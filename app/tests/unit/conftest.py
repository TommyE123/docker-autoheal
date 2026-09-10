"""
Shared fixtures for the Docker Auto-Heal unit-test suite.

These tests never touch a real Docker daemon and never touch the real /data
directory:

* ``FakeDockerClient`` stands in for ``DockerClientWrapper`` and serves
  canned container information.
* ``isolated_config_manager`` points the global ``config_manager`` singleton at
  a per-test temporary directory and resets its in-memory state, so every test
  starts from the documented defaults.
* ``mock_notification_manager`` replaces the global notification manager used
  by the monitoring engine, so no HTTP requests are ever attempted.
* ``recorded_sleeps`` replaces ``asyncio.sleep`` so restart-backoff delays are
  recorded rather than actually waited for, keeping tests fast and
  deterministic.
"""

import asyncio
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Allow running pytest from anywhere in the repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.config.config_manager import (  # noqa: E402
    AutoHealConfig,
    config_manager,
)
from app.docker_client.docker_client_wrapper import DockerClientWrapper  # noqa: E402
from app.monitor.monitoring_engine import MonitoringEngine  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeContainer:
    """
    Minimal stand-in for ``docker.models.containers.Container``.

    The monitoring engine only ever uses ``.name`` / ``.id`` directly and
    otherwise passes the object back to the Docker client wrapper, so a simple
    value object is enough.
    """

    def __init__(self, name: str, container_id: str, status: str = "running"):
        self.name = name
        self.id = container_id
        self.status = status

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<FakeContainer {self.name} {self.id[:12]}>"


def make_container(
    name: str = "web",
    container_id: str = "a" * 64,
    status: str = "running",
    labels: Optional[dict] = None,
    health: Optional[dict] = None,
    exit_code: int = 0,
) -> tuple[FakeContainer, dict]:
    """
    Build a ``(container, info)`` pair shaped like the real
    ``DockerClientWrapper.get_container_info`` output.

    Args:
        name: Container name.
        container_id: Full (64 character) container ID.
        status: Docker state status, e.g. ``running``/``exited``/``starting``.
        labels: Container labels. Defaults to ``{"autoheal": "true"}`` so the
            container is monitored under the default configuration.
        health: Docker native health dict, e.g. ``{"status": "unhealthy"}``.
        exit_code: Exit code reported in the container state.

    Returns:
        Tuple of the fake container object and its info dictionary.
    """
    labels = {"autoheal": "true"} if labels is None else labels
    container = FakeContainer(name=name, container_id=container_id, status=status)

    if "monitoring.id" in labels:
        stable_id = labels["monitoring.id"]
    elif labels.get("com.docker.compose.project") and labels.get("com.docker.compose.service"):
        stable_id = f"{labels['com.docker.compose.project']}_{labels['com.docker.compose.service']}"
    else:
        stable_id = name

    info = {
        "id": container_id[:12],
        "full_id": container_id,
        "name": name,
        "stable_id": stable_id,
        "image": "example:latest",
        "image_id": "sha256:" + ("b" * 64),
        "status": status,
        "state": {"Status": status, "ExitCode": exit_code},
        "labels": labels,
        "networks": ["bridge"],
        "created": "2024-01-01T00:00:00Z",
        "started_at": "2024-01-01T00:00:00Z",
        "finished_at": "0001-01-01T00:00:00Z",
        "exit_code": exit_code,
        "restart_count": 0,
        "health": health,
        "restart_policy": {"Name": "no"},
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
    }
    return container, info


