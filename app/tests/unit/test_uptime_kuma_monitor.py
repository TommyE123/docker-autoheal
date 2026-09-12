"""
Unit tests for ``UptimeKumaMonitor``.

``UptimeKumaMonitor`` only talks to the config manager and an injected
``UptimeKumaClient``-shaped object, so it is tested with a lightweight fake
client (mirroring ``_FakeUptimeKumaClient`` in ``test_api.py``) rather than
faking aiohttp directly. The polling loop is exercised by faking
``asyncio.sleep`` and stopping the loop after a controlled number of
iterations, so no test depends on real timing.
"""

import asyncio
from typing import cast

import pytest

from app.config.config_manager import UptimeKumaMapping, config_manager
from app.monitor import uptime_kuma_monitor as uptime_kuma_monitor_module
from app.monitor.uptime_kuma_monitor import UptimeKumaMonitor
from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient


class _FakeUptimeKumaClient:
    """In-memory stand-in for ``UptimeKumaClient``. No real HTTP is used."""

    def __init__(self, connect_result: bool = True, monitors=None, get_all_monitors_error=None):
        self.connect_result = connect_result
        self.monitors = monitors if monitors is not None else []
        self.get_all_monitors_error = get_all_monitors_error
        self.get_all_monitors_calls = 0

    async def connect(self) -> bool:
        return self.connect_result

    async def get_all_monitors(self):
        self.get_all_monitors_calls += 1
        if self.get_all_monitors_error is not None:
            raise self.get_all_monitors_error
        return self.monitors


def _enable_uptime_kuma(auto_restart_on_down: bool = True):
    config = config_manager.get_config()
    config.uptime_kuma.enabled = True
    config.uptime_kuma.server_url = "http://kuma.example"
    config.uptime_kuma.api_token = "token"
    config.uptime_kuma.auto_restart_on_down = auto_restart_on_down
    config_manager.update_config(config)


def _add_mapping(container_id: str, monitor_friendly_name: str):
    config = config_manager.get_config()
    config.uptime_kuma_mappings.append(
        UptimeKumaMapping(container_id=container_id, monitor_friendly_name=monitor_friendly_name)
    )
    config_manager.update_config(config)


def _install_client(monitor: UptimeKumaMonitor, fake_client: _FakeUptimeKumaClient) -> None:
    """Attach a fake client, satisfying the ``Optional[UptimeKumaClient]`` type."""
    monitor.client = cast(UptimeKumaClient, fake_client)


class TestInit:
    def test_starts_with_no_client_and_empty_caches(self):
        monitor = UptimeKumaMonitor()

        assert monitor.client is None
        assert monitor._running is False
        assert monitor._task is None
        assert monitor._monitor_cache == {}
        assert monitor._container_status_cache == {}


@pytest.mark.asyncio
class TestStart:
    async def test_disabled_integration_leaves_client_unset(self):
        monitor = UptimeKumaMonitor()

        await monitor.start()

        assert monitor.client is None
        assert monitor._running is False

    async def test_enabled_but_unconfigured_leaves_client_unset(self):
        config = config_manager.get_config()
        config.uptime_kuma.enabled = True
        config_manager.update_config(config)
        monitor = UptimeKumaMonitor()

        await monitor.start()

        assert monitor.client is None
        assert monitor._running is False

    async def test_successful_connect_builds_cache_and_starts_loop(self, monkeypatch):
        _enable_uptime_kuma()
        fake_client = _FakeUptimeKumaClient(
            connect_result=True, monitors=[{"friendly_name": "web", "status": 1}]
        )
        monkeypatch.setattr(
            uptime_kuma_monitor_module, "UptimeKumaClient", lambda *a, **k: fake_client
        )
        monitor = UptimeKumaMonitor()

        await monitor.start()

        assert monitor.client is fake_client
        assert monitor._monitor_cache == {"web": {"friendly_name": "web", "status": 1}}
        assert monitor._running is True
        assert monitor._task is not None

        await monitor.stop()

    async def test_failed_connect_does_not_start_loop(self, monkeypatch):
        _enable_uptime_kuma()
        fake_client = _FakeUptimeKumaClient(connect_result=False)
        monkeypatch.setattr(
            uptime_kuma_monitor_module, "UptimeKumaClient", lambda *a, **k: fake_client
        )
        monitor = UptimeKumaMonitor()

        await monitor.start()

        assert monitor.client is fake_client
        assert monitor._running is False
        assert monitor._task is None

    async def test_unexpected_error_is_caught_and_logged(self, monkeypatch):
        _enable_uptime_kuma()

        def _raise(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(uptime_kuma_monitor_module, "UptimeKumaClient", _raise)
        monitor = UptimeKumaMonitor()

        await monitor.start()  # must not raise

        assert monitor._running is False


@pytest.mark.asyncio
class TestStop:
    async def test_stop_without_task_is_a_noop(self):
        monitor = UptimeKumaMonitor()

        await monitor.stop()  # must not raise

        assert monitor._running is False

    async def test_stop_cancels_running_task(self, monkeypatch):
        _enable_uptime_kuma()
        fake_client = _FakeUptimeKumaClient(connect_result=True, monitors=[])
        monkeypatch.setattr(
            uptime_kuma_monitor_module, "UptimeKumaClient", lambda *a, **k: fake_client
        )
        monitor = UptimeKumaMonitor()
        await monitor.start()
        task = monitor._task
        assert task is not None

        await monitor.stop()

        assert monitor._running is False
        assert task.cancelled() or task.done()

    async def test_stop_logs_and_swallows_unexpected_task_error(self):
        monitor = UptimeKumaMonitor()
        monitor._running = True

        async def _failing():
            raise RuntimeError("unexpected failure")

        monitor._task = asyncio.create_task(_failing())
        await asyncio.sleep(0)  # let the task fail before stop() awaits it

        await monitor.stop()  # must not raise

        assert monitor._running is False


@pytest.mark.asyncio
class TestRefreshMonitorCache:
    async def test_noop_when_client_not_initialized(self):
        monitor = UptimeKumaMonitor()

        await monitor._refresh_monitor_cache()

        assert monitor._monitor_cache == {}

    async def test_caches_monitors_by_friendly_name(self):
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            _FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "web", "status": 1},
                    {"friendly_name": "db", "status": 0},
                ]
            ),
        )

        await monitor._refresh_monitor_cache()

        assert set(monitor._monitor_cache) == {"web", "db"}


