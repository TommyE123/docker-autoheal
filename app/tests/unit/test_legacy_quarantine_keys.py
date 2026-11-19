"""
Legacy quarantine entries filed under a container's name or full Docker ID.

Quarantine is written under the recovery ID, but older releases filed it under the
container name or the full Docker ID. The engine, the containers list and detail,
and the unquarantine endpoint must all agree on every form, or a container can stay
quarantined with no working way out (issue #241). The fixtures use Compose and
``monitoring.id`` containers, where the Docker ID, stable ID, name and recovery ID
all differ.
"""

import pytest

from app.api.errors import get_docker_client
from app.api.routes.containers import (
    get_container_details,
    list_containers,
    unquarantine_container,
)
from app.config.config_manager import config_manager
from app.docker_client.identity import recovery_keys
from app.tests.unit.conftest import make_container, until_stable

COMPOSE_LABELS = {
    "autoheal": "true",
    "com.docker.compose.project": "stack",
    "com.docker.compose.service": "web",
    "com.docker.compose.container-number": "2",
}


def compose_container(**kwargs):
    """A Compose replica: stable ID ``stack_web``, recovery ID ``compose:stack:web#2``."""
    return make_container(
        name="stack-web-2", container_id="c" * 64, labels=COMPOSE_LABELS, **kwargs
    )


def monitoring_id_container(**kwargs):
    """A ``monitoring.id`` container: stable ID ``api``, recovery ID ``monitoring.id:api``."""
    return make_container(name="api-1", container_id="d" * 64, stable_id="api", **kwargs)


CONTAINERS = pytest.mark.parametrize(
    "build", [compose_container, monitoring_id_container], ids=["compose", "monitoring_id"]
)
LEGACY_FORMS = pytest.mark.parametrize("form", ["name", "full_id"])


def all_keys(info: dict) -> list[str]:
    return recovery_keys(info["recovery_id"], info["name"], info["full_id"])


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    """Point the API module's shared state at the fake Docker client/engine."""
    monkeypatch.setattr("app.api.state.docker_client", docker_client)
    monkeypatch.setattr("app.api.state.monitoring_engine", engine)
    return docker_client


@CONTAINERS
def test_fixture_identifiers_all_differ(build):
    _container, info = build()

    identifiers = [info["full_id"], info["stable_id"], info["name"], info["recovery_id"]]

    assert len(set(identifiers)) == len(identifiers)


class TestRecoveryKeys:
    def test_returns_recovery_id_then_name_then_full_id(self):
        assert recovery_keys("compose:stack:web#2", "stack-web-2", "c" * 64) == [
            "compose:stack:web#2",
            "stack-web-2",
            "c" * 64,
        ]

    def test_recovery_id_equal_to_name_is_listed_once(self):
        assert recovery_keys("web", "web", "a" * 64) == ["web", "a" * 64]

    def test_duplicate_is_kept_at_its_first_position(self):
        assert recovery_keys("x", "y", "x") == ["x", "y"]

    def test_missing_and_empty_identifiers_are_skipped(self):
        assert recovery_keys(None, "web", "") == ["web"]
        assert recovery_keys("", None, "a" * 64) == ["a" * 64]

    def test_no_identifiers_gives_no_keys(self):
        assert recovery_keys(None, None, None) == []


@pytest.mark.asyncio
class TestQuarantinedFlag:
    @CONTAINERS
    @LEGACY_FORMS
    async def test_list_shows_legacy_entry_as_quarantined(self, wired_api, build, form):
        container, info = build()
        wired_api.add_container(container, info)
        config_manager.quarantine_container(info[form])

        result = await list_containers(get_docker_client())

        assert [c.quarantined for c in result] == [True]

    @CONTAINERS
    @LEGACY_FORMS
    async def test_detail_shows_legacy_entry_as_quarantined(self, wired_api, build, form):
        container, info = build()
        wired_api.add_container(container, info)
        config_manager.quarantine_container(info[form])

        details = await get_container_details(get_docker_client(), info["full_id"])

        assert details["quarantined"] is True

    @CONTAINERS
    async def test_other_containers_entries_do_not_mark_it_quarantined(self, wired_api, build):
        container, info = build()
        wired_api.add_container(container, info)
        config_manager.quarantine_container("other")

        result = await list_containers(get_docker_client())
        details = await get_container_details(get_docker_client(), info["full_id"])

        assert result[0].quarantined is False
        assert details["quarantined"] is False


@pytest.mark.asyncio
class TestUnquarantineEndpoint:
    @CONTAINERS
    @LEGACY_FORMS
    async def test_removes_a_legacy_entry(self, wired_api, build, form):
        container, info = build()
        wired_api.add_container(container, info)
        config_manager.quarantine_container(info[form])

        result = await unquarantine_container(get_docker_client(), info["full_id"])

        assert result["status"] == "success"
        assert config_manager.get_quarantined_containers() == set()
        details = await get_container_details(get_docker_client(), info["full_id"])
        assert details["quarantined"] is False

    @CONTAINERS
    async def test_removes_every_present_form_and_keeps_other_entries(self, wired_api, build):
        container, info = build()
        wired_api.add_container(container, info)
        for key in [*all_keys(info), "other"]:
            config_manager.quarantine_container(key)
        config_manager.record_restart(info["recovery_id"])

        result = await unquarantine_container(get_docker_client(), info["full_id"])

        assert result["status"] == "success"
        assert config_manager.get_quarantined_containers() == {"other"}
        assert config_manager.get_total_restart_count(info["recovery_id"]) == 0


@pytest.mark.asyncio
class TestEngineHonoursLegacyEntries:
    @CONTAINERS
    @LEGACY_FORMS
    async def test_legacy_entry_keeps_a_crashed_container_quarantined(
        self, engine, docker_client, build, form
    ):
        container, info = build(status="exited", exit_code=1)
        docker_client.add_container(container, info)
        config_manager.quarantine_container(info[form])

        await engine._check_single_container(container)

        assert docker_client.restart_calls == []
        assert config_manager.get_quarantined_containers() == {info[form]}

    @CONTAINERS
    async def test_auto_unquarantine_clears_every_present_form(self, engine, docker_client, build):
        container, info = build()
        docker_client.add_container(container, info)
        for key in [*all_keys(info), "other"]:
            config_manager.quarantine_container(key)
        config_manager.record_restart(info["recovery_id"])

        await until_stable(engine._check_single_container, container)

        assert config_manager.get_quarantined_containers() == {"other"}
        assert config_manager.get_total_restart_count(info["recovery_id"]) == 0
        assert [e.event_type for e in config_manager.get_events()] == ["auto_unquarantine"]
