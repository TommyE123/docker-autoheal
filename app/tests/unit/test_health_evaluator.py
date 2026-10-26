"""
Unit tests for ``app.monitor.health.HealthEvaluator`` and the engine's hand-off to it.

The decision logic is covered through the engine in test_health_evaluation.py. These tests
cover what the evaluator owns on its own: the Uptime Kuma dependency it is given, and the
stable identifier the engine passes in.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.monitor.health import HealthEvaluator
from app.tests.unit.conftest import make_container


def kuma_reporting_down() -> MagicMock:
    monitor = MagicMock()
    monitor.should_restart_from_uptime_kuma = AsyncMock(return_value=True)
    return monitor


@pytest.mark.asyncio
class TestUptimeKumaDependency:
    async def test_constructor_argument_is_consulted(self, docker_client):
        monitor = kuma_reporting_down()
        evaluator = HealthEvaluator(docker_client, uptime_kuma_monitor=monitor)
        container, info = make_container(name="web")

        result = await evaluator.evaluate(container, info, "web-id")

        assert result == (True, "Uptime-Kuma monitor reports DOWN")
        monitor.should_restart_from_uptime_kuma.assert_awaited_once_with("web-id")

    async def test_defaults_to_no_monitor(self, docker_client):
        evaluator = HealthEvaluator(docker_client)
        container, info = make_container(name="web")

        assert evaluator.uptime_kuma_monitor is None
        assert await evaluator.evaluate(container, info, "web-id") == (False, "")

    async def test_monitor_is_not_consulted_without_a_stable_id(self, docker_client):
        monitor = kuma_reporting_down()
        evaluator = HealthEvaluator(docker_client, uptime_kuma_monitor=monitor)
        container, info = make_container(name="web")

        assert await evaluator.evaluate(container, info, None) == (False, "")
        monitor.should_restart_from_uptime_kuma.assert_not_called()


@pytest.mark.asyncio
class TestEngineHandOff:
    def test_engine_has_no_uptime_kuma_monitor_by_default(self, engine):
        assert engine.uptime_kuma_monitor is None

    async def test_monitor_attached_to_the_engine_reaches_the_evaluator(self, engine):
        monitor = kuma_reporting_down()
        container, info = make_container(name="web")

        engine.uptime_kuma_monitor = monitor

        assert engine.uptime_kuma_monitor is monitor
        assert await engine._evaluate_container_health(container, info) == (
            True,
            "Uptime-Kuma monitor reports DOWN",
        )

    async def test_engine_passes_its_stable_identifier(self, engine, monkeypatch):
        monitor = kuma_reporting_down()
        engine.uptime_kuma_monitor = monitor
        monkeypatch.setattr(engine, "get_stable_identifier", lambda info: "stable-from-engine")
        container, info = make_container(name="web")

        await engine._evaluate_container_health(container, info)

        monitor.should_restart_from_uptime_kuma.assert_awaited_once_with("stable-from-engine")
