"""
Integration test for the `DELETE /api/events` endpoint against a real,
running Auto-Heal service.

Converted from the root-level `test_clear_events_api.py` manual script, which
printed the request/response and made no assertions.

Requires a running Auto-Heal service reachable at http://localhost:3131.
"""

import requests

AUTOHEAL_BASE_URL = "http://localhost:3131"


def test_delete_events_clears_the_event_log(running_service):
    response = requests.delete(f"{AUTOHEAL_BASE_URL}/api/events", timeout=5)
    response.raise_for_status()

    response = requests.get(f"{AUTOHEAL_BASE_URL}/api/events", timeout=5)
    response.raise_for_status()
    assert response.json() == []
