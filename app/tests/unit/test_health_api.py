"""
Unit tests for the health & status endpoints in ``app/api/routes/health.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client: none of them depend on FastAPI's request
parsing in a way that would be missed by calling the coroutine directly, and
this avoids adding a test-only HTTP client dependency the repository does not
already have. ``config_manager`` is isolated per test (see ``conftest.py``),
and the fake Docker client/monitoring engine mean no real Docker daemon is
ever touched.
"""

import pytest
from fastapi import HTTPException

from app.api.routes.health import get_system_status, health_check
from app.config.config_manager import config_manager
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
class TestHealthCheck:
    async def test_reports_disconnected_and_inactive_when_uninitialized(
        self, uninitialized_api
    ):
        result = await health_check()

        assert result["docker_connected"] is False
        assert result["monitoring_active"] is False
        assert result["status"] == "healthy"

    async def test_reports_connected_and_active(self, wired_api):
        docker_client, engine = wired_api
        engine._running = True

        result = await health_check()

        assert result["docker_connected"] is True
        assert result["monitoring_active"] is True


@pytest.mark.asyncio
class TestSystemStatus:
    async def test_counts_monitored_and_quarantined_containers(self, wired_api):
        docker_client, engine = wired_api
        monitored, monitored_info = make_container(name="web", status="running")
        docker_client.add_container(monitored, monitored_info)
        unmonitored, unmonitored_info = make_container(
            name="scratch", container_id="c" * 64, labels={}
        )
        docker_client.add_container(unmonitored, unmonitored_info)
        config_manager.quarantine_container("scratch")

        status = await get_system_status()

        assert status.total_containers == 2
        assert status.monitored_containers == 1
        assert status.quarantined_containers == 1
        assert status.docker_connected is True

    async def test_docker_failure_returns_500(self, wired_api):
        docker_client, _engine = wired_api
        docker_client.list_containers_error = RuntimeError("daemon unreachable")

        with pytest.raises(HTTPException) as exc_info:
            await get_system_status()

        assert exc_info.value.status_code == 500
