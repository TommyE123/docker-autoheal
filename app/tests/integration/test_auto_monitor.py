"""
Integration test for auto-monitoring: a container started with the
`autoheal=true` label is discovered by the running service's Docker event
listener and added to monitoring. Label matching itself - including
exclusions and unlabelled containers - is already covered against fakes in
`test_engine_lifecycle.py::TestProcessContainerStartEvent`; this exists to
prove the real event stream and the real running service actually wire up
end-to-end (it previously didn't - see #78/#81).

Requires a real Docker daemon *and* a running Auto-Heal service reachable at
http://localhost:3131.
"""

import time
import uuid

import pytest
import requests

AUTOHEAL_BASE_URL = "http://localhost:3131"
POLL_TIMEOUT_SECONDS = 30

pytestmark = pytest.mark.integration


def _wait_for_auto_monitor_event(container_id: str) -> bool:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response = requests.get(f"{AUTOHEAL_BASE_URL}/api/events", timeout=5)
        response.raise_for_status()
        if any(
            e["event_type"] == "auto_monitor" and container_id in e["container_id"]
            for e in response.json()
        ):
            return True
        time.sleep(2)
    return False


def test_container_with_autoheal_label_is_auto_monitored(running_service, disposable_container):
    container_name = f"autoheal-automonitor-{uuid.uuid4().hex[:12]}"
    container = disposable_container(image="nginx:alpine", name=container_name, labels={"autoheal": "true"})

    try:
        assert _wait_for_auto_monitor_event(container.id), (
            f"Expected an auto_monitor event for the labelled container within {POLL_TIMEOUT_SECONDS}s"
        )
    finally:
        # Auto-monitoring adds the container (by name - it has no monitoring.id
        # or compose labels) to the service's real containers.selected.
        # POSTing enabled=False to /api/containers/select would move it to
        # containers.excluded instead of clearing it, so edit config directly.
        response = requests.get(f"{AUTOHEAL_BASE_URL}/api/config", timeout=5)
        response.raise_for_status()
        config = response.json()
        config["containers"]["selected"] = [
            s for s in config["containers"]["selected"] if s != container_name
        ]
        requests.put(f"{AUTOHEAL_BASE_URL}/api/config", json=config, timeout=5).raise_for_status()
