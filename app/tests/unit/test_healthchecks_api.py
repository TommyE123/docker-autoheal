"""
Unit tests for the custom health check management endpoints in
``app/api/routes/healthchecks.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client - ``config_manager`` is isolated per test
(see ``conftest.py``), and the fake Docker client/monitoring engine mean no
real Docker daemon is ever touched.
"""

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.errors import get_docker_client
from app.api.routes.healthchecks import (
    add_health_check,
    delete_health_check,
    get_health_check,
    list_health_checks,
)
from app.config.config_manager import HealthCheckConfig, config_manager
from app.tests.unit.conftest import make_container
from app.tests.unit.test_api_routing import _request


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    """Point the API module's shared state at the fake Docker client/engine."""
    monkeypatch.setattr("app.api.state.docker_client", docker_client)
    monkeypatch.setattr("app.api.state.monitoring_engine", engine)
    return docker_client, engine


@pytest.mark.asyncio
class TestHealthCheckManagement:
    async def test_add_health_check_resolves_full_container_id(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        result = await add_health_check(
            get_docker_client(),
            HealthCheckConfig(
                container_id="web",
                check_type="http",
                http_endpoint="http://localhost/health",
            ),
        )

        assert result["status"] == "success"
        stored = config_manager.get_custom_health_check("web")
        assert stored is not None
        assert stored.container_id == "web"
        assert stored.check_type == "http"

    async def test_add_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                get_docker_client(),
                HealthCheckConfig(container_id="does-not-exist", check_type="tcp", tcp_port=8080),
            )

        assert exc_info.value.status_code == 404

    async def test_get_health_check_returns_stored_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )

        result = await get_health_check(get_docker_client(), "web")

        assert result.container_id == "web"
        assert result.check_type == "tcp"

    async def test_get_health_check_missing_check_returns_404(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check(get_docker_client(), "web")

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

        result = await get_health_check(get_docker_client(), "web")

        assert result.container_id == "a" * 64
        assert result.check_type == "tcp"

    async def test_get_health_check_prefers_stable_id_over_legacy_full_docker_id(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id="web",
                check_type="http",
                http_endpoint="http://localhost/health",
            )
        )
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await get_health_check(get_docker_client(), "web")

        assert result.container_id == "web"
        assert result.check_type == "http"

    async def test_get_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_health_check(get_docker_client(), "does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_delete_health_check_removes_stored_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )

        result = await delete_health_check(get_docker_client(), "web")

        assert result["status"] == "success"
        assert config_manager.get_custom_health_check("web") is None

    async def test_delete_health_check_removes_legacy_full_docker_id(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await delete_health_check(get_docker_client(), "web")

        assert result["status"] == "success"
        assert config_manager.get_custom_health_check("a" * 64) is None

    async def test_delete_health_check_prefers_stable_id_over_legacy_full_docker_id(
        self, wired_api
    ):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id="web",
                check_type="http",
                http_endpoint="http://localhost/health",
            )
        )
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await delete_health_check(get_docker_client(), "web")

        assert result["status"] == "success"
        assert config_manager.get_custom_health_check("web") is None
        assert config_manager.get_custom_health_check("a" * 64) is not None

    async def test_delete_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check(get_docker_client(), "does-not-exist")

        assert exc_info.value.status_code == 404

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
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_container_info return empty dict to simulate inspection failure
        original_get_info = docker_client.get_container_info
        docker_client.get_container_info = lambda c: {}

        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                get_docker_client(),
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080),
            )

        docker_client.get_container_info = original_get_info
        assert exc_info.value.status_code == 500
        assert "Unable to inspect container" in exc_info.value.detail

    async def test_add_health_check_rejects_when_stable_id_cannot_be_resolved(self, wired_api):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_stable_identifier return None
        original_get_stable = engine.get_stable_identifier
        engine.get_stable_identifier = lambda info: None

        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                get_docker_client(),
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080),
            )

        engine.get_stable_identifier = original_get_stable
        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_get_health_check_rejects_when_container_inspection_fails(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_container_info return empty dict to simulate inspection failure
        original_get_info = docker_client.get_container_info
        docker_client.get_container_info = lambda c: {}

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check(get_docker_client(), "web")

        docker_client.get_container_info = original_get_info
        assert exc_info.value.status_code == 500
        assert "Unable to inspect container" in exc_info.value.detail

    async def test_get_health_check_rejects_when_stable_id_cannot_be_resolved(self, wired_api):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_stable_identifier return None
        original_get_stable = engine.get_stable_identifier
        engine.get_stable_identifier = lambda info: None

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check(get_docker_client(), "web")

        engine.get_stable_identifier = original_get_stable
        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_delete_health_check_rejects_when_container_inspection_fails(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_container_info return empty dict to simulate inspection failure
        original_get_info = docker_client.get_container_info
        docker_client.get_container_info = lambda c: {}

        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check(get_docker_client(), "web")

        docker_client.get_container_info = original_get_info
        assert exc_info.value.status_code == 500
        assert "Unable to inspect container" in exc_info.value.detail

    async def test_delete_health_check_rejects_when_stable_id_cannot_be_resolved(self, wired_api):
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Make get_stable_identifier return None
        original_get_stable = engine.get_stable_identifier
        engine.get_stable_identifier = lambda info: None

        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check(get_docker_client(), "web")

        engine.get_stable_identifier = original_get_stable
        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail

    async def test_add_health_check_handles_unexpected_error_in_config_manager(
        self, wired_api, monkeypatch
    ):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Mock config_manager.add_custom_health_check to raise an exception
        def mock_add_raises(health_check):
            raise ValueError("Unexpected config error")

        monkeypatch.setitem(vars(config_manager), "add_custom_health_check", mock_add_raises)

        with pytest.raises(ValueError, match="Unexpected config error"):
            await add_health_check(
                get_docker_client(),
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080),
            )

    async def test_get_health_check_handles_unexpected_error(self, wired_api, monkeypatch):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        # Mock config_manager.get_custom_health_check to raise an exception
        def mock_get_raises(container_id):
            raise ValueError("Unexpected config error")

        monkeypatch.setitem(vars(config_manager), "get_custom_health_check", mock_get_raises)

        with pytest.raises(ValueError, match="Unexpected config error"):
            await get_health_check(get_docker_client(), "web")

    async def test_delete_health_check_handles_unexpected_error(self, wired_api, monkeypatch):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        # A stored check, so the delete reaches remove_custom_health_check
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )

        # Mock config_manager.remove_custom_health_check to raise an exception
        def mock_remove_raises(container_id):
            raise ValueError("Unexpected config error")

        monkeypatch.setitem(vars(config_manager), "remove_custom_health_check", mock_remove_raises)

        with pytest.raises(ValueError, match="Unexpected config error"):
            await delete_health_check(get_docker_client(), "web")

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
                get_docker_client(),
                HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080),
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
            await get_health_check(get_docker_client(), "web")

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
            await delete_health_check(get_docker_client(), "web")

        assert exc_info.value.status_code == 500
        assert "Unable to resolve container stable identifier" in exc_info.value.detail


