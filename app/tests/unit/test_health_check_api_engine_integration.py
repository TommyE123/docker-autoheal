"""
Integration coverage for the custom-health-check write path (the REST API)
and read path (``MonitoringEngine``) working together.

``test_api.py::TestHealthCheckManagement`` exercises ``add_health_check`` /
``get_health_check`` / ``delete_health_check`` in isolation, and
``test_health_evaluation.py::TestCustomHealthChecks`` exercises
``MonitoringEngine._evaluate_container_health()`` against health checks
planted directly via ``config_manager.add_custom_health_check()``. Neither
lets the API's real write path feed the engine's real read path, so a
mismatch between how each side keys a container's custom health check (see
issue #99, reproducing #30) would slip through both suites. These tests wire
the real API endpoint functions to a real ``MonitoringEngine``, with only
Docker itself faked via ``FakeDockerClient``/``make_container``.
"""

import pytest

from app.api.api import add_health_check, delete_health_check
from app.config.config_manager import HealthCheckConfig, config_manager
from app.tests.unit.conftest import make_container


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    """Point the API module's globals at the fake Docker client/engine."""
    monkeypatch.setattr("app.api.api.docker_client", docker_client)
    monkeypatch.setattr("app.api.api.monitoring_engine", engine)
    return docker_client, engine


@pytest.mark.asyncio
class TestCustomHealthCheckDiscoveryAcrossRecreation:
    """Custom health checks registered via the API, as seen by the engine."""

    @pytest.fixture(autouse=True)
    def _health_mode(self, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "health"))

    @staticmethod
    def _compose_container(container_id: str, name: str = "stack-web-1"):
        return make_container(
            name=name,
            container_id=container_id,
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )

    async def test_check_registered_via_api_is_discovered_by_engine(self, wired_api):
        docker_client, engine = wired_api
        container, info = self._compose_container(container_id="a" * 64)
        docker_client.add_container(container, info)
        docker_client.health_results[container.name] = False

        result = await add_health_check(
            HealthCheckConfig(container_id="stack-web-1", check_type="tcp", tcp_port=8080)
        )
        assert result["status"] == "success"

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is True
        assert reason == "Custom health check failed (tcp)"

    async def test_check_still_found_after_container_is_recreated(self, wired_api):
        """
        Reproduces #30: a container recreation gives Docker a brand new
        container ID (and, for containers without a fixed name, a new name),
        but its compose-derived stable ID is unchanged. A custom health check
        registered through the API before recreation must still be found by
        the engine afterwards.
        """
        docker_client, engine = wired_api
        original_container, original_info = self._compose_container(container_id="a" * 64)
        docker_client.add_container(original_container, original_info)

        await add_health_check(
            HealthCheckConfig(container_id="stack-web-1", check_type="tcp", tcp_port=8080)
        )

        stable_id = engine.get_stable_identifier(original_info)

        # Recreate: the old container is gone, a new one takes its place with
        # a new Docker ID but the same compose project/service labels.
        docker_client.remove_container(original_container)
        recreated_container, recreated_info = self._compose_container(container_id="b" * 64)
        docker_client.add_container(recreated_container, recreated_info)
        docker_client.health_results[recreated_container.name] = False

        assert recreated_info["full_id"] != original_info["full_id"]
        assert engine.get_stable_identifier(recreated_info) == stable_id

        needs_restart, reason = await engine._evaluate_container_health(
            recreated_container, recreated_info
        )

        assert needs_restart is True
        assert reason == "Custom health check failed (tcp)"

    async def test_check_deleted_via_api_is_no_longer_evaluated(self, wired_api):
        docker_client, engine = wired_api
        container, info = self._compose_container(container_id="a" * 64)
        docker_client.add_container(container, info)
        docker_client.health_results[container.name] = False

        await add_health_check(
            HealthCheckConfig(container_id="stack-web-1", check_type="tcp", tcp_port=8080)
        )
        needs_restart, _ = await engine._evaluate_container_health(container, info)
        assert needs_restart is True

        result = await delete_health_check("stack-web-1")
        assert result["status"] == "success"
        assert config_manager.get_all_custom_health_checks() == {}

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert needs_restart is False
        assert reason == ""
