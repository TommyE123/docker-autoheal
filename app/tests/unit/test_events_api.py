"""
Unit tests for the events API endpoints (GET/DELETE /api/events).

Calls the endpoint functions directly rather than over HTTP - config_manager
is isolated per test (see conftest.py) and neither endpoint touches Docker,
so a real HTTP round-trip against a running service would add nothing and
risks clearing a real installation's event history.
"""

import asyncio
from datetime import datetime, timezone

from app.api.api import clear_events, get_events
from app.config.config_manager import AutoHealEvent


def test_delete_events_clears_a_seeded_event(isolated_config_manager):
    isolated_config_manager.add_event(
        AutoHealEvent(
            timestamp=datetime.now(timezone.utc),
            container_id="test-container",
            container_name="test-container",
            event_type="restart",
            restart_count=1,
            status="success",
            message="seeded for the clear-events test",
        )
    )
    assert asyncio.run(get_events()) != []

    asyncio.run(clear_events())

    assert asyncio.run(get_events()) == []
