"""
Unit tests for the custom health check management endpoints in
``app/api/routes/healthchecks.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client - ``config_manager`` is isolated per test
(see ``conftest.py``), and the fake Docker client/monitoring engine mean no
real Docker daemon is ever touched.
"""

import pytest
from fastapi import HTTPException

from app.api.routes.healthchecks import (
    add_health_check,
    delete_health_check,
    get_health_check,
    list_health_checks,
)
from app.config.config_manager import HealthCheckConfig, config_manager
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
class TestHealthCheckManagement:
    async def test_add_health_check_resolves_full_container_id(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        result = await add_health_check(
            HealthCheckConfig(
                container_id="web",
                check_type="http",
                http_endpoint="http://localhost/health",
            )
        )

        assert result["status"] == "success"
        stored = config_manager.get_custom_health_check("web")
        assert stored is not None
        assert stored.container_id == "web"
        assert stored.check_type == "http"

    async def test_add_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                HealthCheckConfig(
                    container_id="does-not-exist", check_type="tcp", tcp_port=8080
                )
            )

        assert exc_info.value.status_code == 404

    async def test_add_health_check_uninitialized_docker_client_returns_500(
        self, uninitialized_api
    ):
        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
            )

        assert exc_info.value.status_code == 500

    async def test_get_health_check_returns_stored_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )

        result = await get_health_check("web")

        assert result.container_id == "web"
        assert result.check_type == "tcp"

    async def test_get_health_check_missing_check_returns_404(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        assert exc_info.value.status_code == 404

    async def test_get_health_check_falls_back_to_legacy_full_docker_id(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        # A check persisted before stable-ID storage, still keyed by the
        # container's current full Docker ID.
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await get_health_check("web")

        assert result.container_id == "a" * 64
        assert result.check_type == "tcp"

    async def test_get_health_check_prefers_stable_id_over_legacy_full_docker_id(
        self, wired_api
    ):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="http", http_endpoint="http://localhost/health")
        )
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await get_health_check("web")

        assert result.container_id == "web"
        assert result.check_type == "http"

    async def test_get_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_get_health_check_uninitialized_docker_client_returns_500(
        self, uninitialized_api
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        assert exc_info.value.status_code == 500

    async def test_delete_health_check_removes_stored_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )

        result = await delete_health_check("web")

        assert result["status"] == "success"
        assert config_manager.get_custom_health_check("web") is None

    async def test_delete_health_check_removes_legacy_full_docker_id(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await delete_health_check("web")

        assert result["status"] == "success"
        assert config_manager.get_custom_health_check("a" * 64) is None

    async def test_delete_health_check_prefers_stable_id_over_legacy_full_docker_id(
        self, wired_api
    ):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="http", http_endpoint="http://localhost/health")
        )
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await delete_health_check("web")

        assert result["status"] == "success"
        assert config_manager.get_custom_health_check("web") is None
        assert config_manager.get_custom_health_check("a" * 64) is not None

    async def test_delete_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_delete_health_check_uninitialized_docker_client_returns_500(
        self, uninitialized_api
    ):
        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("web")

        assert exc_info.value.status_code == 500

    async def test_list_health_checks_returns_all_registered_checks(self):
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )
        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id="b" * 64,
                check_type="http",
                http_endpoint="http://localhost/",
            )
        )

        result = await list_health_checks()

        assert set(result.keys()) == {"a" * 64, "b" * 64}

    async def test_list_health_checks_empty_by_default(self):
        assert await list_health_checks() == {}

    async def test_add_health_check_rejects_when_container_inspection_fails(
        self, wired_api, monkeypatch
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_container_info return empty dict to simulate inspection failure
        original_get_info = docker_client.get_container_info
        docker_client.get_container_info = lambda c: {}

        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
            )

        docker_client.get_container_info = original_get_info
        assert exc_info.value.status_code == 500
        assert "Unable to inspect container" in exc_info.value.detail

    async def test_add_health_check_rejects_when_stable_id_cannot_be_resolved(
        self, wired_api
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_stable_identifier return None
        original_get_stable = engine.get_stable_identifier
        engine.get_stable_identifier = lambda info: None

        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
            )

        engine.get_stable_identifier = original_get_stable
        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_get_health_check_rejects_when_container_inspection_fails(
        self, wired_api
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_container_info return empty dict to simulate inspection failure
        original_get_info = docker_client.get_container_info
        docker_client.get_container_info = lambda c: {}

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        docker_client.get_container_info = original_get_info
        assert exc_info.value.status_code == 500
        assert "Unable to inspect container" in exc_info.value.detail

    async def test_get_health_check_rejects_when_stable_id_cannot_be_resolved(
        self, wired_api
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_stable_identifier return None
        original_get_stable = engine.get_stable_identifier
        engine.get_stable_identifier = lambda info: None

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        engine.get_stable_identifier = original_get_stable
        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_delete_health_check_rejects_when_container_inspection_fails(
        self, wired_api
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_container_info return empty dict to simulate inspection failure
        original_get_info = docker_client.get_container_info
        docker_client.get_container_info = lambda c: {}

        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("web")

        docker_client.get_container_info = original_get_info
        assert exc_info.value.status_code == 500
        assert "Unable to inspect container" in exc_info.value.detail

    async def test_delete_health_check_rejects_when_stable_id_cannot_be_resolved(
        self, wired_api
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_stable_identifier return None
        original_get_stable = engine.get_stable_identifier
        engine.get_stable_identifier = lambda info: None

        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("web")

        engine.get_stable_identifier = original_get_stable
        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_add_health_check_handles_unexpected_error_in_config_manager(
        self, wired_api, monkeypatch
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Mock config_manager.add_custom_health_check to raise an exception
        original_add = config_manager.add_custom_health_check
        def mock_add_raises(check):
            raise ValueError("Unexpected config error")
        config_manager.add_custom_health_check = mock_add_raises

        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
            )

        config_manager.add_custom_health_check = original_add
        assert exc_info.value.status_code == 500

    async def test_get_health_check_handles_unexpected_error(
        self, wired_api, monkeypatch
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Mock config_manager.get_custom_health_check to raise an exception
        original_get = config_manager.get_custom_health_check
        def mock_get_raises(container_id):
            raise ValueError("Unexpected config error")
        config_manager.get_custom_health_check = mock_get_raises

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        config_manager.get_custom_health_check = original_get
        assert exc_info.value.status_code == 500

    async def test_delete_health_check_handles_unexpected_error(
        self, wired_api, monkeypatch
    ):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Mock config_manager.remove_custom_health_check to raise an exception
        original_remove = config_manager.remove_custom_health_check
        def mock_remove_raises(container_id):
            raise ValueError("Unexpected config error")
        config_manager.remove_custom_health_check = mock_remove_raises

        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("web")

        config_manager.remove_custom_health_check = original_remove
        assert exc_info.value.status_code == 500

    async def test_add_health_check_rejects_when_monitoring_engine_not_initialized(
        self, monkeypatch, docker_client
    ):
        docker_client_val = docker_client
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client_val.add_container(container, info)

        # Set docker_client but not monitoring_engine
        monkeypatch.setattr("app.api.state.docker_client", docker_client_val)
        monkeypatch.setattr("app.api.state.monitoring_engine", None)

        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
            )

        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_get_health_check_rejects_when_monitoring_engine_not_initialized(
        self, monkeypatch, docker_client
    ):
        docker_client_val = docker_client
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client_val.add_container(container, info)

        # Set docker_client but not monitoring_engine
        monkeypatch.setattr("app.api.state.docker_client", docker_client_val)
        monkeypatch.setattr("app.api.state.monitoring_engine", None)

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_delete_health_check_rejects_when_monitoring_engine_not_initialized(
        self, monkeypatch, docker_client
    ):
        docker_client_val = docker_client
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client_val.add_container(container, info)

        # Set docker_client but not monitoring_engine
        monkeypatch.setattr("app.api.state.docker_client", docker_client_val)
        monkeypatch.setattr("app.api.state.monitoring_engine", None)

        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("web")

        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail
