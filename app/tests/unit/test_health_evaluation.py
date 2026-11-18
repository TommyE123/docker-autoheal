"""
Unit tests for ``MonitoringEngine._evaluate_container_health``.

This is the decision point that answers "does this container need restarting?".
Tests cover healthy containers, unhealthy containers, exit-code handling,
custom health checks and health-check failure paths.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

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

    @pytest.mark.parametrize("status", ["exited", "stopped", "dead"])
    @pytest.mark.parametrize("mode", ["health", "both"])
    async def test_cleanly_stopped_container_not_restarted_by_failing_custom_check(
        self, engine, update_config, mode, status
    ):
        """A deliberately stopped container is not restarted because its check fails."""
        update_config(lambda c: setattr(c.restart, "mode", mode))
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=80)
        )
        engine._health_evaluator.perform_custom_health_check = AsyncMock(return_value=False)
        container, info = make_container(name="web", status=status, exit_code=0)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == "Manual stop (exit 0)"
        engine._health_evaluator.perform_custom_health_check.assert_not_called()

    async def test_clean_exit_in_health_mode_restarts_when_manual_stop_not_respected(
        self, engine, update_config
    ):
        update_config(
            lambda c: (
                setattr(c.restart, "mode", "health"),
                setattr(c.restart, "respect_manual_stop", False),
            )
        )
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=80)
        )
        engine._health_evaluator.perform_custom_health_check = AsyncMock(return_value=False)
        container, info = make_container(name="web", status="exited", exit_code=0)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (tcp)"


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
            HealthCheckConfig(
                container_id="web",
                check_type="http",
                http_endpoint="http://localhost/health",
            )
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
            HealthCheckConfig(
                container_id="d" * 64,
                check_type="http",
                http_endpoint="http://localhost/",
            )
        )

        needs_restart, _reason = await engine._evaluate_container_health(container, info)

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

    async def test_docker_check_type_assumes_healthy_without_native_check(
        self, engine, docker_client
    ):
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
            HealthCheckConfig.model_construct(container_id="web", check_type="carrier-pigeon")
        )

        assert (
            await engine._health_evaluator.perform_custom_health_check(
                container, config_manager.get_custom_health_check("web")
            )
            is True
        )

    async def test_health_check_error_is_reported_as_unhealthy(self, engine, docker_client):
        """A Docker API failure during a health check must not escape the engine."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_check_error = RuntimeError("docker API unavailable")
        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id="web", check_type="http", http_endpoint="http://localhost/"
            )
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (http)"

    @pytest.mark.parametrize(
        "case",
        [
            ("http", {}, "missing http_endpoint or http_expected_status"),
            (
                "http",
                {"http_expected_status": 200},
                "missing http_endpoint or http_expected_status",
            ),
            (
                "http",
                {"http_endpoint": "http://localhost/", "http_expected_status": None},
                "missing http_endpoint or http_expected_status",
            ),
            ("tcp", {}, "missing tcp_port"),
            ("exec", {}, "missing exec_command"),
        ],
    )
    async def test_missing_required_field_is_reported_as_unhealthy(
        self, engine, docker_client, caplog, case
    ):
        """A check without the field its type needs fails closed, never reaching Docker."""
        check_type, fields, message = case
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = True
        config_manager.add_custom_health_check(
            HealthCheckConfig.model_construct(container_id="web", check_type=check_type, **fields)
        )

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == f"Custom health check failed ({check_type})"
        assert f"Error performing health check: {message}" in caplog.text

    @pytest.mark.parametrize(
        "case",
        [
            (
                "check_http_health",
                {
                    "http_endpoint": "http://localhost/health",
                    "http_expected_status": 204,
                    "timeout_seconds": 7,
                },
                ("http://localhost/health", 204, 7),
            ),
            ("check_tcp_health", {"tcp_port": 8080, "timeout_seconds": 7}, (8080, 7)),
            (
                "check_exec_health",
                {"exec_command": ["true", "-x"], "timeout_seconds": 7},
                (["true", "-x"], 7),
            ),
        ],
    )
    async def test_valid_check_passes_configured_values_to_docker_client(
        self, engine, docker_client, monkeypatch, case
    ):
        """Narrowing must forward the configured values unchanged to the check."""
        method, fields, expected_args = case
        container, _ = make_container(name="web")
        check = MagicMock(return_value=True)
        monkeypatch.setattr(docker_client, method, check)
        check_type = method.removeprefix("check_").removesuffix("_health")
        health_check = HealthCheckConfig(container_id="web", check_type=check_type, **fields)

        healthy = await engine._health_evaluator.perform_custom_health_check(
            container, health_check
        )

        assert healthy is True
        check.assert_called_once_with(container, *expected_args)


