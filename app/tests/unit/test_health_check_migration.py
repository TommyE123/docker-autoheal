"""
Backwards-compatibility tests for legacy custom health checks.

Tests that custom health checks persisted using old Docker container ID keys
are properly migrated to stable container identifiers and remain discoverable
after container recreation.
"""

import pytest

from app.config.config_manager import HealthCheckConfig, config_manager
from app.tests.unit.conftest import make_container


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    """Point the API module's globals at the fake Docker client/engine."""
    monkeypatch.setattr("app.api.api.docker_client", docker_client)
    monkeypatch.setattr("app.api.api.monitoring_engine", engine)
    return docker_client, engine


@pytest.mark.asyncio
class TestHealthCheckMigration:
    """Backwards-compatibility for custom health checks persisted with old Docker IDs."""

    @pytest.fixture(autouse=True)
    def _health_mode(self, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "health"))

    async def test_legacy_docker_id_health_check_is_migrated(self, wired_api):
        """
        A health check stored under an old Docker container ID is migrated
        to the container's stable ID when that container is identified.
        """
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        legacy_docker_id = container.id
        stable_id = "web"

        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id=legacy_docker_id,
                check_type="tcp",
                tcp_port=8080,
            )
        )

        config_manager.migrate_legacy_health_checks(docker_client, engine)

        assert (
            config_manager.get_custom_health_check(stable_id) is not None
        ), "Health check should be available under stable ID after migration"
        assert (
            config_manager.get_custom_health_check(legacy_docker_id) is None
        ), "Health check should be removed from old Docker ID key after migration"

    async def test_unmigrated_orphaned_health_check_is_preserved(self, wired_api):
        """
        A health check for a container that no longer exists is preserved,
        in case the container reappears later (though this is unlikely).
        """
        docker_client, engine = wired_api

        orphaned_docker_id = "orphaned" + ("0" * 56)

        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id=orphaned_docker_id,
                check_type="http",
                http_endpoint="http://localhost/health",
            )
        )

        config_manager.migrate_legacy_health_checks(docker_client, engine)

        assert (
            config_manager.get_custom_health_check(orphaned_docker_id) is not None
        ), "Orphaned health check should be preserved under original Docker ID"

    async def test_new_stable_id_health_checks_unchanged_after_migration(self, wired_api):
        """
        Health checks already stored with stable IDs are not affected by migration.
        """
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        stable_id = "web"

        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id=stable_id,
                check_type="tcp",
                tcp_port=8080,
            )
        )

        config_manager.migrate_legacy_health_checks(docker_client, engine)

        assert (
            config_manager.get_custom_health_check(stable_id) is not None
        ), "Stable ID health check should remain accessible"

    async def test_migrated_health_check_discovered_by_engine(self, wired_api):
        """
        After migration, the MonitoringEngine can discover and execute
        the health check for a container.
        """
        docker_client, engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        docker_client.health_results[container.name] = False

        legacy_docker_id = container.id
        stable_id = "web"

        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id=legacy_docker_id,
                check_type="tcp",
                tcp_port=8080,
            )
        )

        config_manager.migrate_legacy_health_checks(docker_client, engine)

        needs_restart, reason = await engine._evaluate_container_health(container, info)

        assert (
            needs_restart is True
        ), "Engine should detect unhealthy custom health check after migration"
        assert reason == "Custom health check failed (tcp)"

    async def test_compose_container_migrates_to_compose_stable_id(self, wired_api):
        """
        A compose container with Docker ID key is migrated to its compose service stable ID.
        """
        docker_client, engine = wired_api
        container, info = make_container(
            name="stack-web-1",
            container_id="a" * 64,
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "mystack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)

        legacy_docker_id = container.id
        expected_stable_id = "mystack_web"

        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id=legacy_docker_id,
                check_type="tcp",
                tcp_port=8080,
            )
        )

        config_manager.migrate_legacy_health_checks(docker_client, engine)

        assert (
            config_manager.get_custom_health_check(expected_stable_id) is not None
        ), f"Health check should be migrated to compose stable ID {expected_stable_id}"
        assert (
            config_manager.get_custom_health_check(legacy_docker_id) is None
        ), "Health check should be removed from old Docker ID key"

    async def test_mixed_legacy_and_new_health_checks(self, wired_api):
        """
        When both legacy (Docker ID) and new (stable ID) health checks exist,
        migration handles both correctly.
        """
        docker_client, engine = wired_api

        container1, info1 = make_container(name="web", container_id="a" * 64)
        container2, info2 = make_container(name="db", container_id="b" * 64)
        docker_client.add_container(container1, info1)
        docker_client.add_container(container2, info2)

        legacy_docker_id = container1.id
        stable_id_1 = "web"
        stable_id_2 = "db"

        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id=legacy_docker_id,
                check_type="tcp",
                tcp_port=8080,
            )
        )

        config_manager.add_custom_health_check(
            HealthCheckConfig(
                container_id=stable_id_2,
                check_type="http",
                http_endpoint="http://localhost/health",
            )
        )

        config_manager.migrate_legacy_health_checks(docker_client, engine)

        assert (
            config_manager.get_custom_health_check(stable_id_1) is not None
        ), "Legacy health check should be migrated to stable ID"
        assert (
            config_manager.get_custom_health_check(stable_id_2) is not None
        ), "New-style stable ID health check should be preserved"
        assert (
            config_manager.get_custom_health_check(legacy_docker_id) is None
        ), "Old Docker ID key should be removed after migration"

        checks = config_manager.get_all_custom_health_checks()
        assert len(checks) == 2, "Should have exactly 2 health checks after migration"