INVALID_CHECKS = [
    pytest.param({"check_type": "http"}, "http_endpoint", id="http-missing-endpoint"),
    pytest.param(
        {"check_type": "http", "http_endpoint": "/h", "http_expected_status": None},
        "http_expected_status",
        id="http-null-status",
    ),
    pytest.param({"check_type": "tcp"}, "tcp_port", id="tcp-missing-port"),
    pytest.param({"check_type": "exec"}, "exec_command", id="exec-missing-command"),
    pytest.param({"check_type": "carrier-pigeon"}, "Unknown check_type", id="unknown-type"),
    pytest.param(
        {"check_type": "http", "http_endpoint": ""},
        "http_endpoint must not be empty",
        id="http-empty-endpoint",
    ),
    pytest.param(
        {"check_type": "http", "http_endpoint": "   "},
        "http_endpoint must not be empty",
        id="http-blank-endpoint",
    ),
    pytest.param({"check_type": "tcp", "tcp_port": 0}, "between 1 and 65535", id="tcp-port-zero"),
    pytest.param(
        {"check_type": "tcp", "tcp_port": -1},
        "between 1 and 65535",
        id="tcp-port-negative",
    ),
    pytest.param(
        {"check_type": "tcp", "tcp_port": 65536},
        "between 1 and 65535",
        id="tcp-port-too-high",
    ),
    pytest.param(
        {"check_type": "exec", "exec_command": []},
        "non-blank command",
        id="exec-empty-list",
    ),
    pytest.param(
        {"check_type": "exec", "exec_command": [""]},
        "non-blank command",
        id="exec-empty-command",
    ),
    pytest.param(
        {"check_type": "exec", "exec_command": [" "]},
        "non-blank command",
        id="exec-blank-command",
    ),
]


