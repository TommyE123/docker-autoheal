"""
Unit tests for ``MonitoringEngine._evaluate_container_health``.

This is the decision point that answers "does this container need restarting?".
Tests cover healthy containers, unhealthy containers, exit-code handling,
custom health checks and health-check failure paths.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config.config_manager import HealthCheckConfig, config_manager
from app.monitor.health import CustomCheckLookup, find_custom_health_check
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

    @staticmethod
    def _skip_events():
        return [e for e in config_manager.get_events() if e.event_type == "health_check_skipped"]

    async def test_skip_is_reported_again_after_the_check_type_goes_away_and_returns(
        self, engine, docker_client
    ):
        """A skip of http, then a run of exec, then a skip of http again is a new skip."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = None
        self._add_check("http")
        await engine._evaluate_container_health(container, info)

        docker_client.health_results["web"] = True
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="exec", exec_command=["true"])
        )
        await engine._evaluate_container_health(container, info)

        docker_client.health_results["web"] = None
        self._add_check("http")
        await engine._evaluate_container_health(container, info)

        assert [e.message.split()[1] for e in self._skip_events()] == ["http", "http"]

    async def test_skip_is_reported_again_after_the_check_is_deleted(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.health_results["web"] = None
        self._add_check("http")
        await engine._evaluate_container_health(container, info)

        config_manager.remove_custom_health_check("web")
        await engine._evaluate_container_health(container, info)
        self._add_check("http")
        await engine._evaluate_container_health(container, info)

        assert len(self._skip_events()) == 2

    async def test_forget_absent_drops_only_containers_docker_no_longer_lists(
        self, engine, docker_client
    ):
        evaluator = engine._health_evaluator
        docker_client.health_results["web"] = None
        docker_client.health_results["db"] = None
        pairs = []
        for name, container_id in (("web", "a" * 64), ("db", "b" * 64)):
            container, info = make_container(name=name, container_id=container_id)
            docker_client.add_container(container, info)
            config_manager.add_custom_health_check(
                HealthCheckConfig(container_id=name, check_type="tcp", tcp_port=8080)
            )
            pairs.append((container, info))
            await engine._evaluate_container_health(container, info)
        assert set(evaluator._skipped_checks) == {"a" * 64, "b" * 64}

        evaluator.forget_absent({"a" * 64, None})

        assert evaluator._skipped_checks == {"a" * 64: "tcp"}
        # The kept container stays quiet; the forgotten one is reported when it returns.
        for container, info in pairs:
            await engine._evaluate_container_health(container, info)
        assert sorted(e.container_name for e in self._skip_events()) == ["db", "db", "web"]

    async def test_cycle_forgets_removed_containers_but_not_after_a_failed_listing(
        self, engine, docker_client
    ):
        web, web_info = make_container(name="web", container_id="a" * 64)
        other, other_info = make_container(name="api", container_id="c" * 64)
        docker_client.add_container(web, web_info)
        docker_client.add_container(other, other_info)
        docker_client.health_results["web"] = None
        self._add_check("tcp")
        await engine._check_containers()
        assert list(engine._health_evaluator._skipped_checks) == ["a" * 64]

        # An empty listing may be a failed Docker call, so it forgets nothing.
        docker_client.remove_container(web)
        docker_client.remove_container(other)
        await engine._check_containers()
        assert list(engine._health_evaluator._skipped_checks) == ["a" * 64]

        # A listing without the container says it is gone.
        docker_client.add_container(other, other_info)
        await engine._check_containers()
        assert engine._health_evaluator._skipped_checks == {}

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


_COMPOSE_WEB = {
    "autoheal": "true",
    "com.docker.compose.project": "stack",
    "com.docker.compose.service": "web",
}


def _compose_web(number: int = 1, container_id: str = "a" * 64):
    """A Compose container whose stable ID, name and Docker ID all differ."""
    return make_container(
        name=f"stack-web-{number}",
        container_id=container_id,
        labels={**_COMPOSE_WEB, "com.docker.compose.container-number": str(number)},
    )


def _tcp_check(key: str) -> HealthCheckConfig:
    return HealthCheckConfig(container_id=key, check_type="tcp", tcp_port=8080)


@pytest.mark.asyncio
class TestNameKeyedCustomChecks:
    """A check stored under the container name is used only when no other container owns it."""

    @pytest.fixture(autouse=True)
    def _health_mode(self, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "health"))

    async def test_name_keyed_check_applies_when_no_other_container_owns_the_name(
        self, engine, docker_client
    ):
        container, info = _compose_web()
        docker_client.add_container(container, info)
        docker_client.health_results["stack-web-1"] = False
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (tcp)"

    async def test_stable_id_match_does_not_list_docker(self, engine, docker_client, monkeypatch):
        container, info = _compose_web()
        docker_client.add_container(container, info)
        docker_client.health_results["stack-web-1"] = False
        listing = MagicMock(wraps=docker_client.list_containers)
        monkeypatch.setattr(docker_client, "list_containers", listing)
        config_manager.add_custom_health_check(_tcp_check("stack_web"))
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        needs_restart, _reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        listing.assert_not_called()

    @pytest.mark.parametrize("owner_status", ["running", "exited"])
    async def test_ambiguous_name_keyed_check_is_skipped_with_a_warning(
        self, engine, docker_client, caplog, owner_status
    ):
        """Another container (running or stopped) has the name as its stable ID."""
        container, info = _compose_web()
        owner, owner_info = make_container(
            name="other", container_id="b" * 64, stable_id="stack-web-1", status=owner_status
        )
        docker_client.add_container(container, info)
        docker_client.add_container(owner, owner_info)
        docker_client.health_results["stack-web-1"] = False
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        with caplog.at_level(logging.WARNING, logger="app.monitor.health"):
            needs_restart, _reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [
            "Custom health check stored under 'stack-web-1' was not applied to container "
            "stack-web-1: 'stack-web-1' is also the stable identifier of other. Set a unique "
            "monitoring.id label on that container so the key identifies one container"
        ]

    async def test_ambiguous_name_falls_through_to_an_exact_full_id_check(
        self, engine, docker_client, caplog
    ):
        container, info = _compose_web()
        owner, owner_info = make_container(
            name="other", container_id="b" * 64, stable_id="stack-web-1"
        )
        docker_client.add_container(container, info)
        docker_client.add_container(owner, owner_info)
        docker_client.health_results["stack-web-1"] = False
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="exec", exec_command=["true"])
        )

        with caplog.at_level(logging.WARNING, logger="app.monitor.health"):
            needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (exec)"
        assert "was not applied to container stack-web-1" in caplog.text

    async def test_owner_keeps_its_own_check(self, engine, docker_client):
        """The container whose stable ID is the key still gets the check."""
        container, info = _compose_web()
        owner, owner_info = make_container(
            name="other", container_id="b" * 64, stable_id="stack-web-1"
        )
        docker_client.add_container(container, info)
        docker_client.add_container(owner, owner_info)
        docker_client.health_results["other"] = False
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        needs_restart, _reason = await engine._evaluate_container_health(owner, owner_info)

        assert needs_restart is True

    async def test_failed_listing_skips_the_name_keyed_check_with_a_warning(
        self, engine, docker_client, caplog
    ):
        container, info = _compose_web()
        docker_client.add_container(container, info)
        docker_client.health_results["stack-web-1"] = False
        docker_client.list_containers_error = RuntimeError("daemon unreachable")
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        with caplog.at_level(logging.WARNING, logger="app.monitor.health"):
            needs_restart, _reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert (
            "Custom health check stored under 'stack-web-1' was not applied to container "
            "stack-web-1: Docker containers could not be listed to rule out another container "
            "with that stable identifier"
        ) in caplog.text

    async def test_uninspectable_container_in_the_listing_skips_the_name_keyed_check(
        self, engine, docker_client, caplog
    ):
        """An incomplete inventory cannot rule out a conflict either."""
        container, info = _compose_web()
        other, _other_info = make_container(name="other", container_id="b" * 64)
        docker_client.add_container(container, info)
        docker_client.add_container(other, {})  # the wrapper returns {} when inspection fails
        docker_client.health_results["stack-web-1"] = False
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        with caplog.at_level(logging.WARNING, logger="app.monitor.health"):
            needs_restart, _reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert "could not be listed" in caplog.text

    async def test_replicas_share_the_check_under_their_stable_id(
        self, engine, docker_client, caplog, monkeypatch
    ):
        """Two replicas of one service both use the check stored under the shared stable ID."""
        first, first_info = _compose_web(1, "a" * 64)
        second, second_info = _compose_web(2, "b" * 64)
        docker_client.add_container(first, first_info)
        docker_client.add_container(second, second_info)
        docker_client.health_results["stack-web-1"] = False
        docker_client.health_results["stack-web-2"] = False
        listing = MagicMock(wraps=docker_client.list_containers)
        monkeypatch.setattr(docker_client, "list_containers", listing)
        config_manager.add_custom_health_check(_tcp_check("stack_web"))

        with caplog.at_level(logging.WARNING, logger="app.monitor.health"):
            first_result = await engine._evaluate_container_health(first, first_info)
            second_result = await engine._evaluate_container_health(second, second_info)

        listing.assert_not_called()

        assert first_result == (True, "Custom health check failed (tcp)")
        assert second_result == (True, "Custom health check failed (tcp)")
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]


