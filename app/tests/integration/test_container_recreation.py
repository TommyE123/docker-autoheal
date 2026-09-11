"""
Integration test for the container-ID-vs-stable-ID tracking bug: Docker
assigns a new container ID on every recreation, so restart/quarantine state
and monitoring selection must be tracked by a stable identifier instead.
Fake-based unit coverage of the same logic lives in
`test_monitoring_identity.py` / `test_restart_handling.py`; this validates it
against a real Docker recreation rather than a simulated ID change.

Requires a real Docker daemon; does not require a running Auto-Heal service.
"""

import uuid

import docker
import pytest

from app.docker_client.docker_client_wrapper import DockerClientWrapper
from app.monitor.monitoring_engine import MonitoringEngine

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(real_docker_client: DockerClientWrapper) -> MonitoringEngine:
    return MonitoringEngine(real_docker_client)


def _run_container(real_docker_client: DockerClientWrapper, name: str):
    client = real_docker_client._client
    return client.containers.run(
        image="alpine:latest",
        name=name,
        command=["sleep", "300"],
        detach=True,
    )


def test_restart_history_and_monitoring_survive_recreation(
    real_docker_client: DockerClientWrapper,
    isolated_config_manager,
    engine: MonitoringEngine,
):
    container_name = f"autoheal-recreate-{uuid.uuid4().hex[:12]}"
    container = _run_container(real_docker_client, container_name)

    try:
        info = real_docker_client.get_container_info(container)
        stable_id = engine.get_stable_identifier(info)
        assert stable_id == container_name

        # Select the container for monitoring by its stable ID (name).
        config = isolated_config_manager.get_config()
        config.containers.selected.append(stable_id)
        isolated_config_manager.update_config(config)

        assert engine.should_monitor_container(container, info) is True

        # Simulate prior restarts and a quarantine against the original container.
        isolated_config_manager.record_restart(stable_id)
        isolated_config_manager.record_restart(stable_id)
        isolated_config_manager.quarantine_container(stable_id)
        assert isolated_config_manager.get_restart_count(stable_id, window_seconds=600) == 2
        assert isolated_config_manager.is_quarantined(stable_id) is True

        original_full_id = info["full_id"]

        # Recreate: remove the old container and start a new one with the same name.
        container.remove(force=True)
        recreated = _run_container(real_docker_client, container_name)
        try:
            new_info = real_docker_client.get_container_info(recreated)

            # Docker assigned a brand new container ID.
            assert new_info["full_id"] != original_full_id

            # But the stable identifier - and everything tracked against it -
            # is unchanged.
            new_stable_id = engine.get_stable_identifier(new_info)
            assert new_stable_id == stable_id
            assert engine.should_monitor_container(recreated, new_info) is True
            assert isolated_config_manager.get_restart_count(stable_id, window_seconds=600) == 2
            assert isolated_config_manager.is_quarantined(stable_id) is True
        finally:
            recreated.remove(force=True)
    finally:
        try:
            container.reload()
            container.remove(force=True)
        except docker.errors.NotFound:
            pass  # already removed earlier in the test


def test_explicit_exclusion_persists_by_name_across_recreation(
    real_docker_client: DockerClientWrapper,
    isolated_config_manager,
    engine: MonitoringEngine,
):
    container_name = f"autoheal-exclude-{uuid.uuid4().hex[:12]}"
    container = _run_container(real_docker_client, container_name)

    try:
        info = real_docker_client.get_container_info(container)

        config = isolated_config_manager.get_config()
        config.containers.excluded.append(container_name)
        isolated_config_manager.update_config(config)

        assert engine.should_monitor_container(container, info) is False

        container.remove(force=True)
        recreated = _run_container(real_docker_client, container_name)
        try:
            new_info = real_docker_client.get_container_info(recreated)
            assert engine.should_monitor_container(recreated, new_info) is False
        finally:
            recreated.remove(force=True)
    finally:
        try:
            container.reload()
            container.remove(force=True)
        except docker.errors.NotFound:
            pass  # already removed earlier in the test