class TestHealthCheckValidation:
    @pytest.mark.parametrize(("fields", "expected"), INVALID_CHECKS)
    def test_model_rejects_check_missing_required_field(self, fields, expected):
        with pytest.raises(ValidationError, match=expected):
            HealthCheckConfig(container_id="web", **fields)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("fields", "expected"), INVALID_CHECKS)
    async def test_post_returns_422_and_stores_nothing(self, wired_api, fields, expected):
        status, body, _ = await _request(
            "POST",
            "/api/healthchecks",
            request_headers={"content-type": "application/json"},
            body=json.dumps({"container_id": "web", **fields}).encode(),
        )

        assert status == 422
        assert expected in body.decode()
        assert config_manager.get_all_custom_health_checks() == {}

    @pytest.mark.parametrize(
        "fields",
        [
            {"check_type": "http", "http_endpoint": "http://localhost/"},
            {"check_type": "tcp", "tcp_port": 8080},
            {"check_type": "tcp", "tcp_port": 1},
            {"check_type": "tcp", "tcp_port": 65535},
            {"check_type": "exec", "exec_command": ["true"]},
            {"check_type": "exec", "exec_command": ["echo", " "]},
            {"check_type": "exec", "exec_command": ["sh", "-c", ""]},
            {"check_type": "docker"},
        ],
    )
    def test_model_accepts_valid_check_of_each_type(self, fields):
        assert HealthCheckConfig(container_id="web", **fields).check_type == fields["check_type"]


_COMPOSE_WEB = {
    "autoheal": "true",
    "com.docker.compose.project": "stack",
    "com.docker.compose.service": "web",
}
_FULL_ID = "a" * 64


def _compose_web(number: int = 1, container_id: str = _FULL_ID):
    """A Compose container whose stable ID (stack_web), name and Docker ID all differ."""
    return make_container(
        name=f"stack-web-{number}",
        container_id=container_id,
        labels={**_COMPOSE_WEB, "com.docker.compose.container-number": str(number)},
    )


def _tcp_check(key: str, port: int = 8080) -> HealthCheckConfig:
    return HealthCheckConfig(container_id=key, check_type="tcp", tcp_port=port)


