"""
Integration test for reading Docker's native restart count.

A manual `container.restart()` does not increment Docker's RestartCount - it's
specifically a count of restarts performed by Docker's own restart policy.
Use a container with `--restart on-failure` that exits immediately, and let
Docker restart it, to produce a real, deterministic increment.

Requires a real Docker daemon; does not require a running Auto-Heal service.
"""

import time

import pytest

from app.docker_client.docker_client_wrapper import DockerClientWrapper

pytestmark = pytest.mark.integration

RESTART_TIMEOUT_SECONDS = 15
POLL_INTERVAL_SECONDS = 1


def test_restart_count_reflects_a_policy_triggered_restart(
    real_docker_client: DockerClientWrapper, disposable_container
):
    container = disposable_container(
        image="alpine:latest",
        command=["sh", "-c", "exit 1"],
        restart_policy={"Name": "on-failure"},
    )

    deadline = time.monotonic() + RESTART_TIMEOUT_SECONDS
    restart_count = 0
    while time.monotonic() < deadline:
        info = real_docker_client.get_container_info(container)
        restart_count = info["restart_count"]
        if restart_count >= 1:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    assert restart_count >= 1, (
        f"Expected Docker to have restarted the container at least once within "
        f"{RESTART_TIMEOUT_SECONDS}s"
    )
    assert restart_count == container.attrs["RestartCount"]
