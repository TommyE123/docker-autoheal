"""
Regression tests for #471: replicas of a scaled Compose service recover independently.

Configuration (selection, custom health checks, Uptime Kuma mappings) stays keyed by
the per-service stable identifier, ``project_service``. Restart counts, cooldown,
backoff and quarantine are keyed by the per-replica recovery identifier. Replica 1
keeps the old key, so state persisted before #471 still applies to it.
"""

import pytest

from app.api.routes.containers import (
    get_container_details,
    list_containers,
    unquarantine_container,
)
from app.config.config_manager import config_manager
from app.docker_client.docker_client_wrapper import recovery_identifier
from app.tests.unit.conftest import make_container

COMPOSE = {
    "com.docker.compose.project": "myapp",
    "com.docker.compose.service": "web",
}


def replica(number, status="running", exit_code=0, container_id=None, extra_labels=None):
    """A replica of ``myapp``/``web`` with the given Compose container number."""
    labels = {"autoheal": "true", **COMPOSE, "com.docker.compose.container-number": str(number)}
    labels.update(extra_labels or {})
    return make_container(
        name=f"myapp-web-{number}",
        container_id=container_id or str(number) * 64,
        status=status,
        exit_code=exit_code,
        labels=labels,
    )


@pytest.fixture
def no_cooldown(update_config):
    update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))


@pytest.fixture
def two_replicas(docker_client):
    """Replica 1 has exited with an error; replica 2 is running and healthy."""
    a, a_info = replica(1, status="exited", exit_code=1)
    b, b_info = replica(2)
    docker_client.add_container(a, a_info)
    docker_client.add_container(b, b_info)
    return (a, a_info), (b, b_info)


async def quarantine(engine, container, info):
    """Restart until the default ``max_restarts`` (3) quarantines the container."""
    for _ in range(4):
        await engine._handle_container_restart(container, info, "unhealthy")


