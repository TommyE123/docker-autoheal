"""
Shared fixtures for the Docker Auto-Heal integration suite.

Unlike ``app/tests/unit``, these tests exercise the real Docker SDK and/or a
running Auto-Heal service (``http://localhost:3131``). They are never
collected by a plain ``pytest`` run (see ``pytest.ini``'s ``testpaths`` and
``docs/TESTING.md``) and every test here is skipped, rather than failed, when
the resource it needs isn't available - so this suite is safe to run in an
environment that only has some of those resources (e.g. Docker but no
running service).
"""

import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Iterator

import pytest
import requests

# Allow running pytest from anywhere in the repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.config.config_manager import AutoHealConfig, config_manager  # noqa: E402
from app.docker_client.docker_client_wrapper import DockerClientWrapper  # noqa: E402

AUTOHEAL_BASE_URL = "http://localhost:3131"

try:
    import docker as docker_sdk
except ImportError:  # pragma: no cover - docker is a runtime dependency of the app
    docker_sdk = None

_INTEGRATION_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    for item in items:
        if _INTEGRATION_DIR in Path(item.fspath).resolve().parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def real_docker_client():
    """
    A ``DockerClientWrapper`` connected to the real Docker daemon.

    Skips the test (rather than failing) when no daemon is reachable, so this
    suite can still run in a sandbox that has Docker but not the compose
    stack, or vice versa.
    """
    if docker_sdk is None:
        pytest.skip("docker SDK is not installed")

    try:
        wrapper = DockerClientWrapper()
    except Exception as exc:
        pytest.skip(f"No Docker daemon available: {exc}")
        return

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
def isolated_config_manager():
    """
    Point the global ``config_manager`` singleton at a per-test temp directory.

    Mirrors ``app/tests/unit/conftest.py``'s fixture of the same name so
    integration tests that only need a real Docker daemon (not a running
    service) never touch the real ``/data`` directory.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="autoheal-integration-test-"))

    original = {
        "DATA_DIR": config_manager.DATA_DIR,
        "CONFIG_FILE": config_manager.CONFIG_FILE,
        "EVENTS_FILE": config_manager.EVENTS_FILE,
        "RESTART_COUNTS_FILE": config_manager.RESTART_COUNTS_FILE,
        "QUARANTINE_FILE": config_manager.QUARANTINE_FILE,
        "MAINTENANCE_FILE": config_manager.MAINTENANCE_FILE,
        "_config": config_manager._config,
        "_event_log": config_manager._event_log,
        "_custom_health_checks": config_manager._custom_health_checks,
        "_quarantined_containers": config_manager._quarantined_containers,
        "_maintenance_mode": config_manager._maintenance_mode,
        "_maintenance_start_time": config_manager._maintenance_start_time,
    }

    config_manager.DATA_DIR = temp_dir
    config_manager._update_file_paths()
    config_manager._config = AutoHealConfig()
    config_manager._event_log = []
    config_manager._custom_health_checks = {}
    config_manager._quarantined_containers = set()
    config_manager._maintenance_mode = False
    config_manager._maintenance_start_time = None

    try:
        yield config_manager
    finally:
        for attribute, value in original.items():
            setattr(config_manager, attribute, value)
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def disposable_container(real_docker_client: DockerClientWrapper):
    """
    Factory fixture that runs throwaway containers and removes them afterwards.

    Usage: ``container = disposable_container(image="nginx:alpine", labels={...})``
    """
    created = []

    def _run(image: str = "nginx:alpine", **run_kwargs):
        client = real_docker_client._client
        name = run_kwargs.pop("name", None) or f"autoheal-integration-{uuid.uuid4().hex[:12]}"
        run_kwargs.setdefault("detach", True)
        container = client.containers.run(image=image, name=name, **run_kwargs)
        created.append(container)
        return container

    try:
        yield _run
    finally:
        for container in created:
            try:
                container.remove(force=True)
            except Exception:
                pass
