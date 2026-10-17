"""
Unit tests for ``UptimeKumaMonitor``.

``UptimeKumaMonitor`` only talks to the config manager and an injected
``UptimeKumaClient``-shaped object, so it is tested with the shared
``FakeUptimeKumaClient`` fixture (see ``conftest.py``) rather than faking
aiohttp directly. The polling loop is exercised by faking ``asyncio.sleep``
and stopping the loop after a controlled number of iterations, so no test
depends on real timing.
"""

import asyncio
import logging
from typing import cast

import pytest

from app.config.config_manager import UptimeKumaMapping, config_manager
from app.monitor import uptime_kuma_monitor as uptime_kuma_monitor_module
from app.monitor.uptime_kuma_monitor import UptimeKumaMonitor
from app.tests.unit.conftest import FakeUptimeKumaClient
from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient


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


def _install_client(monitor: UptimeKumaMonitor, fake_client: FakeUptimeKumaClient) -> None:
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
        assert monitor._ambiguous_mappings == set()


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
        fake_client = FakeUptimeKumaClient(
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
        fake_client = FakeUptimeKumaClient(connect_result=False)
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
        fake_client = FakeUptimeKumaClient(connect_result=True, monitors=[])
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
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "web", "status": 1},
                    {"friendly_name": "db", "status": 0},
                ]
            ),
        )

        await monitor._refresh_monitor_cache()

        assert set(monitor._monitor_cache) == {"web", "db"}

    async def test_failed_fetch_leaves_empty_cache(self):
        monitor = UptimeKumaMonitor()
        _install_client(monitor, FakeUptimeKumaClient(get_all_monitors_fails=True))

        await monitor._refresh_monitor_cache()

        assert monitor._monitor_cache == {}