class TestRecoveryIdentifier:
    @pytest.mark.parametrize(
        ("labels", "expected"),
        [
            ({**COMPOSE, "com.docker.compose.container-number": "2"}, "myapp_web#2"),
            ({**COMPOSE, "com.docker.compose.container-number": "10"}, "myapp_web#10"),
            # Replica 1 keeps the pre-#471 key, so persisted state needs no migration.
            ({**COMPOSE, "com.docker.compose.container-number": "1"}, "myapp_web"),
            ({**COMPOSE}, "myapp_web"),
            ({**COMPOSE, "com.docker.compose.container-number": "0"}, "myapp_web"),
            ({**COMPOSE, "com.docker.compose.container-number": "-3"}, "myapp_web"),
            ({**COMPOSE, "com.docker.compose.container-number": ""}, "myapp_web"),
            ({**COMPOSE, "com.docker.compose.container-number": "two"}, "myapp_web"),
        ],
    )
    def test_compose_replica_numbers(self, labels, expected):
        assert recovery_identifier("myapp_web", labels) == expected

    def test_explicit_monitoring_id_is_never_suffixed(self):
        labels = {**COMPOSE, "monitoring.id": "shared", "com.docker.compose.container-number": "3"}

        assert recovery_identifier("shared", labels) == "monitoring.id:shared"

    def test_empty_monitoring_id_label_is_still_never_suffixed(self):
        labels = {**COMPOSE, "monitoring.id": "", "com.docker.compose.container-number": "3"}

        assert recovery_identifier("", labels) == "monitoring.id:"

    @pytest.mark.parametrize(
        "labels",
        [
            {"com.docker.compose.container-number": "2"},
            {"com.docker.compose.project": "myapp", "com.docker.compose.container-number": "2"},
            {"com.docker.compose.service": "web", "com.docker.compose.container-number": "2"},
            {
                "com.docker.compose.project": "",
                "com.docker.compose.service": "web",
                "com.docker.compose.container-number": "2",
            },
        ],
    )
    def test_non_compose_containers_keep_their_stable_id(self, labels):
        assert recovery_identifier("web-2", labels) == "web-2"

    def test_replica_key_cannot_collide_with_a_service_named_like_it(self):
        """Replica 2 of ``web`` must not share state with replica 1 of a service ``web-2``."""
        web_replica_2 = {**COMPOSE, "com.docker.compose.container-number": "2"}
        web_2_service = {
            **COMPOSE,
            "com.docker.compose.service": "web-2",
            "com.docker.compose.container-number": "1",
        }

        assert recovery_identifier("myapp_web", web_replica_2) != recovery_identifier(
            "myapp_web-2", web_2_service
        )

    def test_explicit_id_cannot_collide_with_a_generated_replica_key(self):
        """A ``monitoring.id`` copied from replica 2's key must not share its state."""
        web_replica_2 = {**COMPOSE, "com.docker.compose.container-number": "2"}
        other = {"monitoring.id": "myapp_web#2"}

        generated = recovery_identifier("myapp_web", web_replica_2)
        explicit = recovery_identifier("myapp_web#2", other)

        assert generated == "myapp_web#2"
        assert explicit == "monitoring.id:myapp_web#2"

    def test_explicit_id_cannot_collide_with_a_generated_service_key(self):
        """A ``monitoring.id`` equal to a service's generated key must not share its state."""
        assert recovery_identifier("myapp_web", COMPOSE) == "myapp_web"
        assert recovery_identifier("myapp_web", {"monitoring.id": "myapp_web"}) == (
            "monitoring.id:myapp_web"
        )

    def test_engine_uses_per_service_stable_id_and_per_replica_recovery_id(self, engine):
        _, info = replica(2)

        assert engine.get_stable_identifier(info) == "myapp_web"
        assert engine.get_recovery_identifier(info) == "myapp_web#2"

    def test_engine_recovery_id_without_labels_is_the_name(self, engine):
        assert engine.get_recovery_identifier({"name": "web"}) == "web"


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_cooldown")
class TestReplicasRecoverIndependently:
    async def test_restarting_one_replica_does_not_count_against_another(
        self, engine, two_replicas
    ):
        (a, a_info), (_b, b_info) = two_replicas

        await engine._handle_container_restart(a, a_info, "unhealthy")
        await engine._handle_container_restart(a, a_info, "unhealthy")

        assert config_manager.get_total_restart_count("myapp_web") == 2
        assert config_manager.get_total_restart_count(engine.get_recovery_identifier(b_info)) == 0

    async def test_cooldown_is_per_replica(
        self, engine, docker_client, two_replicas, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 60))
        (a, a_info), (b, b_info) = two_replicas

        await engine._handle_container_restart(a, a_info, "unhealthy")
        await engine._handle_container_restart(b, b_info, "unhealthy")

        assert docker_client.restart_calls == ["myapp-web-1", "myapp-web-2"]

    async def test_backoff_is_per_replica(
        self, engine, docker_client, two_replicas, recorded_sleeps
    ):
        (a, a_info), (b, b_info) = two_replicas
        docker_client.restart_results["myapp-web-1"] = False
        await engine._handle_container_restart(a, a_info, "unhealthy")
        await engine._handle_container_restart(a, a_info, "unhealthy")
        recorded_sleeps.clear()

        await engine._handle_container_restart(b, b_info, "unhealthy")

        assert recorded_sleeps == [config_manager.get_config().restart.backoff.initial_seconds]

    async def test_quarantining_one_replica_does_not_stop_another_being_restarted(
        self, engine, docker_client
    ):
        a, a_info = replica(1, status="exited", exit_code=1)
        b, b_info = replica(2, status="exited", exit_code=1)
        docker_client.add_container(a, a_info)
        docker_client.add_container(b, b_info)
        await quarantine(engine, a, a_info)
        assert config_manager.is_quarantined("myapp_web")
        docker_client.restart_calls.clear()

        await engine._check_single_container(b)

        assert docker_client.restart_calls == ["myapp-web-2"]
        assert not config_manager.is_quarantined("myapp_web#2")

    async def test_quarantine_event_names_the_replica(self, engine, docker_client):
        b, b_info = replica(2, status="exited", exit_code=1)
        docker_client.add_container(b, b_info)

        await quarantine(engine, b, b_info)

        assert config_manager.get_quarantined_containers() == {"myapp_web#2"}
        quarantines = [e for e in config_manager.get_events() if e.event_type == "quarantine"]
        assert [e.container_name for e in quarantines] == ["myapp-web-2 (myapp_web#2)"]

    async def test_healthy_replica_does_not_unquarantine_another(self, engine, two_replicas):
        (a, a_info), (b, _b_info) = two_replicas
        await quarantine(engine, a, a_info)

        await engine._check_single_container(b)

        assert config_manager.is_quarantined("myapp_web")
        assert config_manager.get_total_restart_count("myapp_web") == 3
        assert not [e for e in config_manager.get_events() if e.event_type == "auto_unquarantine"]

    async def test_healthy_quarantined_replica_unquarantines_only_itself(
        self, engine, docker_client
    ):
        a, a_info = replica(1, status="exited", exit_code=1)
        b, b_info = replica(2, status="exited", exit_code=1)
        docker_client.add_container(a, a_info)
        docker_client.add_container(b, b_info)
        await quarantine(engine, a, a_info)
        await quarantine(engine, b, b_info)
        engine._backoff_delays["myapp_web#2"] = 999
        engine._backoff_delays["myapp_web"] = 999
        # Replica 2 comes back healthy.
        b_info["state"] = {"Status": "running", "ExitCode": 0}
        docker_client._info[b.id] = b_info

        await engine._check_single_container(b)

        assert not config_manager.is_quarantined("myapp_web#2")
        assert config_manager.get_total_restart_count("myapp_web#2") == 0
        initial = config_manager.get_config().restart.backoff.initial_seconds
        assert engine._backoff_delays["myapp_web#2"] == initial
        assert config_manager.is_quarantined("myapp_web")
        assert config_manager.get_total_restart_count("myapp_web") == 3
        assert engine._backoff_delays["myapp_web"] == 999
        events = [e for e in config_manager.get_events() if e.event_type == "auto_unquarantine"]
        assert [e.container_name for e in events] == ["myapp-web-2 (myapp_web#2)"]

    async def test_recreated_replica_keeps_its_restart_count(self, engine, docker_client):
        b, b_info = replica(2)
        docker_client.add_container(b, b_info)
        await engine._handle_container_restart(b, b_info, "unhealthy")
        # docker compose up recreates the replica: new ID, same container number.
        b2, b2_info = replica(2, container_id="f" * 64)
        docker_client.add_container(b2, b2_info)

        await engine._handle_container_restart(b2, b2_info, "unhealthy")

        assert config_manager.get_total_restart_count("myapp_web#2") == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_cooldown")
