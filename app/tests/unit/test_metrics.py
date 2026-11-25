"""
Unit tests for the Prometheus metrics in ``app/monitor/metrics.py``.

The metrics live in the default registry, which every test shares, so each test uses its
own container names and asserts the change in a sample rather than its absolute value.
Samples are read back through ``REGISTRY`` by their exposed names, so a renamed metric or
label fails here.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

from app.api.errors import get_docker_client
from app.api.routes.containers import restart_container_manual
from app.config.config_manager import HealthCheckConfig, config_manager
from app.monitor.metrics import containers_monitored
from app.tests.unit.conftest import after_backoff, make_container

RESTARTS = "autoheal_container_restarts_total"
CHECKS = "autoheal_health_checks_total"
FAILED = "autoheal_health_checks_failed_total"
MONITORED = "autoheal_containers_monitored"
QUARANTINED = "autoheal_containers_quarantined"


def sample(name: str, container_name: str | None = None) -> float:
    """A sample's current value, 0 for a labelled child not yet created"""
    labels = None if container_name is None else {"container_name": container_name}
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else value


class Delta:
    """Snapshot the counters for one container, to compare after the action"""

    def __init__(self, container_name: str) -> None:
        self.container_name = container_name
        self.restarts = sample(RESTARTS, container_name)
        self.checks = sample(CHECKS)
        self.failed = sample(FAILED, container_name)

    def restarted(self) -> float:
        return sample(RESTARTS, self.container_name) - self.restarts

    def checked(self) -> float:
        return sample(CHECKS) - self.checks

    def check_failures(self) -> float:
        return sample(FAILED, self.container_name) - self.failed


def use_mode(update_config, mode: str) -> None:
    update_config(lambda c: setattr(c.restart, "mode", mode))


def add_check(container_name: str, check_type: str = "tcp") -> None:
    if check_type == "tcp":
        check = HealthCheckConfig(container_id=container_name, check_type="tcp", tcp_port=80)
    else:
        check = HealthCheckConfig(container_id=container_name, check_type="docker")
    config_manager.add_custom_health_check(check)


def family(name: str):
    """The registered metric family with this name (counters drop their ``_total``)"""
    return next(metric for metric in REGISTRY.collect() if metric.name == name)


@pytest.mark.parametrize(
    ("name", "metric_type", "documentation"),
    [
        ("autoheal_container_restarts", "counter", "Total container restarts"),
        ("autoheal_health_checks", "counter", "Total health checks performed"),
        ("autoheal_health_checks_failed", "counter", "Failed health checks"),
        (MONITORED, "gauge", "Number of containers being monitored"),
        (QUARANTINED, "gauge", "Number of quarantined containers"),
    ],
)
def test_metric_is_registered_with_its_type_and_help(name, metric_type, documentation):
    metric = family(name)

    assert metric.type == metric_type
    assert metric.documentation == documentation


