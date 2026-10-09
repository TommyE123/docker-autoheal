"""
Integration test for auto-monitoring: a container started with the running
service's configured monitor label (`autoheal.dev=true` for the dev stack) is
discovered by the running service's Docker event listener and added to
monitoring. Label matching itself - including
exclusions and unlabelled containers - is already covered against fakes in
`test_engine_lifecycle.py::TestProcessContainerStartEvent`; this exists to
prove the real event stream and the real running service actually wire up
end-to-end (it previously didn't - see #78/#81).

Requires a real Docker daemon *and* a running Auto-Heal service reachable at
AUTOHEAL_BASE_URL (default http://localhost:3132, the development stack).
"""

import time
import uuid

import pytest
import requests

from app.tests.integration.conftest import AUTOHEAL_BASE_URL

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


def test_container_with_monitor_label_is_auto_monitored(running_service, disposable_container):
    # Snapshot the real config before touching anything, so it can be restored
    # exactly afterward - auto-monitoring will mutate containers.selected.
    response = requests.get(f"{AUTOHEAL_BASE_URL}/api/config", timeout=5)
    response.raise_for_status()
    original_config = response.json()

    # The dev stack monitors autoheal.dev=true, not the production autoheal=true.
    monitor = original_config["monitor"]
    label = {monitor["label_key"]: monitor["label_value"]}

    container_name = f"autoheal-automonitor-{uuid.uuid4().hex[:12]}"
    container = disposable_container(image="nginx:alpine", name=container_name, labels=label)

    try:
        assert _wait_for_auto_monitor_event(container.id), (
            f"Expected an auto_monitor event for the labelled container within {POLL_TIMEOUT_SECONDS}s"
        )
    finally:
        # Left unguarded deliberately: if restoring the original config fails,
        # the test must fail loudly, not leave the running service modified.
        requests.put(f"{AUTOHEAL_BASE_URL}/api/config", json=original_config, timeout=5).raise_for_status()
