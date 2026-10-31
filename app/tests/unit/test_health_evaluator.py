"""
Unit tests for ``app.monitor.health.HealthEvaluator`` and the engine's hand-off to it.

The decision logic is covered through the engine in test_health_evaluation.py. These tests
cover what the evaluator owns on its own: the Uptime Kuma dependency it is given, and the
stable identifier the engine passes in.
"""

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config.config_manager import HealthCheckConfig, config_manager
from app.monitor.health import HealthEvaluator
from app.monitor.monitoring_engine import MonitoringEngine
from app.tests.unit.conftest import make_container

if TYPE_CHECKING:
    from docker.models.containers import Container


def web_container() -> tuple[Container, dict]:
    """A ``(container, info)`` pair typed for the evaluator, which takes a real ``Container``"""
    container, info = make_container(name="web")
    return cast("Container", container), info


def kuma_reporting_down() -> MagicMock:
    monitor = MagicMock()
    monitor.should_restart_from_uptime_kuma = AsyncMock(return_value=True)
    return monitor


@pytest.mark.asyncio
class TestUptimeKumaDependency:
    async def test_constructor_argument_is_consulted(self, docker_client):
        monitor = kuma_reporting_down()
        evaluator = HealthEvaluator(docker_client, uptime_kuma_monitor=monitor)
        container, info = web_container()

        result = await evaluator.evaluate(container, info, "web-id")

        assert result == (True, "Uptime-Kuma monitor reports DOWN")
        monitor.should_restart_from_uptime_kuma.assert_awaited_once_with("web-id")

    async def test_defaults_to_no_monitor(self, docker_client):
        evaluator = HealthEvaluator(docker_client)
        container, info = web_container()

        assert evaluator.uptime_kuma_monitor is None
        assert await evaluator.evaluate(container, info, "web-id") == (False, "")

    async def test_monitor_is_not_consulted_without_a_stable_id(self, docker_client):
        monitor = kuma_reporting_down()
        evaluator = HealthEvaluator(docker_client, uptime_kuma_monitor=monitor)
        container, info = web_container()

        assert await evaluator.evaluate(container, info, None) == (False, "")
        monitor.should_restart_from_uptime_kuma.assert_not_called()


@pytest.mark.asyncio
class TestEngineHandOff:
    def test_engine_has_no_uptime_kuma_monitor_by_default(self, engine):
        assert engine.uptime_kuma_monitor is None

    async def test_monitor_passed_to_the_engine_constructor_reaches_the_evaluator(
        self, docker_client
    ):
        monitor = kuma_reporting_down()
        engine = MonitoringEngine(docker_client, uptime_kuma_monitor=monitor)
        container, info = web_container()

        assert engine.uptime_kuma_monitor is monitor
        assert await engine._evaluate_container_health(container, info) == (
            True,
            "Uptime-Kuma monitor reports DOWN",
        )
        monitor.should_restart_from_uptime_kuma.assert_awaited_once_with("web")

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