@pytest.mark.asyncio
class TestUpdateStatusCache:
    async def test_no_mappings_configured_clears_cached_statuses_without_fetching(self):
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["web"] = 0
        fake_client = FakeUptimeKumaClient()
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {}
        assert fake_client.get_all_monitors_calls == 0

    async def test_caches_status_for_each_mapping(self):
        _add_mapping("web", "Web Monitor")
        _add_mapping("db", "DB Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(
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
        fake_client = FakeUptimeKumaClient(
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
        _install_client(
            monitor,
            FakeUptimeKumaClient(monitors=[{"friendly_name": "Other Monitor", "status": 1}]),
        )

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {}

    async def test_vanished_monitor_among_other_monitors_clears_stale_status(self):
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["web"] = 0
        _install_client(
            monitor,
            FakeUptimeKumaClient(monitors=[{"friendly_name": "Other Monitor", "status": 1}]),
        )

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {}

    async def test_last_mapped_monitor_disappearing_clears_cached_down_status(self):
        # A successful fetch that returns [] is a valid refresh, not a failure.
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["web"] = 0
        _install_client(monitor, FakeUptimeKumaClient(monitors=[]))

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {}
        assert await monitor.should_restart_from_uptime_kuma("web") is False

    async def test_failed_fetch_preserves_cached_down_status(self):
        # The real client returns None (not []) when the request fails.
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}])
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()
        fake_client.get_all_monitors_fails = True

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 0}

    async def test_failed_fetch_drops_remapped_status_and_preserves_other_container(self):
        _add_mapping("web", "Old Monitor")
        _add_mapping("db", "DB Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(
            monitors=[
                {"friendly_name": "Old Monitor", "status": 0},
                {"friendly_name": "DB Monitor", "status": 1},
            ]
        )
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()
        config = config_manager.get_config()
        config.uptime_kuma_mappings = [
            UptimeKumaMapping(container_id="web", monitor_friendly_name="New Monitor"),
            UptimeKumaMapping(container_id="db", monitor_friendly_name="DB Monitor"),
        ]
        config_manager.update_config(config)
        fake_client.get_all_monitors_fails = True

        await monitor._update_status_cache()

        assert monitor.get_container_status("web") is None
        assert monitor.get_container_status("db") == 1

    async def test_failed_fetch_drops_status_when_its_source_mapping_is_removed(self):
        _add_mapping("web", "Monitor A")
        _add_mapping("web", "Monitor B")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(
            monitors=[
                {"friendly_name": "Monitor A", "status": 1},
                {"friendly_name": "Monitor B", "status": 0},
            ]
        )
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()
        assert monitor.get_container_status("web") == 0

        config = config_manager.get_config()
        config.uptime_kuma_mappings = [
            UptimeKumaMapping(container_id="web", monitor_friendly_name="Monitor A")
        ]
        config_manager.update_config(config)
        fake_client.get_all_monitors_fails = True

        await monitor._update_status_cache()

        assert monitor.get_container_status("web") is None

    async def test_missing_client_is_treated_as_failed_fetch_and_keeps_configured_status(
        self, caplog
    ):
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        monitor.client = None
        monitor._container_status_cache["web"] = 1
        monitor._container_status_mapping_cache["web"] = "Web Monitor"
        monitor._container_status_cache["old"] = 0
        monitor._container_status_mapping_cache["old"] = "Old Monitor"

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 1}
        assert "Uptime-Kuma client not initialized" in caplog.text

    async def test_status_for_unmapped_container_is_dropped(self):
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["old"] = 0
        _install_client(
            monitor,
            FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 1}]),
        )

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 1}

    @pytest.mark.parametrize(
        "monitor_names",
        [("Web Monitor", "Deleted Monitor"), ("Deleted Monitor", "Web Monitor")],
        ids=["present-mapping-first", "present-mapping-last"],
    )
    async def test_duplicate_mappings_keep_status_from_present_monitor(self, monitor_names):
        for monitor_name in monitor_names:
            _add_mapping("web", monitor_name)
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}]),
        )

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 0}

    @pytest.mark.parametrize(
        "statuses",
        [(1, 0), (0, 1)],
        ids=["up-then-down", "down-then-up"],
    )
    async def test_duplicate_friendly_name_is_ambiguous_and_not_cached(self, statuses, caplog):
        """Two monitors sharing the mapped name must not resolve to either one."""
        _add_mapping("db", "Database")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "Database", "status": statuses[0]},
                    {"friendly_name": "Database", "status": statuses[1]},
                ]
            ),
        )

        with caplog.at_level(logging.WARNING):
            await monitor._update_status_cache()

        assert monitor._container_status_cache == {}
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert warnings[0].getMessage() == (
            "Uptime-Kuma monitor name 'Database' mapped to db matches 2 monitors - "
            "ignoring its status because the name is ambiguous, so it will not "
            "trigger an automatic restart"
        )

    async def test_ambiguous_name_warns_once_until_it_is_unique_again(self, caplog):
        _add_mapping("db", "Database")
        monitor = UptimeKumaMonitor()
        duplicates = [
            {"friendly_name": "Database", "status": 0},
            {"friendly_name": "Database", "status": 1},
        ]
        fake_client = FakeUptimeKumaClient(monitors=duplicates)
        _install_client(monitor, fake_client)

        def ambiguity_warnings() -> int:
            return sum(
                r.levelno == logging.WARNING and "ambiguous" in r.getMessage()
                for r in caplog.records
            )

        with caplog.at_level(logging.WARNING):
            await monitor._update_status_cache()
            await monitor._update_status_cache()
            assert ambiguity_warnings() == 1

            fake_client.monitors = [{"friendly_name": "Database", "status": 0}]
            await monitor._update_status_cache()
            assert monitor._container_status_cache == {"db": 0}

            fake_client.monitors = duplicates
            await monitor._update_status_cache()
            assert ambiguity_warnings() == 2
            assert monitor._container_status_cache == {}

    async def test_duplicate_mapping_entries_warn_once_and_get_no_status(self, caplog):
        """Identical mapping entries for one container must not warn once per entry."""
        _add_mapping("db", "Database")
        _add_mapping("db", "Database")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "Database", "status": 1},
                    {"friendly_name": "Database", "status": 0},
                ]
            ),
        )

        with caplog.at_level(logging.WARNING):
            await monitor._update_status_cache()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert monitor._container_status_cache == {}

    async def test_each_newly_ambiguous_mapping_is_warned_about(self, caplog):
        _add_mapping("db", "Database")
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(
            monitors=[
                {"friendly_name": "Database", "status": 1},
                {"friendly_name": "Database", "status": 1},
                {"friendly_name": "Web Monitor", "status": 1},
            ]
        )
        _install_client(monitor, fake_client)

        with caplog.at_level(logging.WARNING):
            await monitor._update_status_cache()
            fake_client.monitors = [
                *fake_client.monitors,
                {"friendly_name": "Web Monitor", "status": 0},
            ]
            await monitor._update_status_cache()

        warned = sorted(
            r.getMessage().split(" mapped to ")[1].split(" ")[0]
            for r in caplog.records
            if r.levelno == logging.WARNING
        )
        assert warned == ["db", "web"]
        assert monitor._container_status_cache == {}

    async def test_duplicate_friendly_name_clears_previously_cached_status(self):
        """A status cached before the name became ambiguous must not survive."""
        _add_mapping("db", "Database")
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["db"] = 0
        _install_client(
            monitor,
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "Database", "status": 1},
                    {"friendly_name": "Database", "status": 1},
                ]
            ),
        )

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {}

    async def test_duplicate_name_does_not_affect_other_mappings(self):
        _add_mapping("db", "Database")
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "Database", "status": 0},
                    {"friendly_name": "Web Monitor", "status": 0},
                    {"friendly_name": "Database", "status": 1},
                ]
            ),
        )

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 0}

    @pytest.mark.parametrize(
        "mapped_names",
        [("Database", "Web Monitor"), ("Web Monitor", "Database")],
        ids=["ambiguous-first", "ambiguous-last"],
    )
    async def test_container_with_any_ambiguous_mapping_gets_no_status(self, mapped_names):
        """A container's other, unique mapping must not restore a status that its
        ambiguous mapping dropped, whatever order the mappings are stored in."""
        for name in mapped_names:
            _add_mapping("db", name)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        monitor._container_status_cache["db"] = 0
        _install_client(
            monitor,
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "Database", "status": 1},
                    {"friendly_name": "Web Monitor", "status": 0},
                    {"friendly_name": "Database", "status": 0},
                ]
            ),
        )

        await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 0}

    async def test_error_fetching_metrics_is_logged_and_leaves_cache_unchanged(self, caplog):
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 1}])
        _install_client(monitor, fake_client)

        await monitor._update_status_cache()
        fake_client.get_all_monitors_error = RuntimeError("upstream error")

        with caplog.at_level(logging.ERROR):
            await monitor._update_status_cache()

        assert monitor._container_status_cache == {"web": 1}
        assert fake_client.get_all_monitors_calls == 2
        assert any(
            record.levelno == logging.ERROR and "upstream error" in record.getMessage()
            for record in caplog.records
        )


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
        fake_client = FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}])
        _install_client(monitor, fake_client)

        result = await monitor.should_restart_from_uptime_kuma("web")

        assert result is False
        assert fake_client.get_all_monitors_calls == 0  # cache refresh skipped entirely

    async def test_false_when_container_not_mapped(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}]),
        )

        assert await monitor.should_restart_from_uptime_kuma("web") is False

    async def test_true_when_mapped_monitor_is_down(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}]),
        )

        assert await monitor.should_restart_from_uptime_kuma("web") is True

    async def test_remapped_container_does_not_restart_from_stale_down_status_during_outage(
        self,
    ):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Old Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(monitors=[{"friendly_name": "Old Monitor", "status": 0}])
        _install_client(monitor, fake_client)

        assert await monitor.should_restart_from_uptime_kuma("web") is True

        config = config_manager.get_config()
        config.uptime_kuma_mappings = [
            UptimeKumaMapping(container_id="web", monitor_friendly_name="New Monitor")
        ]
        config_manager.update_config(config)
        fake_client.get_all_monitors_fails = True

        assert await monitor.should_restart_from_uptime_kuma("web") is False
        assert monitor.get_container_status("web") is None

    async def test_false_when_mapped_monitor_is_up(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 1}]),
        )

        assert await monitor.should_restart_from_uptime_kuma("web") is False

    async def test_false_when_monitor_vanished_after_being_down(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(monitors=[{"friendly_name": "Web Monitor", "status": 0}])
        _install_client(monitor, fake_client)
        assert await monitor.should_restart_from_uptime_kuma("web") is True

        fake_client.monitors = [{"friendly_name": "Other Monitor", "status": 1}]

        assert await monitor.should_restart_from_uptime_kuma("web") is False

    @pytest.mark.parametrize(
        "statuses",
        [(1, 0), (0, 1), (0, 0)],
        ids=["up-then-down", "down-then-up", "both-down"],
    )
    async def test_false_when_mapped_name_matches_several_monitors(self, statuses):
        """An ambiguous monitor identity must never produce a restart decision."""
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("db", "Database")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "Database", "status": statuses[0]},
                    {"friendly_name": "Database", "status": statuses[1]},
                ]
            ),
        )

        assert await monitor.should_restart_from_uptime_kuma("db") is False
        assert monitor.get_container_status("db") is None

    async def test_false_for_duplicate_names_parsed_from_real_metrics(self):
        """End to end from the /metrics parser: Uptime-Kuma reports two monitors
        named "Database" (distinct monitor_id labels), one UP and one DOWN."""
        metrics = (
            'monitor_status{monitor_id="7",monitor_name="Database",'
            'monitor_url="",monitor_hostname="db-a",monitor_port="5432"} 1\n'
            'monitor_status{monitor_id="9",monitor_name="Database",'
            'monitor_url="",monitor_hostname="db-b",monitor_port="5432"} 0\n'
        )
        client = UptimeKumaClient("http://kuma.example", "token")
        parsed = client._parse_monitors_from_metrics(metrics)
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("db", "Database")
        monitor = UptimeKumaMonitor()
        _install_client(monitor, FakeUptimeKumaClient(monitors=parsed))

        assert len(parsed) == 2
        assert await monitor.should_restart_from_uptime_kuma("db") is False

    async def test_false_when_another_mapping_of_the_container_is_ambiguous(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("db", "Database")
        _add_mapping("db", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(
            monitor,
            FakeUptimeKumaClient(
                monitors=[
                    {"friendly_name": "Database", "status": 1},
                    {"friendly_name": "Database", "status": 1},
                    {"friendly_name": "Web Monitor", "status": 0},
                ]
            ),
        )

        assert await monitor.should_restart_from_uptime_kuma("db") is False

    async def test_false_when_mapped_name_becomes_ambiguous_after_down(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("db", "Database")
        monitor = UptimeKumaMonitor()
        fake_client = FakeUptimeKumaClient(monitors=[{"friendly_name": "Database", "status": 0}])
        _install_client(monitor, fake_client)
        assert await monitor.should_restart_from_uptime_kuma("db") is True

        fake_client.monitors = [
            {"friendly_name": "Database", "status": 1},
            {"friendly_name": "Database", "status": 0},
        ]

        assert await monitor.should_restart_from_uptime_kuma("db") is False

    async def test_false_when_status_unavailable(self):
        _enable_uptime_kuma(auto_restart_on_down=True)
        _add_mapping("web", "Web Monitor")
        monitor = UptimeKumaMonitor()
        _install_client(monitor, FakeUptimeKumaClient(monitors=[]))

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
