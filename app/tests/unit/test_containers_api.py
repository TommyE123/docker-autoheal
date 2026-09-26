"""
Unit tests for the container management endpoints in
``app/api/routes/containers.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client: none of them depend on FastAPI's request
parsing in a way that would be missed by calling the coroutine directly, and
this avoids adding a test-only HTTP client dependency the repository does not
already have. ``config_manager`` is isolated per test (see ``conftest.py``),
and the fake Docker client/monitoring engine mean no real Docker daemon is
ever touched.
"""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.models import ContainerSelectionRequest
from app.api.routes.containers import (
    get_container_details,
    list_containers,
    restart_container_manual,
    unquarantine_container,
    update_container_selection,
)
from app.config.config_manager import UptimeKumaMapping, config_manager
from app.tests.unit.conftest import make_container


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    """Point the API module's shared state at the fake Docker client/engine."""
    monkeypatch.setattr("app.api.state.docker_client", docker_client)
    monkeypatch.setattr("app.api.state.monitoring_engine", engine)
    return docker_client, engine


@pytest.fixture
def uninitialized_api(monkeypatch):
    """Simulate the API being called before ``init_api`` has run."""
    monkeypatch.setattr("app.api.state.docker_client", None)
    monkeypatch.setattr("app.api.state.monitoring_engine", None)


@pytest.mark.asyncio
class TestListContainers:
    async def test_returns_container_info_with_default_fields(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        result = await list_containers()

        assert len(result) == 1
        assert result[0].name == "web"
        assert result[0].monitored is True
        assert result[0].quarantined is False
        # Uptime-Kuma integration is disabled by default.
        assert result[0].uptime_kuma_status == 5

    async def test_reports_uptime_kuma_status_when_mapped(self, wired_api):
        docker_client, engine = wired_api
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.uptime_kuma.enabled = True
        config.uptime_kuma_mappings = [
            UptimeKumaMapping(container_id="web", monitor_friendly_name="Web Monitor")
        ]
        config_manager.update_config(config)
        engine.uptime_kuma_monitor = MagicMock()
        engine.uptime_kuma_monitor.is_container_mapped.return_value = True
        engine.uptime_kuma_monitor.get_container_status.return_value = 1  # up

        result = await list_containers()

        assert result[0].uptime_kuma_status == 1
        assert result[0].uptime_kuma_monitor_name == "Web Monitor"

    async def test_reports_unknown_status_when_uptime_kuma_monitor_not_initialized(
        self, wired_api
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.uptime_kuma.enabled = True
        config_manager.update_config(config)
        # engine has no `uptime_kuma_monitor` attribute, mirroring a service
        # that hasn't finished initializing the integration yet.
        assert not hasattr(engine, "uptime_kuma_monitor")

        result = await list_containers()

        assert result[0].uptime_kuma_status == 4
        assert result[0].uptime_kuma_monitor_name is None

    async def test_skips_containers_docker_could_not_inspect(self, wired_api):
        docker_client, _engine = wired_api
        # Registered with the client but with no info recorded, mirroring a
        # container that disappeared between listing and inspection.
        container, _info = make_container(name="vanished")
        docker_client._containers.append(container)

        result = await list_containers()

        assert result == []

    async def test_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await list_containers()

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestGetContainerDetails:
    async def test_returns_details_for_known_container(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        details = await get_container_details("a" * 64)

        assert details["name"] == "web"
        assert details["monitored"] is True
        assert details["quarantined"] is False
        assert details["total_restart_count"] == 0

    async def test_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_container_details("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_container_details("anything")

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestUpdateContainerSelection:
    async def test_enabling_adds_stable_id_and_clears_exclusion(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.containers.excluded = ["web"]
        config_manager.update_config(config)

        await update_container_selection(
            ContainerSelectionRequest(container_ids=["a" * 64], enabled=True)
        )

        updated = config_manager.get_config()
        assert "web" in updated.containers.selected
        assert "web" not in updated.containers.excluded

    async def test_disabling_adds_to_excluded_and_clears_selection(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.containers.selected = ["web"]
        config_manager.update_config(config)

        await update_container_selection(
            ContainerSelectionRequest(container_ids=["a" * 64], enabled=False)
        )

        updated = config_manager.get_config()
        assert "web" in updated.containers.excluded
        assert "web" not in updated.containers.selected

    async def test_unresolvable_container_falls_back_to_raw_identifier(self, wired_api):
        # No container registered with this id, so docker_client.get_container()
        # returns None and the endpoint must fall back to storing the raw id.
        await update_container_selection(
            ContainerSelectionRequest(container_ids=["ghost-container"], enabled=True)
        )

        updated = config_manager.get_config()
        assert "ghost-container" in updated.containers.selected


@pytest.mark.asyncio
class TestRestartContainerManual:
    async def test_successful_restart(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        result = await restart_container_manual("a" * 64)

        assert result["status"] == "success"
        assert docker_client.restart_calls == ["web"]

    async def test_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_docker_restart_failure_returns_500(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("a" * 64)

        assert exc_info.value.status_code == 500

    async def test_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("anything")

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestUnquarantineContainer:
    async def test_clears_quarantine_and_restart_history(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        config_manager.record_restart("web")

        result = await unquarantine_container("a" * 64)

        assert result["status"] == "success"
        assert config_manager.is_quarantined("web") is False
        assert config_manager.get_total_restart_count("web") == 0
        events = config_manager.get_events()
        event = events[-1]
        assert event.event_type == "unquarantine"
        assert event.timestamp.tzinfo is not None
        assert event.timestamp.utcoffset() == timedelta(0)

    async def test_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await unquarantine_container("does-not-exist")

        assert exc_info.value.status_code == 404
