"""
Integration test for reading Docker's native restart count.

Converted from the root-level `test_restart_count.py` debug script, which
printed `container.attrs` at several candidate locations against whatever
containers happened to already be running on the host, with no assertions.
`DockerClientWrapper.get_container_info` reads the count from
`attrs["State"]["RestartCount"]`; this test creates a disposable container,
forces Docker to restart it (bumping the real counter), and asserts the
wrapper reports the same value Docker does - a real regression check instead
of an exploratory print.

Requires a real Docker daemon; does not require a running Auto-Heal service.
"""

from app.docker_client.docker_client_wrapper import DockerClientWrapper


def test_restart_count_matches_docker_state(
    real_docker_client: DockerClientWrapper, disposable_container
):
    container = disposable_container(
        image="alpine:latest", command=["sleep", "300"]
    )

    info = real_docker_client.get_container_info(container)
    assert info["restart_count"] == 0

    container.restart(timeout=5)
    container.reload()

    info = real_docker_client.get_container_info(container)
    assert info["restart_count"] == container.attrs["State"]["RestartCount"]
    assert info["restart_count"] >= 1