@pytest.mark.asyncio
class TestUpdateStatusCache:
    async def test_noop_when_no_mappings_configured(self):
        monitor = UptimeKumaMonitor()
        fake_client = _FakeUptimeKumaClient()
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {}
        assert fake_client.get_all_monitors_calls == 0

    async def test_caches_status_for_each_mapping(self):
        _add_mapping("web", "Web Monitor")
        _add_mapping("db", "DB Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = _FakeUptimeKumaClient(
            monitors=[
                {"friendly_name": "Web Monitor", "status": 1},
                {"friendly_name": "DB Monitor", "status": 0},
            ]
        )
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 1, "db": 0}
        assert fake_client.get_all_monitors_calls == 1

    async def test_fetches_metrics_once_regardless_of_mapping_count(self):
        """Regression test for #94: N mapped containers must not cause N /metrics fetches."""
        _add_mapping("web", "Web Monitor")
        _add_mapping("db", "DB Monitor")
        _add_mapping("cache", "Cache Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = _FakeUptimeKumaClient(
            monitors=[
                {"friendly_name": "Web Monitor", "status": 1},
                {"friendly_name": "DB Monitor", "status": 0},
                {"friendly_name": "Cache Monitor", "status": 1},
            ]
        )
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 1, "db": 0, "cache": 1}
        assert fake_client.get_all_monitors_calls == 1

    async def test_missing_monitor_status_is_skipped(self):
        _add_mapping("web", "Unknown Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(monitor, _FakeUptimeKumaClient(monitors=[]))

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {}

    async def test_error_fetching_metrics_is_logged_and_leaves_cache_unchanged(self):
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["web"] = 1
        fake_client = _FakeUptimeKumaClient(get_all_monitors_error=RuntimeError("upstream error"))
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 1}
        assert fake_client.get_all_monitors_calls == 1


class TestGetContainerStatus:
    def test_returns_none_for_unknown_container(self):
        monitor = UptimeKumaMonitor()

        assert monitor.get_container_status("web") is None

    def test_returns_cached_status(self):
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["web"] = 1

        assert monitor.get_container_status("web") == 1


class TestIsContainerMapped:
    def test_false_when_no_mappings(self):
        monitor = UptimeKumaMonitor()

        assert monitor.is_container_mapped("web") is False

    def test_true_when_container_is_mapped(self):
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()

        assert monitor.is_container_mapped("web") is True

    def test_false_for_unmapped_container(self):
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()

        assert monitor.is_container_mapped("other") is False


@pytest.mark.asyncio
class TestShouldRestartFromUptimeKuma:
    async def test_false_when_auto_restart_disabled(self):
        _enable_uptime_kuma(auto_restart_on_down=False)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = _FakeUptimeKumaClient(
            monitors=[{"friendly_name": "Web Monitor", "status": 0}]
        )
        _install_client(monitor, fake_client)

        result = await monitor.should_restart_from_uptime_kuma("web")

        assert result is False
        assert fake_client.get_all_monitors_calls == 0  # cache refresh skipped entirely

    async def test_false_when_container_not_mapped(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor, _FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}])
        )

        assert await monitor.should_restart_from_uptime_kuma("web") is False

    async def test_true_when_mapped_monitor_is_down(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor, _FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}])
        )

        assert await monitor.should_restart_from_uptime_kuma("web") is True

    async def test_false_when_mapped_monitor_is_up(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor, _FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 1}])
        )

        assert await monitor.should_restart_from_uptime_kuma("web") is False

    async def test_false_when_status_unavailable(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(monitor, _FakeUptimeKumaClient(monitors=[]))

        assert await monitor.should_restart_from_uptime_kuma("web") is False


@pytest.mark.asyncio
class TestMonitoringLoop:
    async def test_calls_update_status_cache_each_iteration_until_stopped(self, monkeypatch):
        monitor = UptimeKumaMonitor()
        monitor._running = True
        calls = []

        async def fake_sleep(_delay):
            return None

        async def fake_update():
            calls.append(1)
            if len(calls) >= 2:
                monitor._running = False

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(monitor, "_update_status_cache", fake_update)

        await monitor._monitoring_loop()

        assert len(calls) == 2

    async def test_cancelled_error_during_sleep_stops_loop_cleanly(self, monkeypatch):
        monitor = UptimeKumaMonitor()
        monitor._running = True

        async def fake_sleep(_delay):
            raise asyncio.CancelledError()

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await monitor._monitoring_loop()  # must not raise

    async def test_error_in_update_status_cache_is_logged_and_loop_continues(self, monkeypatch):
        monitor = UptimeKumaMonitor()
        monitor._running = True
        attempts = []

        async def fake_sleep(_delay):
            return None

        async def flaky_update():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("transient failure")
            monitor._running = False

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(monitor, "_update_status_cache", flaky_update)

        await monitor._monitoring_loop()

        assert len(attempts) == 2