class TestFindCustomHealthCheck:
    """``find_custom_health_check`` called directly."""

    def test_unrelated_containers_do_not_block_a_name_keyed_check(self, docker_client):
        container, info = _compose_web()
        unrelated, unrelated_info = make_container(name="db", container_id="b" * 64)
        docker_client.add_container(container, info)
        docker_client.add_container(unrelated, unrelated_info)
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        lookup = find_custom_health_check(docker_client, info, "stack_web")

        assert lookup == CustomCheckLookup(check=_tcp_check("stack-web-1"), key="stack-web-1")

    def test_info_without_a_docker_id_and_no_check_finds_nothing(self, docker_client):
        assert find_custom_health_check(docker_client, {"name": "web"}, "web") == (
            CustomCheckLookup()
        )

    def test_listing_asks_the_wrapper_to_raise_instead_of_returning_empty(self):
        """The real wrapper returns [] on failure unless asked to raise, which would read
        as "no other container"; the lookup must ask for the error."""
        client = MagicMock()
        client.list_containers.return_value = []
        _container, info = _compose_web()
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        lookup = find_custom_health_check(client, info, "stack_web")

        client.list_containers.assert_called_once_with(all_containers=True, raise_errors=True)
        assert lookup == CustomCheckLookup(check=_tcp_check("stack-web-1"), key="stack-web-1")