@pytest.mark.asyncio
class TestSkippedCustomHealthChecks:
    """A check that cannot run (host networking) is skipped, never counted as a failure."""

    @pytest.fixture(autouse=True)
    def _health_mode(self, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "both"))

    @staticmethod
    def _add_check(check_type):
        if check_type == "http":
            check = HealthCheckConfig(
                container_id="web", check_type="http", http_endpoint="http://localhost/health"
            )
        else:
            check = HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        config_manager.add_custom_health_check(check)

    @pytest.mark.parametrize("check_type", ["http", "tcp"])
    async def test_unrunnable_check_does_not_trigger_restart(
        self, engine, docker_client, check_type
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = None
        self._add_check(check_type)

        assert await engine._evaluate_container_health(container, info) == (False, "")

    async def test_docker_unhealthy_still_restarts_when_check_is_skipped(
        self, engine, docker_client
    ):
        container, info = make_container(name="web", health={"status": "unhealthy"})
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = None
        self._add_check("http")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Docker health check reports unhealthy"

    async def test_skip_is_logged_and_recorded_once_per_container(
        self, engine, docker_client, caplog
    ):
        container, info = make_container(name="web", container_id="c" * 64)
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = None
        self._add_check("http")

        for _ in range(3):
            await engine._evaluate_container_health(container, info)

        message = (
            "Custom http health check skipped: the container uses host networking, so Autoheal "
            "cannot reach it. Use an exec or Docker health check instead"
        )
        events = [e for e in config_manager.get_events() if e.event_type == "health_check_skipped"]
        assert len(events) == 1
        event = events[0]
        assert event.container_name == "web"
        assert event.container_id == "c" * 64
        assert event.restart_count == 0
        assert event.status == "skipped"
        assert event.message == message
        skip_logs = [r for r in caplog.records if "health check skipped" in r.getMessage()]
        assert [(r.levelname, r.getMessage()) for r in skip_logs] == [
            ("WARNING", f"Container web: {message}")
        ]

    async def test_skip_is_reported_again_when_the_check_type_changes(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = None

        for check_type in ("http", "tcp"):
            self._add_check(check_type)
            await engine._evaluate_container_health(container, info)

        events = [e for e in config_manager.get_events() if e.event_type == "health_check_skipped"]
        assert [e.message.split()[1] for e in events] == ["http", "tcp"]

    async def test_skips_of_different_containers_are_reported_separately(
        self, engine, docker_client
    ):
        docker_client.health_results["web"] = None
        docker_client.health_results["db"] = None
        for name, container_id in (("web", "a" * 64), ("db", "b" * 64)):
            container, info = make_container(name=name, container_id=container_id)
            docker_client.add_container(container, info)
            config_manager.add_custom_health_check(
                HealthCheckConfig(container_id=name, check_type="tcp", tcp_port=8080)
            )
            await engine._evaluate_container_health(container, info)

        events = [e for e in config_manager.get_events() if e.event_type == "health_check_skipped"]
        assert sorted(e.container_name for e in events) == ["db", "web"]

    @pytest.mark.parametrize("ran", [True, False])
    async def test_skip_is_reported_again_after_the_check_runs(self, engine, docker_client, ran):
        """The check running again resets the skip record, whether it passes or fails."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        self._add_check("tcp")

        for result in (None, ran, None):
            docker_client.health_results["web"] = result
            await engine._evaluate_container_health(container, info)

        events = [e for e in config_manager.get_events() if e.event_type == "health_check_skipped"]
        assert len(events) == 2

    async def test_failing_check_is_still_a_failure(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = False
        self._add_check("tcp")

        assert await engine._evaluate_container_health(container, info) == (
            True,
            "Custom health check failed (tcp)",
        )

    async def test_skipped_check_never_restarts_backs_off_or_quarantines(
        self, engine, docker_client
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = None
        self._add_check("http")

        for _ in range(10):
            await engine._check_containers()

        assert docker_client.restart_calls == []
        assert engine._recovery.next_allowed_restart == {}
        assert config_manager.is_quarantined("web") is False
        assert not [
            e for e in config_manager.get_events() if e.event_type != "health_check_skipped"
        ]


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

    async def test_down_monitor_does_not_restart_cleanly_stopped_container_in_health_mode(
        self, engine, update_config
    ):
        update_config(lambda c: setattr(c.restart, "mode", "health"))
        engine.uptime_kuma_monitor = MagicMock()
        engine.uptime_kuma_monitor.should_restart_from_uptime_kuma = AsyncMock(return_value=True)
        container, info = make_container(name="web", status="exited", exit_code=0)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == "Manual stop (exit 0)"
        engine.uptime_kuma_monitor.should_restart_from_uptime_kuma.assert_not_called()

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
        assert engine.uptime_kuma_monitor is None


@pytest.mark.asyncio
async def test_custom_health_check_is_found_by_id_when_info_has_no_name(engine, update_config):
    update_config(lambda c: setattr(c.restart, "mode", "health"))
    container, info = make_container(name="web")
    del info["name"]
    config_manager.add_custom_health_check(
        HealthCheckConfig(container_id=info["full_id"], check_type="docker")
    )
    engine._health_evaluator.perform_custom_health_check = AsyncMock(return_value=False)

    needs_restart, _reason = await engine._evaluate_container_health(container, info)

    assert needs_restart is True
