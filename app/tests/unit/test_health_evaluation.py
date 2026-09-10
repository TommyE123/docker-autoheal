"""
Unit tests for ``MonitoringEngine._evaluate_container_health``.

This is the decision point that answers "does this container need restarting?".
Tests cover healthy containers, unhealthy containers, exit-code handling,
custom health checks and health-check failure paths.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.config.config_manager import HealthCheckConfig, config_manager
from app.tests.unit.conftest import make_container


@pytest.mark.asyncio
class TestExitStatusEvaluation:
    """Exit-code driven restart decisions (``on-failure`` restart mode)."""

    async def test_healthy_running_container_needs_no_restart(self, engine):
        container, info = make_container(status="running")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == ""

    async def test_starting_container_is_skipped(self, engine):
        container, info = make_container(status="starting")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == "Container is starting"

    @pytest.mark.parametrize("status", ["exited", "stopped", "dead"])
    async def test_non_zero_exit_triggers_restart(self, engine, status):
        container, info = make_container(status=status, exit_code=137)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Container exited with code 137"

    async def test_clean_exit_respects_manual_stop(self, engine):
        container, info = make_container(status="exited", exit_code=0)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == "Manual stop (exit 0)"

    async def test_clean_exit_restarts_when_manual_stop_not_respected(self, engine, update_config):
        update_config(lambda c: setattr(c.restart, "respect_manual_stop", False))
        container, info = make_container(status="exited", exit_code=0)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Container stopped (exit 0)"

    async def test_exit_code_ignored_in_health_only_mode(self, engine, update_config):
        """In ``health`` mode a crashed container is not restarted on exit code alone."""
        update_config(lambda c: setattr(c.restart, "mode", "health"))
        container, info = make_container(status="exited", exit_code=1)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == ""


@pytest.mark.asyncio
class TestDockerNativeHealthEvaluation:
    """Docker health-check driven restart decisions."""

    @pytest.mark.parametrize("mode", ["health", "both"])
    async def test_unhealthy_container_triggers_restart(self, engine, update_config, mode):
        update_config(lambda c: setattr(c.restart, "mode", mode))
        container, info = make_container(health={"status": "unhealthy", "failing_streak": 3})

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Docker health check reports unhealthy"

    async def test_healthy_container_needs_no_restart(self, engine, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "both"))
        container, info = make_container(health={"status": "healthy", "failing_streak": 0})

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == ""

    async def test_unhealthy_ignored_in_on_failure_mode(self, engine):
        """``on-failure`` mode is the default and does not consult health status."""
        container, info = make_container(health={"status": "unhealthy"})

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == ""


@pytest.mark.asyncio
class TestCustomHealthChecks:
    """Custom (HTTP/TCP/exec/docker) health checks."""

    @pytest.fixture(autouse=True)
    def _health_mode(self, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "health"))

    async def test_failing_http_check_triggers_restart(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = False
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="http", http_endpoint="http://localhost/health")
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (http)"

    async def test_passing_tcp_check_needs_no_restart(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = True
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == ""

    async def test_custom_check_is_found_by_stable_id(self, engine, docker_client):
        """A compose container is looked up by ``project_service``, not by name."""
        container, info = make_container(
            name="stack-web-1",
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)
        docker_client.health_results["stack-web-1"] = False
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="stack_web", check_type="exec", exec_command=["true"])
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (exec)"

    async def test_custom_check_is_found_by_full_container_id(self, engine, docker_client):
        """Health checks registered against a raw container ID still resolve."""
        container, info = make_container(name="web", container_id="d" * 64)
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = False
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="d" * 64, check_type="http", http_endpoint="http://localhost/")
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True

    async def test_docker_check_type_uses_native_health(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.native_health["web"] = "unhealthy"
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="docker")
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (docker)"

    async def test_docker_check_type_assumes_healthy_without_native_check(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.native_health["web"] = None
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="docker")
        )

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False

    async def test_unknown_check_type_is_treated_as_healthy(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="carrier-pigeon")
        )

        assert await engine._perform_custom_health_check(
            container, config_manager.get_custom_health_check("web")
        ) is True

    async def test_health_check_error_is_reported_as_unhealthy(self, engine, docker_client):
        """A Docker API failure during a health check must not escape the engine."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_check_error = RuntimeError("docker API unavailable")
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="http", http_endpoint="http://localhost/")
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (http)"


@pytest.mark.asyncio
class TestUptimeKumaEvaluation:
    """Optional Uptime-Kuma integration."""

    async def test_monitor_down_triggers_restart(self, engine):
        engine.uptime_kuma_monitor = MagicMock()
        engine.uptime_kuma_monitor.should_restart_from_uptime_kuma = AsyncMock(return_value=True)
        container, info = make_container(name="web")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Uptime-Kuma monitor reports DOWN"
        engine.uptime_kuma_monitor.should_restart_from_uptime_kuma.assert_awaited_once_with("web")

    async def test_monitor_up_needs_no_restart(self, engine):
        engine.uptime_kuma_monitor = MagicMock()
        engine.uptime_kuma_monitor.should_restart_from_uptime_kuma = AsyncMock(return_value=False)
        container, info = make_container(name="web")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == ""

    async def test_integration_is_skipped_when_not_configured(self, engine):
        container, info = make_container(name="web")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert not hasattr(engine, "uptime_kuma_monitor")
