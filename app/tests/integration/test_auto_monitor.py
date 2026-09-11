"""
Integration test for the auto-monitoring feature: containers started with the
`autoheal=true` label should be discovered and added to monitoring
automatically, and containers without it should not be.

Requires a real Docker daemon *and* a running Auto-Heal service reachable at
http://localhost:3131 (the service is what performs the auto-monitoring this
test observes via its API). Cleans up containers.selected afterward; the
auto_monitor event itself is left in the log, same as it would be from real
usage - the API only exposes clearing the entire log, not one event.
"""

import time
import uuid

import pytest
import requests

AUTOHEAL_BASE_URL = "http://localhost:3131"
POLL_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 2

pytestmark = pytest.mark.integration


def _matches(identifier: str, container) -> bool:
    return identifier in (container.id, container.name) or container.id.startswith(identifier)


def _wait_for_auto_monitor_event(container_id: str, timeout: float = POLL_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = requests.get(f"{AUTOHEAL_BASE_URL}/api/events", timeout=5)
        response.raise_for_status()
        events = response.json()
        if any(
            e.get("event_type") == "auto_monitor" and container_id in e.get("container_id", "")
            for e in events
        ):
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


def _deselect(container) -> None:
    """
    Undo auto-monitoring's effect on containers.selected. POSTing enabled=False
    to /api/containers/select would move the container into containers.excluded
    instead of clearing it - a different stale entry left behind - so edit the
    config directly.
    """
    response = requests.get(f"{AUTOHEAL_BASE_URL}/api/config", timeout=5)
    response.raise_for_status()
    config = response.json()
    config["containers"]["selected"] = [
        identifier for identifier in config["containers"]["selected"] if not _matches(identifier, container)
    ]
    response = requests.put(f"{AUTOHEAL_BASE_URL}/api/config", json=config, timeout=5)
    response.raise_for_status()


def test_container_with_autoheal_label_is_auto_monitored(
    real_docker_client, running_service, disposable_container
):
    container = disposable_container(
        image="nginx:alpine",
        name=f"autoheal-automonitor-{uuid.uuid4().hex[:12]}",
        labels={"autoheal": "true", "test": "auto-monitor-integration"},
        ports={"80/tcp": None},
    )

    try:
        assert _wait_for_auto_monitor_event(container.id), (
            "Expected an auto_monitor event for the labelled container within "
            f"{POLL_TIMEOUT_SECONDS}s"
        )

        response = requests.get(f"{AUTOHEAL_BASE_URL}/api/config", timeout=5)
        response.raise_for_status()
        selected = response.json()["containers"]["selected"]
        assert any(_matches(identifier, container) for identifier in selected)
    finally:
        _deselect(container)


def test_container_without_autoheal_label_is_not_auto_monitored(
    real_docker_client, running_service, disposable_container
):
    container = disposable_container(
        image="nginx:alpine",
        name=f"autoheal-nolabel-{uuid.uuid4().hex[:12]}",
        labels={"test": "auto-monitor-integration-no-label"},
    )

    assert not _wait_for_auto_monitor_event(container.id, timeout=10), (
        "Container without the autoheal=true label should not be auto-monitored"
    )
