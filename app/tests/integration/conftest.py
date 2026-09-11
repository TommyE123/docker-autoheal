"""
Shared fixtures for the Docker Auto-Heal integration suite.

Unlike ``app/tests/unit``, these tests exercise the real Docker SDK and/or a
running Auto-Heal service (``http://localhost:3131``). They are never
collected by a plain ``pytest`` run (see ``pytest.ini``'s ``testpaths`` and
``docs/TESTING.md``) and every test here is skipped, rather than failed, when
the resource it needs isn't available.
"""

import uuid

import pytest
import requests

from app.docker_client.docker_client_wrapper import DockerClientWrapper

# Reuse the unit suite's isolation fixture instead of duplicating it: it patches
# the same global config_manager singleton, and integration tests that need
# isolated local config (rather than a real running service's config) want
# exactly the same behaviour.
from app.tests.unit.conftest import isolated_config_manager  # noqa: F401

AUTOHEAL_BASE_URL = "http://localhost:3131"

try:
    import docker
except ImportError:  # pragma: no cover - docker is a runtime dependency of the app
    docker = None


@pytest.fixture(scope="session")
def real_docker_client():
    """A DockerClientWrapper connected to the real Docker daemon. Skips if unreachable."""
    if docker is None:
        pytest.skip("docker SDK is not installed")

    try:
        wrapper = DockerClientWrapper()
    except Exception as exc:
        pytest.skip(f"No Docker daemon available: {exc}")

    try:
        yield wrapper
    finally:
        wrapper.close()


@pytest.fixture
def running_service():
    """Skip the test unless a live Auto-Heal service answers on localhost:3131."""
    try:
        response = requests.get(f"{AUTOHEAL_BASE_URL}/health", timeout=3)
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(f"No running Auto-Heal service at {AUTOHEAL_BASE_URL}: {exc}")
    return AUTOHEAL_BASE_URL


@pytest.fixture
def disposable_container(real_docker_client):
    """
    Factory fixture that runs throwaway containers and removes them afterwards.

    Uses the Docker SDK directly rather than DockerClientWrapper: the app never
    creates containers, only manages existing ones, so there's no wrapper method
    for this. Depending on real_docker_client just reuses its "skip if no daemon"
    check.

    Usage: ``container = disposable_container(image="nginx:alpine", labels={...})``
    """
    client = docker.DockerClient(base_url="unix://var/run/docker.sock")
    created = []

    def _run(image: str = "nginx:alpine", **run_kwargs):
        name = run_kwargs.pop("name", None) or f"autoheal-integration-{uuid.uuid4().hex[:12]}"
        container = client.containers.run(image=image, name=name, detach=True, **run_kwargs)
        created.append(container)
        return container

    try:
        yield _run
    finally:
        for container in created:
            try:
                container.remove(force=True)
            except docker.errors.NotFound:
                pass  # already removed by the test itself
        client.close()