class FakeDockerClient:
    """
    In-memory fake of :class:`DockerClientWrapper`.

    Only the surface actually used by the monitoring engine is implemented.
    Every method records its calls so tests can assert on observable
    behaviour (e.g. "the container was restarted once").
    """

    def __init__(self) -> None:
        self._containers: list[FakeContainer] = []
        self._info: dict[str, dict] = {}
        self.connected = True
        self.reconnect_succeeds = True
        self.restart_results: dict[str, bool] = {}
        self.restart_calls: list[str] = []
        self.reconnect_calls = 0
        self.list_containers_error: Optional[Exception] = None
        self.events: Any = []
        self.health_results: dict[str, bool] = {}
        self.native_health: dict[str, Optional[str]] = {}
        self.health_check_error: Optional[Exception] = None
        self.info_errors: dict[str, Exception] = {}

    # -- test helpers -------------------------------------------------------

    def add_container(self, container: FakeContainer, info: dict) -> None:
        """Register a container and the info dict the wrapper would return."""
        self._containers.append(container)
        self._info[container.id] = info

    def remove_container(self, container: FakeContainer) -> None:
        """
        Simulate a container disappearing between listing and inspection.

        The real wrapper returns an empty dict when ``container.reload()``
        raises (for example ``docker.errors.NotFound``), so the fake does the
        same.
        """
        self._containers = [c for c in self._containers if c.id != container.id]
        self._info.pop(container.id, None)

    # -- DockerClientWrapper surface ---------------------------------------

    def is_connected(self) -> bool:
        return self.connected

    def reconnect(self) -> bool:
        self.reconnect_calls += 1
        if self.reconnect_succeeds:
            self.connected = True
        return self.reconnect_succeeds

    def list_containers(self, all_containers: bool = False) -> list:
        if self.list_containers_error is not None:
            raise self.list_containers_error
        if all_containers:
            return list(self._containers)
        return [c for c in self._containers if c.status == "running"]

    def get_container(self, container_id: str):
        for container in self._containers:
            if container.id == container_id or container.name == container_id:
                return container
        return None

    def get_container_info(self, container: FakeContainer) -> dict:
        if container.id in self.info_errors:
            raise self.info_errors[container.id]
        # Mirrors the wrapper's behaviour of returning {} when inspection fails
        # (which is what happens when a container disappears).
        return deepcopy(self._info.get(container.id, {}))

    def restart_container(self, container: FakeContainer, timeout: int = 10) -> bool:
        self.restart_calls.append(container.name)
        return self.restart_results.get(container.name, True)

    def check_http_health(self, container, endpoint, expected_status=200, timeout=5) -> bool:
        if self.health_check_error is not None:
            raise self.health_check_error
        return self.health_results.get(container.name, True)

    def check_tcp_health(self, container, port, timeout=5) -> bool:
        if self.health_check_error is not None:
            raise self.health_check_error
        return self.health_results.get(container.name, True)

    def check_exec_health(self, container, command) -> bool:
        if self.health_check_error is not None:
            raise self.health_check_error
        return self.health_results.get(container.name, True)

    def get_docker_native_health(self, container) -> Optional[str]:
        if self.health_check_error is not None:
            raise self.health_check_error
        return self.native_health.get(container.name)

    def get_events(self, decode=True, filters=None):
        return self.events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_config_manager():
    """
    Isolate the global ``config_manager`` singleton for each test.

    The singleton is created at import time and persists to disk, so without
    this fixture tests would share state and write to the real data directory.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="autoheal-unit-test-"))

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
def update_config():
    """
    Return a helper that mutates and persists the active configuration.

    ``config_manager.get_config()`` hands back a deep copy, so configuration
    changes have to be written back through ``update_config``.
    """

    def _update(mutator):
        config = config_manager.get_config()
        mutator(config)
        config_manager.update_config(config)
        return config

    return _update


@pytest.fixture
def docker_client() -> FakeDockerClient:
    """A fake Docker client wrapper with no containers registered."""
    return FakeDockerClient()


@pytest.fixture(autouse=True)
def mock_notification_manager(monkeypatch) -> MagicMock:
    """Replace the notification manager so no outbound requests are made."""
    fake = MagicMock()
    fake.send_event_notification = AsyncMock()
    monkeypatch.setattr(
        "app.monitor.monitoring_engine.notification_manager",
        fake,
    )
    return fake


@pytest.fixture(autouse=True)
def recorded_sleeps(monkeypatch) -> list:
    """
    Replace ``asyncio.sleep`` with a recorder.

    The monitoring engine sleeps for the restart backoff delay; recording the
    requested delay makes backoff assertions possible without slowing the suite
    down or making it timing dependent.
    """
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        delays.append(delay)
        # Yield control without actually waiting.
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


@pytest.fixture
def engine(docker_client: FakeDockerClient) -> MonitoringEngine:
    """A monitoring engine wired to the fake Docker client."""
    return MonitoringEngine(docker_client)


@pytest.fixture
def wrapper_spec() -> MagicMock:
    """A strict mock limited to the real DockerClientWrapper API."""
    return MagicMock(spec=DockerClientWrapper)