class FakeClock:
    """A monotonic clock the test moves by hand"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def add_tcp_check(retries: int, interval_seconds: int = 30, container_id: str = "web") -> None:
    config_manager.add_custom_health_check(
        HealthCheckConfig(
            container_id=container_id,
            check_type="tcp",
            tcp_port=8080,
            retries=retries,
            interval_seconds=interval_seconds,
        )
    )


@pytest.mark.asyncio
class TestCustomCheckRetriesAndInterval:
    @pytest.fixture(autouse=True)
    def _health_mode(self, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "health"))

    @pytest.fixture
    def clock(self, engine) -> FakeClock:
        clock = FakeClock()
        engine._health_evaluator._clock = clock
        return clock

    async def cycle(self, engine, clock, container, info, *, healthy: bool, **kwargs):
        """One monitoring cycle (30 seconds, the default interval) with the check passing or not"""
        engine.docker_client.health_results[container.name] = healthy
        clock.now += 30
        return await engine._evaluate_container_health(container, info, **kwargs)

    async def test_fewer_than_retries_failures_do_not_restart(self, engine, clock):
        container, info = web_container()
        engine.docker_client.add_container(container, info)
        add_tcp_check(retries=3)

        for _ in range(2):
            result = await self.cycle(engine, clock, container, info, healthy=False)
            assert result == (False, "")

    async def test_retries_consecutive_failures_request_a_restart(self, engine, clock):
        container, info = web_container()
        engine.docker_client.add_container(container, info)
        add_tcp_check(retries=3)

        for _ in range(2):
            await self.cycle(engine, clock, container, info, healthy=False)
        result = await self.cycle(engine, clock, container, info, healthy=False)

        assert result == (True, "Custom health check failed (tcp)")

    async def test_a_pass_resets_the_count(self, engine, clock):
        container, info = web_container()
        engine.docker_client.add_container(container, info)
        add_tcp_check(retries=2)

        await self.cycle(engine, clock, container, info, healthy=False)
        await self.cycle(engine, clock, container, info, healthy=True)
        result = await self.cycle(engine, clock, container, info, healthy=False)

        assert result == (False, "")

    async def test_count_is_kept_per_container(self, engine, clock):
        labels = {"autoheal": "true", "monitoring.id": "shared"}
        first, first_info = make_container(name="a", container_id="a" * 64, labels=labels)
        second, second_info = make_container(name="b", container_id="b" * 64, labels=labels)
        engine.docker_client.add_container(first, first_info)
        engine.docker_client.add_container(second, second_info)
        add_tcp_check(retries=2, container_id="shared")

        engine.docker_client.health_results = {"a": False, "b": True}
        clock.now += 30
        await engine._evaluate_container_health(cast("Container", first), first_info)
        await engine._evaluate_container_health(cast("Container", second), second_info)
        clock.now += 30
        failing = await engine._evaluate_container_health(cast("Container", first), first_info)
        passing = await engine._evaluate_container_health(cast("Container", second), second_info)

        assert failing[0] is True
        assert passing == (False, "")

    async def test_a_restarted_container_starts_a_new_count(self, engine, clock):
        container, info = web_container()
        engine.docker_client.add_container(container, info)
        add_tcp_check(retries=2)

        await self.cycle(engine, clock, container, info, healthy=False)
        restarted = {**info, "started_at": "2024-02-02T00:00:00Z"}
        result = await self.cycle(engine, clock, container, restarted, healthy=False)

        assert result == (False, "")

    async def test_quarantine_check_fails_at_once_without_counting(self, engine, clock):
        container, info = web_container()
        engine.docker_client.add_container(container, info)
        add_tcp_check(retries=3)

        immediate = await self.cycle(
            engine, clock, container, info, healthy=False, apply_check_schedule=False
        )
        counted = await self.cycle(engine, clock, container, info, healthy=False)

        assert immediate == (True, "Custom health check failed (tcp)")
        assert counted == (False, "")

    async def test_check_runs_only_when_its_interval_has_passed(self, engine, clock):
        container, info = web_container()
        engine.docker_client.add_container(container, info)
        add_tcp_check(retries=1, interval_seconds=90)
        runs: list[bool] = []
        engine.docker_client.check_tcp_health = lambda *_args, **_kwargs: runs.append(True) or False

        verdicts = []
        for _ in range(4):
            clock.now += 30
            verdicts.append(await engine._evaluate_container_health(container, info))

        # Runs on the first cycle, then every third; the last verdict stands in between
        assert len(runs) == 2
        assert all(v[0] is True for v in verdicts)

    async def test_forgotten_container_starts_a_new_count(self, engine, clock):
        container, info = web_container()
        engine.docker_client.add_container(container, info)
        add_tcp_check(retries=2)

        await self.cycle(engine, clock, container, info, healthy=False)
        engine._health_evaluator.forget_container(info["full_id"])
        result = await self.cycle(engine, clock, container, info, healthy=False)

        assert result == (False, "")
