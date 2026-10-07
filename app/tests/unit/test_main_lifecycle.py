"""
Unit tests for AutoHealService application lifecycle: startup failure
handling, shutdown ordering, signal handling and the process entry point.

Reuses the mocking approach from test_prometheus_start.py (patching
app.main.DockerClientWrapper / MonitoringEngine / UptimeKumaMonitor /
init_api / notification_manager / start_http_server) rather than
duplicating startup-success coverage already provided there.
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_module
from app.main import (
    AutoHealService,
    CancelledErrorFilter,
    get_public_port,
    get_ui_url,
    signal_handler,
)


class TestCancelledErrorFilter:
    """Uvicorn logs a noisy CancelledError traceback during shutdown; it should be dropped."""

    def test_suppresses_cancelled_error_from_uvicorn_error(self):
        record = MagicMock(name="uvicorn.error")
        record.name = "uvicorn.error"
        record.getMessage.return_value = "CancelledError raised during shutdown"

        assert CancelledErrorFilter().filter(record) is False

    def test_allows_other_uvicorn_error_messages(self):
        record = MagicMock()
        record.name = "uvicorn.error"
        record.getMessage.return_value = "some other error"

        assert CancelledErrorFilter().filter(record) is True

    def test_allows_cancelled_error_from_other_loggers(self):
        record = MagicMock()
        record.name = "app.main"
        record.getMessage.return_value = "CancelledError"

        assert CancelledErrorFilter().filter(record) is True


class TestAutoHealServiceStop:
    """AutoHealService.stop() shutdown ordering and per-component error handling."""

    @pytest.mark.asyncio
    async def test_stop_with_no_components_initialized(self):
        service = AutoHealService()
        service.running = True

        await service.stop()

        assert service.running is False

    @pytest.mark.asyncio
    async def test_stop_order_kuma_then_engine_then_notifications_then_docker(self):
        service = AutoHealService()
        order = []

        service.uptime_kuma_monitor = MagicMock()
        service.uptime_kuma_monitor.stop = AsyncMock(side_effect=lambda: order.append("kuma"))
        service.monitoring_engine = MagicMock()
        service.monitoring_engine.stop = AsyncMock(side_effect=lambda: order.append("engine"))
        service.notification_manager = MagicMock()
        service.notification_manager.stop = AsyncMock(
            side_effect=lambda: order.append("notifications")
        )
        service.docker_client = MagicMock()
        service.docker_client.close = MagicMock(side_effect=lambda: order.append("docker"))

        await service.stop()

        assert order == ["kuma", "engine", "notifications", "docker"]

    @pytest.mark.asyncio
    async def test_stop_stops_notification_manager(self):
        service = AutoHealService()
        service.notification_manager = MagicMock()
        service.notification_manager.stop = AsyncMock()

        await service.stop()

        service.notification_manager.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_continues_after_notification_manager_stop_raises(self):
        service = AutoHealService()
        service.notification_manager = MagicMock()
        service.notification_manager.stop = AsyncMock(
            side_effect=RuntimeError("notif boom")
        )
        service.docker_client = MagicMock()

        await service.stop()

        service.docker_client.close.assert_called_once()
        assert service.running is False

    @pytest.mark.asyncio
    async def test_stop_continues_after_kuma_stop_raises(self):
        service = AutoHealService()
        service.uptime_kuma_monitor = MagicMock()
        service.uptime_kuma_monitor.stop = AsyncMock(side_effect=RuntimeError("kuma boom"))
        service.monitoring_engine = MagicMock()
        service.monitoring_engine.stop = AsyncMock()
        service.docker_client = MagicMock()

        await service.stop()

        service.monitoring_engine.stop.assert_awaited_once()
        service.docker_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_continues_after_engine_stop_raises(self):
        service = AutoHealService()
        service.monitoring_engine = MagicMock()
        service.monitoring_engine.stop = AsyncMock(side_effect=RuntimeError("engine boom"))
        service.docker_client = MagicMock()

        await service.stop()

        service.docker_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_swallows_docker_close_error(self):
        service = AutoHealService()
        service.docker_client = MagicMock()
        service.docker_client.close.side_effect = RuntimeError("close boom")

        await service.stop()  # must not raise

        assert service.running is False


class TestAutoHealServiceStartFailure:
    """Failure handling for AutoHealService.start(): partial init + notification cleanup + re-raise."""

    def _make_config(self, uptime_kuma_enabled=False):
        config = MagicMock()
        config.observability.prometheus_enabled = False
        config.observability.metrics_port = 9090
        config.observability.log_level = "INFO"
        config.monitor.interval_seconds = 30
        config.notifications.enabled = False
        config.notifications.services = []
        config.uptime_kuma.enabled = uptime_kuma_enabled
        config.ui.listen_address = "0.0.0.0"
        config.ui.listen_port = 3131
        return config

    @pytest.mark.asyncio
    async def test_docker_client_init_failure_stops_notifications_and_reraises(self):
        with patch('app.main.config_manager') as mock_cm, \
             patch('app.main.DockerClientWrapper', side_effect=RuntimeError("docker unavailable")), \
             patch('app.main.notification_manager') as mock_notif:
            mock_cm.get_config.return_value = self._make_config()
            mock_notif.stop = AsyncMock()

            service = AutoHealService()

            with pytest.raises(RuntimeError, match="docker unavailable"):
                await service.start()

            mock_notif.stop.assert_awaited_once()
            assert service.docker_client is None
            assert service.monitoring_engine is None
            assert service.running is False

    @pytest.mark.asyncio
    async def test_monitoring_engine_init_failure_reraises_and_keeps_docker_client(self):
        with patch('app.main.config_manager') as mock_cm, \
             patch('app.main.DockerClientWrapper'), \
             patch('app.main.MonitoringEngine', side_effect=RuntimeError("engine broke")), \
             patch('app.main.notification_manager') as mock_notif:
            mock_cm.get_config.return_value = self._make_config()
            mock_notif.stop = AsyncMock()

            service = AutoHealService()

            with pytest.raises(RuntimeError, match="engine broke"):
                await service.start()

            mock_notif.stop.assert_awaited_once()
            # Docker client was already assigned before the failing step (partial init).
            assert service.docker_client is not None
            assert service.monitoring_engine is None

    @pytest.mark.asyncio
    async def test_config_load_failure_reraises_before_any_component_created(self):
        with patch('app.main.config_manager') as mock_cm, \
             patch('app.main.DockerClientWrapper') as mock_docker_cls, \
             patch('app.main.notification_manager') as mock_notif:
            mock_cm.get_config.side_effect = RuntimeError("config broke")
            mock_notif.stop = AsyncMock()

            service = AutoHealService()

            with pytest.raises(RuntimeError, match="config broke"):
                await service.start()

            mock_notif.stop.assert_awaited_once()
            mock_docker_cls.assert_not_called()
            assert service.docker_client is None

    @pytest.mark.asyncio
    async def test_startup_log_reports_the_api_version(self, caplog):
        # The version comes from the FastAPI app (kept current by Release Please),
        # not a literal in main.py that can go stale.
        with patch('app.main.config_manager') as mock_cm, \
             patch('app.main.notification_manager') as mock_notif, \
             caplog.at_level("INFO", logger="app.main"):
            mock_cm.get_config.side_effect = RuntimeError("config broke")
            mock_notif.stop = AsyncMock()

            with pytest.raises(RuntimeError):
                await AutoHealService().start()

        assert f"Starting Docker Auto-Heal Service v{main_module.app.version}" in caplog.text

    @pytest.mark.asyncio
    async def test_uptime_kuma_start_failure_does_not_abort_startup(self):
        with patch('app.main.config_manager') as mock_cm, \
             patch('app.main.DockerClientWrapper'), \
             patch('app.main.MonitoringEngine') as mock_engine_cls, \
             patch('app.main.UptimeKumaMonitor') as mock_kuma_cls, \
             patch('app.main.init_api'), \
             patch('app.main.notification_manager') as mock_notif, \
             patch('app.main.start_http_server'):
            mock_cm.get_config.return_value = self._make_config(uptime_kuma_enabled=True)
            mock_engine_cls.return_value.start = AsyncMock()
            mock_kuma_cls.return_value.start = AsyncMock(side_effect=RuntimeError("kuma down"))
            mock_notif.start = AsyncMock()

            service = AutoHealService()
            await service.start()  # must not raise

            assert service.running is True
            mock_notif.stop.assert_not_called()


class TestUiUrl:
    """Startup URL reporting: a real URL only when a public host is supplied; bind unaffected."""

    @staticmethod
    def _config(address="0.0.0.0", port=3131):
        config = MagicMock()
        config.ui.listen_address = address
        config.ui.listen_port = port
        config.observability.log_level = "INFO"
        config.observability.prometheus_enabled = False
        config.monitor.interval_seconds = 30
        config.notifications.enabled = False
        config.uptime_kuma.enabled = False
        return config

    @staticmethod
    async def _start_and_capture_log(config, caplog):
        with (
            patch("app.main.config_manager") as mock_cm,
            patch("app.main.DockerClientWrapper"),
            patch("app.main.MonitoringEngine") as mock_engine_cls,
            patch("app.main.UptimeKumaMonitor"),
            patch("app.main.init_api"),
            patch("app.main.notification_manager") as mock_notif,
            caplog.at_level("INFO", logger="app.main"),
        ):
            mock_cm.get_config.return_value = config
            mock_engine_cls.return_value.start = AsyncMock()
            mock_notif.start = AsyncMock()

            await AutoHealService().start()

        return caplog.text

    def test_no_url_without_a_public_host(self, monkeypatch):
        monkeypatch.delenv("AUTOHEAL_PUBLIC_HOST", raising=False)
        monkeypatch.delenv("AUTOHEAL_PUBLIC_PORT", raising=False)

        assert get_ui_url(self._config()) is None

    def test_a_port_alone_does_not_make_a_url(self, monkeypatch):
        monkeypatch.delenv("AUTOHEAL_PUBLIC_HOST", raising=False)
        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "3132")

        assert get_ui_url(self._config()) is None

    def test_public_host_and_port_make_the_user_facing_url(self, monkeypatch):
        monkeypatch.setenv("AUTOHEAL_PUBLIC_HOST", "192.0.2.10")
        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "3132")

        assert get_ui_url(self._config()) == "http://192.0.2.10:3132"

    def test_blank_public_values_fall_back(self, monkeypatch):
        # Blank host (what an unset Compose variable becomes) means no URL.
        monkeypatch.setenv("AUTOHEAL_PUBLIC_HOST", "  ")
        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "3132")
        assert get_ui_url(self._config()) is None

        # Blank port falls back to the listen port.
        monkeypatch.setenv("AUTOHEAL_PUBLIC_HOST", "192.0.2.10")
        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "")
        assert get_ui_url(self._config()) == "http://192.0.2.10:3131"

    @pytest.mark.asyncio
    async def test_startup_log_reports_the_public_url_when_supplied(
        self, monkeypatch, caplog
    ):
        monkeypatch.setenv("AUTOHEAL_PUBLIC_HOST", "192.0.2.10")
        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "3132")

        log = await self._start_and_capture_log(self._config(), caplog)

        assert "Web UI available at http://192.0.2.10:3132" in log
        assert "API documentation available at http://192.0.2.10:3132/docs" in log
        assert "0.0.0.0" not in log

    def test_public_port_is_the_trimmed_value_or_none(self, monkeypatch):
        monkeypatch.delenv("AUTOHEAL_PUBLIC_PORT", raising=False)
        assert get_public_port() is None

        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "  ")
        assert get_public_port() is None

        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "3132")
        assert get_public_port() == "3132"

    @pytest.mark.asyncio
    async def test_startup_log_reports_the_published_port_when_no_host_is_supplied(
        self, monkeypatch, caplog
    ):
        # The dev Compose override: published port known, host address deliberately not.
        monkeypatch.setenv("AUTOHEAL_PUBLIC_HOST", "")
        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "3132")

        log = await self._start_and_capture_log(self._config(), caplog)

        assert "Web UI published on host port 3132 (container port 3131)" in log
        assert (
            "API documentation published on host port 3132 at /docs (container port 3131)"
            in log
        )
        assert "0.0.0.0" not in log
        assert "http://" not in log
        assert "listening on" not in log

    @pytest.mark.asyncio
    async def test_startup_log_does_not_present_the_bind_address_as_a_url(
        self, monkeypatch, caplog
    ):
        monkeypatch.delenv("AUTOHEAL_PUBLIC_HOST", raising=False)
        monkeypatch.delenv("AUTOHEAL_PUBLIC_PORT", raising=False)

        log = await self._start_and_capture_log(self._config(), caplog)

        assert "Web UI listening on 0.0.0.0:3131" in log
        assert "API documentation listening on 0.0.0.0:3131/docs" in log
        assert "http://0.0.0.0" not in log
        assert "available at" not in log

    @pytest.mark.asyncio
    async def test_server_still_binds_to_all_interfaces_with_a_public_host_set(
        self, monkeypatch
    ):
        monkeypatch.setenv("AUTOHEAL_PUBLIC_HOST", "192.0.2.10")
        monkeypatch.setenv("AUTOHEAL_PUBLIC_PORT", "3132")

        with (
            patch("app.main.config_manager") as mock_cm,
            patch("app.main.uvicorn") as mock_uvicorn,
        ):
            mock_cm.get_config.return_value = self._config()
            mock_uvicorn.Server.return_value.serve = AsyncMock()

            await main_module.run_api_server()

        kwargs = mock_uvicorn.Config.call_args.kwargs
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 3131


class TestSignalHandler:
    def teardown_method(self):
        main_module.service = None

    @pytest.mark.asyncio
    async def test_signal_handler_schedules_service_stop(self):
        mock_service = MagicMock()
        mock_service.stop = AsyncMock()
        main_module.service = mock_service

        signal_handler(signal.SIGTERM, None)
        await asyncio.sleep(0)  # let the scheduled task run

        mock_service.stop.assert_awaited_once()

    def test_signal_handler_noop_when_service_not_set(self):
        main_module.service = None

        signal_handler(signal.SIGINT, None)  # must not raise


class TestRunApiServer:
    @pytest.mark.asyncio
    async def test_run_api_server_configures_and_serves(self):
        config = MagicMock()
        config.observability.log_level = "WARNING"
        config.ui.listen_address = "127.0.0.1"
        config.ui.listen_port = 3131

        with patch('app.main.config_manager') as mock_cm, \
             patch('app.main.uvicorn') as mock_uvicorn:
            mock_cm.get_config.return_value = config
            mock_server_instance = MagicMock()
            mock_server_instance.serve = AsyncMock()
            mock_uvicorn.Server.return_value = mock_server_instance

            await main_module.run_api_server()

            mock_uvicorn.Config.assert_called_once_with(
                main_module.app,
                host="127.0.0.1",
                port=3131,
                log_level="warning",
                access_log=False,
                log_config=None,
            )
            mock_uvicorn.Server.assert_called_once_with(mock_uvicorn.Config.return_value)
            mock_server_instance.serve.assert_awaited_once()


class TestAutoHealServiceRun:
    @pytest.mark.asyncio
    async def test_run_starts_loops_then_stops(self):
        service = AutoHealService()
        service.start = AsyncMock(side_effect=lambda: setattr(service, 'running', True))
        service.stop = AsyncMock()

        async def fake_sleep(_delay):
            service.running = False

        with patch('app.main.asyncio.sleep', side_effect=fake_sleep):
            await service.run()

        service.start.assert_awaited_once()
        service.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_stops_on_cancelled_error_during_sleep(self):
        service = AutoHealService()
        service.start = AsyncMock(side_effect=lambda: setattr(service, 'running', True))
        service.stop = AsyncMock()

        with patch('app.main.asyncio.sleep', side_effect=asyncio.CancelledError):
            await service.run()  # CancelledError must be swallowed, not propagated

        service.stop.assert_awaited_once()


class TestMain:
    def teardown_method(self):
        main_module.service = None

    @pytest.mark.asyncio
    async def test_main_registers_signal_handlers_and_wires_components(self):
        fake_service = MagicMock()
        fake_service.run = AsyncMock()
        fake_service.running = False

        with patch('app.main.signal.signal') as mock_signal, \
             patch('app.main.AutoHealService', return_value=fake_service), \
             patch('app.main.run_api_server', new=AsyncMock()):
            await main_module.main()

            mock_signal.assert_any_call(signal.SIGINT, signal_handler)
            mock_signal.assert_any_call(signal.SIGTERM, signal_handler)
            assert main_module.service is fake_service
            fake_service.run.assert_awaited_once()
            fake_service.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_main_stops_service_in_finally_if_still_running(self):
        fake_service = MagicMock()
        fake_service.run = AsyncMock()
        fake_service.stop = AsyncMock()
        fake_service.running = True

        with patch('app.main.signal.signal'), \
             patch('app.main.AutoHealService', return_value=fake_service), \
             patch('app.main.run_api_server', new=AsyncMock()):
            await main_module.main()

            fake_service.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_main_swallows_cancelled_error_from_gather(self):
        fake_service = MagicMock()
        fake_service.run = MagicMock(return_value=None)
        fake_service.running = False

        with patch('app.main.signal.signal'), \
             patch('app.main.AutoHealService', return_value=fake_service), \
             patch('app.main.run_api_server', new=MagicMock(return_value=None)), \
             patch('app.main.asyncio.gather', side_effect=asyncio.CancelledError):
            await main_module.main()  # must not raise

    @pytest.mark.asyncio
    async def test_main_stops_service_after_generic_exception_from_gather(self):
        fake_service = MagicMock()
        fake_service.run = MagicMock(return_value=None)
        fake_service.stop = AsyncMock()
        fake_service.running = True

        with patch('app.main.signal.signal'), \
             patch('app.main.AutoHealService', return_value=fake_service), \
             patch('app.main.run_api_server', new=MagicMock(return_value=None)), \
             patch('app.main.asyncio.gather', side_effect=RuntimeError("gather boom")):
            await main_module.main()  # must not raise

            fake_service.stop.assert_awaited_once()