@pytest.mark.asyncio
class TestRestartCounter:
    """Only successful Autoheal recovery restarts are counted, by container name"""

    async def test_successful_restart_is_counted_once_for_the_container(
        self, engine, docker_client
    ):
        container, info = make_container(name="metrics-restart-ok")
        other = Delta("metrics-restart-other")
        docker_client.add_container(container, info)
        delta = Delta("metrics-restart-ok")

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert docker_client.restart_calls == ["metrics-restart-ok"]
        assert delta.restarted() == 1
        assert other.restarted() == 0

    async def test_compose_container_is_labelled_by_name_not_recovery_id(
        self, engine, docker_client
    ):
        container, info = make_container(
            name="metrics-stack-web-1",
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "metrics-stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)
        delta = Delta("metrics-stack-web-1")
        by_recovery_id = Delta(info["recovery_id"])

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert delta.restarted() == 1
        assert by_recovery_id.restarted() == 0

    async def test_failed_restart_is_not_counted(self, engine, docker_client):
        container, info = make_container(name="metrics-restart-fail")
        docker_client.add_container(container, info)
        docker_client.restart_results["metrics-restart-fail"] = False
        delta = Delta("metrics-restart-fail")

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert docker_client.restart_calls == ["metrics-restart-fail"]
        assert delta.restarted() == 0

    async def test_restart_in_cooldown_is_not_counted(self, engine, docker_client):
        container, info = make_container(name="metrics-restart-cooldown")
        docker_client.add_container(container, info)
        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")
        delta = Delta("metrics-restart-cooldown")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == ["metrics-restart-cooldown"]
        assert delta.restarted() == 0

    async def test_restart_waiting_out_its_backoff_is_not_counted(self, engine, docker_client):
        container, info = make_container(name="metrics-restart-backoff")
        docker_client.add_container(container, info)
        delta = Delta("metrics-restart-backoff")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert "metrics-restart-backoff" in engine._recovery.next_allowed_restart
        assert docker_client.restart_calls == []
        assert delta.restarted() == 0

    async def test_quarantine_is_not_counted(self, engine, docker_client):
        container, info = make_container(name="metrics-restart-quarantine")
        docker_client.add_container(container, info)
        for _ in range(3):  # default max_restarts
            config_manager.record_restart("metrics-restart-quarantine")
        delta = Delta("metrics-restart-quarantine")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("metrics-restart-quarantine") is True
        assert delta.restarted() == 0

    async def test_manual_api_restart_is_not_counted(self, monkeypatch, engine, docker_client):
        monkeypatch.setattr("app.api.state.docker_client", docker_client)
        monkeypatch.setattr("app.api.state.monitoring_engine", engine)
        container, info = make_container(name="metrics-restart-manual", container_id="m" * 64)
        docker_client.add_container(container, info)
        delta = Delta("metrics-restart-manual")

        result = await restart_container_manual(get_docker_client(), "m" * 64)

        assert result["status"] == "success"
        assert docker_client.restart_calls == ["metrics-restart-manual"]
        assert delta.restarted() == 0


@pytest.mark.asyncio
class TestHealthCheckCounters:
    """Each custom or Docker native check that produces a result is counted once"""

    async def test_passing_custom_check_is_counted(self, engine, update_config):
        use_mode(update_config, "health")
        add_check("metrics-hc-custom-ok")
        container, info = make_container(name="metrics-hc-custom-ok")
        delta = Delta("metrics-hc-custom-ok")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert delta.checked() == 1
        assert delta.check_failures() == 0

    async def test_failing_custom_check_is_counted_as_failed(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "both")
        add_check("metrics-hc-custom-fail")
        docker_client.health_results["metrics-hc-custom-fail"] = False
        # The native status is not read once the custom check fails
        container, info = make_container(
            name="metrics-hc-custom-fail", health={"status": "unhealthy"}
        )
        delta = Delta("metrics-hc-custom-fail")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (tcp)"
        assert delta.checked() == 1
        assert delta.check_failures() == 1

    async def test_custom_check_that_raises_is_counted_as_failed(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-custom-error")
        docker_client.health_check_error = RuntimeError("boom")
        container, info = make_container(name="metrics-hc-custom-error")
        delta = Delta("metrics-hc-custom-error")

        await engine._evaluate_container_health(container, info)

        assert delta.checked() == 1
        assert delta.check_failures() == 1

    async def test_passing_custom_and_native_checks_are_each_counted(self, engine, update_config):
        use_mode(update_config, "health")
        add_check("metrics-hc-both-ok")
        container, info = make_container(name="metrics-hc-both-ok", health={"status": "healthy"})
        delta = Delta("metrics-hc-both-ok")

        await engine._evaluate_container_health(container, info)

        assert delta.checked() == 2
        assert delta.check_failures() == 0

    async def test_passing_custom_check_then_unhealthy_native_counts_one_failure(
        self, engine, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-native-after")
        container, info = make_container(
            name="metrics-hc-native-after", health={"status": "unhealthy"}
        )
        delta = Delta("metrics-hc-native-after")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Docker health check reports unhealthy"
        assert delta.checked() == 2
        assert delta.check_failures() == 1

    async def test_docker_type_custom_check_counts_the_native_status_once(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-docker-ok", "docker")
        docker_client.native_health["metrics-hc-docker-ok"] = "healthy"
        container, info = make_container(name="metrics-hc-docker-ok", health={"status": "healthy"})
        delta = Delta("metrics-hc-docker-ok")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert delta.checked() == 1
        assert delta.check_failures() == 0

    async def test_docker_type_custom_check_without_a_healthcheck_is_not_counted(
        self, engine, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-docker-none", "docker")
        container, info = make_container(name="metrics-hc-docker-none", health=None)
        delta = Delta("metrics-hc-docker-none")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_docker_type_custom_check_counts_an_unhealthy_status_once(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-docker-bad", "docker")
        docker_client.native_health["metrics-hc-docker-bad"] = "unhealthy"
        container, info = make_container(
            name="metrics-hc-docker-bad", health={"status": "unhealthy"}
        )
        delta = Delta("metrics-hc-docker-bad")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (docker)"
        assert delta.checked() == 1
        assert delta.check_failures() == 1

    async def test_docker_type_custom_check_on_a_starting_container_is_not_counted(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-docker-starting", "docker")
        docker_client.native_health["metrics-hc-docker-starting"] = "starting"
        container, info = make_container(
            name="metrics-hc-docker-starting", health={"status": "starting"}
        )
        delta = Delta("metrics-hc-docker-starting")

        await engine._evaluate_container_health(container, info)

        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_custom_check_that_could_not_run_is_not_counted(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-skipped")
        docker_client.health_results["metrics-hc-skipped"] = None  # host networking
        container, info = make_container(name="metrics-hc-skipped")
        delta = Delta("metrics-hc-skipped")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_native_check_still_counted_when_custom_check_could_not_run(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-skipped-native")
        docker_client.health_results["metrics-hc-skipped-native"] = None
        container, info = make_container(
            name="metrics-hc-skipped-native", health={"status": "healthy"}
        )
        delta = Delta("metrics-hc-skipped-native")

        await engine._evaluate_container_health(container, info)

        assert delta.checked() == 1
        assert delta.check_failures() == 0

    async def test_healthy_native_status_is_counted(self, engine, update_config):
        use_mode(update_config, "health")
        container, info = make_container(name="metrics-hc-native-ok", health={"status": "healthy"})
        delta = Delta("metrics-hc-native-ok")

        await engine._evaluate_container_health(container, info)

        assert delta.checked() == 1
        assert delta.check_failures() == 0

    async def test_unhealthy_native_status_is_counted_as_failed(self, engine, update_config):
        use_mode(update_config, "health")
        container, info = make_container(
            name="metrics-hc-native-bad", health={"status": "unhealthy"}
        )
        other = Delta("metrics-hc-native-other")
        delta = Delta("metrics-hc-native-bad")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert delta.checked() == 1
        assert delta.check_failures() == 1
        assert other.check_failures() == 0

    @pytest.mark.parametrize("health", [None, {"status": "starting"}, {"status": None}])
    async def test_native_status_without_a_result_is_not_counted(
        self, engine, update_config, health
    ):
        use_mode(update_config, "health")
        container, info = make_container(name="metrics-hc-native-none", health=health)
        delta = Delta("metrics-hc-native-none")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_starting_container_is_not_counted(self, engine, update_config):
        use_mode(update_config, "both")
        add_check("metrics-hc-starting")
        container, info = make_container(
            name="metrics-hc-starting", status="starting", health={"status": "unhealthy"}
        )
        delta = Delta("metrics-hc-starting")

        await engine._evaluate_container_health(container, info)

        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_exit_code_restart_is_not_counted(self, engine, update_config):
        use_mode(update_config, "both")
        add_check("metrics-hc-exited")
        container, info = make_container(
            name="metrics-hc-exited", status="exited", exit_code=1, health={"status": "unhealthy"}
        )
        delta = Delta("metrics-hc-exited")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Container exited with code 1"
        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_checks_are_not_run_or_counted_in_on_failure_mode(self, engine):
        add_check("metrics-hc-on-failure")
        container, info = make_container(
            name="metrics-hc-on-failure", health={"status": "unhealthy"}
        )
        delta = Delta("metrics-hc-on-failure")

        needs_restart, _ = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_uptime_kuma_trigger_is_not_counted(self, engine):
        engine.uptime_kuma_monitor = MagicMock()
        engine.uptime_kuma_monitor.should_restart_from_uptime_kuma = AsyncMock(return_value=True)
        container, info = make_container(name="metrics-hc-kuma")
        delta = Delta("metrics-hc-kuma")

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Uptime-Kuma monitor reports DOWN"
        assert delta.checked() == 0
        assert delta.check_failures() == 0

    async def test_failure_is_labelled_by_id_when_the_name_is_unknown(self, engine, update_config):
        use_mode(update_config, "health")
        container, info = make_container(
            name="metrics-hc-unnamed", container_id="u" * 64, health={"status": "unhealthy"}
        )
        del info["name"]
        delta = Delta("u" * 64)

        await engine._evaluate_container_health(container, info)

        assert delta.checked() == 1
        assert delta.check_failures() == 1

    async def test_a_monitoring_cycle_counts_each_check_once(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        add_check("metrics-hc-cycle")
        docker_client.health_results["metrics-hc-cycle"] = False
        container, info = make_container(name="metrics-hc-cycle", health={"status": "unhealthy"})
        docker_client.add_container(container, info)
        delta = Delta("metrics-hc-cycle")

        await engine._check_containers()

        assert delta.checked() == 1
        assert delta.check_failures() == 1

    async def test_quarantined_container_check_is_counted_once(
        self, engine, docker_client, update_config
    ):
        use_mode(update_config, "health")
        container, info = make_container(
            name="metrics-hc-quarantined", health={"status": "healthy"}
        )
        docker_client.add_container(container, info)
        config_manager.quarantine_container("metrics-hc-quarantined")
        delta = Delta("metrics-hc-quarantined")

        await engine._check_containers()

        assert config_manager.is_quarantined("metrics-hc-quarantined") is True
        assert delta.checked() == 1
        assert delta.check_failures() == 0


def test_quarantined_gauge_reads_the_quarantine_list_at_scrape_time():
    assert sample(QUARANTINED) == 0

    config_manager.quarantine_container("metrics-q-one")
    config_manager.quarantine_container("metrics-q-two")
    assert sample(QUARANTINED) == 2

    config_manager.unquarantine_container("metrics-q-one")
    assert sample(QUARANTINED) == 1


@pytest.mark.asyncio
class TestMonitoredGauge:
    """Set from each monitoring cycle; kept when a cycle says nothing about the count"""

    @pytest.fixture(autouse=True)
    def sentinel(self):
        """Start from a value no cycle in these tests produces"""
        containers_monitored.set(7)

    @staticmethod
    def add(docker_client, name: str, container_id: str, labels: dict | None = None) -> None:
        container, info = make_container(name=name, container_id=container_id, labels=labels)
        docker_client.add_container(container, info)

    async def test_counts_the_containers_selected_for_monitoring(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-a", "1" * 64)
        self.add(docker_client, "metrics-mon-b", "2" * 64)
        self.add(docker_client, "metrics-mon-unlabelled", "3" * 64, labels={})

        await engine._check_containers()

        assert sample(MONITORED) == 2

    async def test_each_cycle_replaces_the_count(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-c", "1" * 64)
        self.add(docker_client, "metrics-mon-d", "2" * 64)
        await engine._check_containers()
        docker_client.remove_container(docker_client.get_container("2" * 64))

        await engine._check_containers()

        assert sample(MONITORED) == 1

    async def test_no_monitored_containers_sets_zero(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-none", "1" * 64, labels={})

        await engine._check_containers()

        assert sample(MONITORED) == 0

    async def test_quarantined_containers_are_counted(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-quarantined", "1" * 64)
        config_manager.quarantine_container("metrics-mon-quarantined")

        await engine._check_containers()

        assert sample(MONITORED) == 1

    async def test_a_container_whose_check_fails_is_still_counted(
        self, engine, docker_client, monkeypatch
    ):
        self.add(docker_client, "metrics-mon-error", "1" * 64)
        monkeypatch.setattr(
            engine, "_evaluate_container_health", AsyncMock(side_effect=RuntimeError("boom"))
        )

        await engine._check_containers()

        assert sample(MONITORED) == 1

    async def test_maintenance_mode_keeps_the_last_count(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-maint", "1" * 64)
        config_manager.enable_maintenance_mode()

        await engine._check_containers()

        assert sample(MONITORED) == 7

        config_manager.disable_maintenance_mode()
        await engine._check_containers()

        assert sample(MONITORED) == 1

    async def test_empty_listing_keeps_the_last_count(self, engine, docker_client):
        await engine._check_containers()

        assert sample(MONITORED) == 7

    async def test_failed_listing_keeps_the_last_count(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-list-error", "1" * 64)
        docker_client.list_containers_error = RuntimeError("docker down")

        await engine._check_containers()

        assert sample(MONITORED) == 7

    async def test_unreachable_docker_keeps_the_last_count(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-unreachable", "1" * 64)
        docker_client.connected = False
        docker_client.reconnect_succeeds = False

        await engine._check_containers()

        assert sample(MONITORED) == 7

    async def test_get_status_is_unchanged(self, engine, docker_client):
        self.add(docker_client, "metrics-mon-status", "1" * 64)

        await engine._check_containers()

        assert sample(MONITORED) == 1
        assert engine.get_status()["monitored_containers"] == 0