@pytest.mark.asyncio
class TestNameKeyedHealthChecks:
    """GET and DELETE find a name-keyed check as the engine does, and refuse when unsure."""

    def _add_owner(self, docker_client, status: str = "running"):
        """Another container whose stable identifier is the first container's name."""
        owner, owner_info = make_container(
            name="other", container_id="b" * 64, stable_id="stack-web-1", status=status
        )
        docker_client.add_container(owner, owner_info)

    async def test_get_and_delete_find_a_name_keyed_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        got = await get_health_check(get_docker_client(), _FULL_ID)
        assert got.container_id == "stack-web-1"

        await delete_health_check(get_docker_client(), _FULL_ID)
        assert config_manager.get_all_custom_health_checks() == {}

    async def test_check_added_then_identity_label_added_can_be_deleted(self, wired_api):
        """A plain container's check (stored under its name) stays manageable after the
        container is recreated with a monitoring.id label."""
        docker_client, _engine = wired_api
        old, old_info = make_container(name="web", container_id="1" * 64)
        docker_client.add_container(old, old_info)
        await add_health_check(get_docker_client(), _tcp_check("web"))
        docker_client.remove_container(old)
        new, new_info = make_container(name="web", container_id="2" * 64, stable_id="web-svc")
        docker_client.add_container(new, new_info)

        assert (await get_health_check(get_docker_client(), "web")).container_id == "web"
        await delete_health_check(get_docker_client(), "web")
        assert config_manager.get_all_custom_health_checks() == {}

    async def test_stable_id_match_does_not_list_docker(self, wired_api):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        docker_client.add_container(container, info)
        docker_client.list_containers_error = RuntimeError("must not be listed")
        config_manager.add_custom_health_check(_tcp_check("stack_web"))
        config_manager.add_custom_health_check(_tcp_check("stack-web-1", port=9090))

        assert (await get_health_check(get_docker_client(), _FULL_ID)).tcp_port == 8080
        await delete_health_check(get_docker_client(), _FULL_ID)
        assert set(config_manager.get_all_custom_health_checks()) == {"stack-web-1"}

    @pytest.mark.parametrize("owner_status", ["running", "exited"])
    async def test_ambiguous_name_keyed_check_returns_409(self, wired_api, owner_status):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        docker_client.add_container(container, info)
        self._add_owner(docker_client, owner_status)
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        for endpoint in (get_health_check, delete_health_check):
            with pytest.raises(HTTPException) as exc_info:
                await endpoint(get_docker_client(), _FULL_ID)
            assert exc_info.value.status_code == 409
            assert exc_info.value.detail == (
                "The custom health check stored under 'stack-web-1' is ambiguous: "
                "'stack-web-1' is this container's name and also the stable identifier of "
                "'other'. Set a unique monitoring.id label on that container so the key "
                "identifies one container."
            )
        assert set(config_manager.get_all_custom_health_checks()) == {"stack-web-1"}

    async def test_ambiguous_name_falls_through_to_an_exact_full_id_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        docker_client.add_container(container, info)
        self._add_owner(docker_client)
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))
        config_manager.add_custom_health_check(_tcp_check(_FULL_ID, port=9090))

        assert (await get_health_check(get_docker_client(), _FULL_ID)).tcp_port == 9090
        await delete_health_check(get_docker_client(), _FULL_ID)
        assert set(config_manager.get_all_custom_health_checks()) == {"stack-web-1"}

    async def test_owner_still_manages_its_own_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        docker_client.add_container(container, info)
        self._add_owner(docker_client)
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        assert (await get_health_check(get_docker_client(), "other")).container_id == (
            "stack-web-1"
        )
        await delete_health_check(get_docker_client(), "other")
        assert config_manager.get_all_custom_health_checks() == {}

    async def test_failed_listing_returns_503_and_removes_nothing(self, wired_api):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        docker_client.add_container(container, info)
        docker_client.list_containers_error = RuntimeError("daemon unreachable")
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        for endpoint in (get_health_check, delete_health_check):
            with pytest.raises(HTTPException) as exc_info:
                await endpoint(get_docker_client(), _FULL_ID)
            assert exc_info.value.status_code == 503
            assert "Could not list Docker containers" in exc_info.value.detail
            assert "'stack-web-1'" in exc_info.value.detail
        assert set(config_manager.get_all_custom_health_checks()) == {"stack-web-1"}

    async def test_uninspectable_container_in_the_listing_returns_503(self, wired_api):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        other, _other_info = make_container(name="other", container_id="b" * 64)
        docker_client.add_container(container, info)
        docker_client.add_container(other, {})  # the wrapper returns {} when inspection fails
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))

        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check(get_docker_client(), _FULL_ID)

        assert exc_info.value.status_code == 503
        assert set(config_manager.get_all_custom_health_checks()) == {"stack-web-1"}

    async def test_failed_listing_still_allows_an_exact_full_id_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = _compose_web()
        docker_client.add_container(container, info)
        docker_client.list_containers_error = RuntimeError("daemon unreachable")
        config_manager.add_custom_health_check(_tcp_check("stack-web-1"))
        config_manager.add_custom_health_check(_tcp_check(_FULL_ID, port=9090))

        assert (await get_health_check(get_docker_client(), _FULL_ID)).tcp_port == 9090

    async def test_replicas_share_the_check_under_their_stable_id(self, wired_api):
        docker_client, _engine = wired_api
        first, first_info = _compose_web(1, "a" * 64)
        second, second_info = _compose_web(2, "b" * 64)
        docker_client.add_container(first, first_info)
        docker_client.add_container(second, second_info)
        docker_client.list_containers_error = RuntimeError("must not be listed")
        config_manager.add_custom_health_check(_tcp_check("stack_web"))

        for replica in ("stack-web-1", "stack-web-2"):
            assert (await get_health_check(get_docker_client(), replica)).container_id == (
                "stack_web"
            )