class TestPersistedStateCompatibility:
    async def test_pre_471_quarantine_entry_applies_to_replica_1_only(self, engine, docker_client):
        a, a_info = replica(1, status="exited", exit_code=1)
        b, b_info = replica(2, status="exited", exit_code=1)
        docker_client.add_container(a, a_info)
        docker_client.add_container(b, b_info)
        config_manager.quarantine_container("myapp_web")

        await engine._check_single_container(a)
        await engine._check_single_container(b)

        assert docker_client.restart_calls == ["myapp-web-2"]

    async def test_pre_471_restart_count_applies_to_replica_1(self, engine, docker_client):
        a, a_info = replica(1)
        docker_client.add_container(a, a_info)
        config_manager.record_restart("myapp_web")

        await engine._handle_container_restart(a, a_info, "unhealthy")

        assert config_manager.get_total_restart_count("myapp_web") == 2

    async def test_unscaled_compose_service_keeps_its_key(self, engine, docker_client):
        container, info = make_container(name="myapp-web-1", labels={"autoheal": "true", **COMPOSE})
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.get_total_restart_count("myapp_web") == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_cooldown")
class TestExplicitMonitoringIdIsShared:
    async def test_replicas_sharing_a_monitoring_id_share_recovery_state(
        self, engine, docker_client
    ):
        shared = {"monitoring.id": "shared-web"}
        a, a_info = replica(1, status="exited", exit_code=1, extra_labels=shared)
        b, b_info = replica(2, status="exited", exit_code=1, extra_labels=shared)
        docker_client.add_container(a, a_info)
        docker_client.add_container(b, b_info)

        await quarantine(engine, a, a_info)
        docker_client.restart_calls.clear()
        await engine._check_single_container(b)

        assert config_manager.is_quarantined("monitoring.id:shared-web")
        assert docker_client.restart_calls == []


class TestConfigurationStaysPerService:
    def test_selection_by_service_id_monitors_every_replica(self, engine, update_config):
        update_config(lambda c: c.containers.selected.append("myapp_web"))
        b, b_info = replica(2, extra_labels={"autoheal": "false"})

        assert engine.should_monitor_container(b, b_info) is True


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    monkeypatch.setattr("app.api.state.docker_client", docker_client)
    monkeypatch.setattr("app.api.state.monitoring_engine", engine)
    return docker_client


@pytest.mark.asyncio
class TestApiReportsPerReplicaState:
    async def test_list_shows_quarantine_and_count_per_replica(self, wired_api, two_replicas):
        config_manager.quarantine_container("myapp_web#2")
        config_manager.record_restart("myapp_web#2")

        result = {c.name: c for c in await list_containers(include_stopped=True)}

        assert result["myapp-web-1"].quarantined is False
        assert result["myapp-web-1"].restart_count == 0
        assert result["myapp-web-2"].quarantined is True
        assert result["myapp-web-2"].restart_count == 1

    async def test_details_show_per_replica_state(self, wired_api, two_replicas):
        config_manager.quarantine_container("myapp_web")
        config_manager.record_restart("myapp_web")

        replica_1 = await get_container_details("1" * 64)
        replica_2 = await get_container_details("2" * 64)

        assert (replica_1["quarantined"], replica_1["total_restart_count"]) == (True, 1)
        assert replica_1["recent_restart_count"] == 1
        assert (replica_2["quarantined"], replica_2["total_restart_count"]) == (False, 0)
        assert replica_2["recent_restart_count"] == 0

    async def test_unquarantining_one_replica_leaves_the_other(self, wired_api, two_replicas):
        for key in ("myapp_web", "myapp_web#2"):
            config_manager.quarantine_container(key)
            config_manager.record_restart(key)

        await unquarantine_container("2" * 64)

        assert not config_manager.is_quarantined("myapp_web#2")
        assert config_manager.get_total_restart_count("myapp_web#2") == 0
        assert config_manager.is_quarantined("myapp_web")
        assert config_manager.get_total_restart_count("myapp_web") == 1
        assert config_manager.get_events()[-1].container_name == "myapp-web-2 (myapp_web#2)"
