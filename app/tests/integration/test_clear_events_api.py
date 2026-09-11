"""
Integration test for the `DELETE /api/events` endpoint against a real,
running Auto-Heal service.

Converted from the root-level `test_clear_events_api.py` manual script, which
printed the request/response and made no assertions.

Requires a running Auto-Heal service reachable at http://localhost:3131 and a
real Docker daemon (used to seed at least one event, so the assertion below
proves DELETE actually cleared something rather than trivially passing
against an already-empty log).
"""

import requests

AUTOHEAL_BASE_URL = "http://localhost:3131"


def test_delete_events_clears_the_event_log(running_service, real_docker_client, disposable_container):
    container = disposable_container(image="alpine:latest", command=["sleep", "300"])

    # The unquarantine endpoint logs an event unconditionally for any known
    # container, regardless of whether it was actually quarantined - a
    # simple, deterministic way to seed the log without waiting on
    # auto-monitoring or a real restart.
    response = requests.post(
        f"{AUTOHEAL_BASE_URL}/api/containers/{container.id}/unquarantine", timeout=5
    )
    response.raise_for_status()

    response = requests.get(f"{AUTOHEAL_BASE_URL}/api/events", timeout=5)
    response.raise_for_status()
    assert response.json(), "Expected the seeded event to appear in the log before clearing it"

    response = requests.delete(f"{AUTOHEAL_BASE_URL}/api/events", timeout=5)
    response.raise_for_status()

    response = requests.get(f"{AUTOHEAL_BASE_URL}/api/events", timeout=5)
    response.raise_for_status()
    assert response.json() == []
