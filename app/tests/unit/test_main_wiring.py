"""
Unit tests for how AutoHealService.start() wires its components together.

Uses the patching approach from test_main_lifecycle.py and test_prometheus_start.py
(patching the component classes on ``app.main``) so no Docker daemon is needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import AutoHealService


def _make_config() -> MagicMock:
    config = MagicMock()
    config.observability.prometheus_enabled = False
    config.observability.log_level = "INFO"
    config.monitor.interval_seconds = 30
    config.notifications.enabled = False
    config.notifications.services = []
    config.uptime_kuma.enabled = False
    config.ui.listen_address = "127.0.0.1"  # only logged here
    config.ui.listen_port = 3131
    return config


@pytest.mark.asyncio
class TestUptimeKumaWiring:
    """The engine receives the Uptime Kuma monitor the service built, at construction."""

    async def test_engine_is_built_with_the_services_uptime_kuma_monitor(self):
        built = []

        def build_kuma() -> MagicMock:
            built.append("kuma")
            return MagicMock()

        def build_engine(*_args, **_kwargs) -> MagicMock:
            built.append("engine")
            return MagicMock(start=AsyncMock())

        with (
            patch("app.main.config_manager") as mock_cm,
            patch("app.main.DockerClientWrapper") as mock_docker_cls,
            patch("app.main.UptimeKumaMonitor") as mock_kuma_cls,
            patch("app.main.MonitoringEngine") as mock_engine_cls,
            patch("app.main.init_api"),
            patch("app.main.notification_manager") as mock_notif,
        ):
            mock_cm.get_config.return_value = _make_config()
            mock_kuma_cls.side_effect = build_kuma
            mock_engine_cls.side_effect = build_engine
            mock_notif.start = AsyncMock()

            service = AutoHealService()
            await service.start()

        assert built == ["kuma", "engine"]
        assert service.uptime_kuma_monitor is not None
        mock_engine_cls.assert_called_once_with(
            mock_docker_cls.return_value, uptime_kuma_monitor=service.uptime_kuma_monitor
        )
        assert service.monitoring_engine is not None
        assert service.running is True
