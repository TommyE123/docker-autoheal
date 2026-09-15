"""
Unit tests for the events API endpoints (GET/DELETE /api/events).

Calls the endpoint functions directly rather than over HTTP - config_manager
is isolated per test (see conftest.py) and neither endpoint touches Docker,
so a real HTTP round-trip against a running service would add nothing and
risks clearing a real installation's event history.
"""

import asyncio
import json
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


def test_events_api_serializes_utc_timestamp(isolated_config_manager):
    timestamp = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    isolated_config_manager.add_event(
        AutoHealEvent(
            timestamp=timestamp,
            container_id="test-container",
            container_name="test-container",
            event_type="restart",
            restart_count=1,
            status="success",
            message="serialized event",
        )
    )

    events = asyncio.run(get_events())

    assert events[0]["timestamp"] == timestamp.isoformat()


def test_events_api_preserves_legacy_naive_timestamp_text(isolated_config_manager):
    naive_timestamp = "2024-01-01T12:00:00"
    isolated_config_manager.EVENTS_FILE.write_text(
        json.dumps([
            {
                "timestamp": naive_timestamp,
                "container_id": "test-container",
                "container_name": "test-container",
                "event_type": "restart",
                "restart_count": 1,
                "status": "success",
                "message": "legacy event",
            }
        ])
    )
    isolated_config_manager._event_log = isolated_config_manager._load_events()

    events = asyncio.run(get_events())

    assert events[0]["timestamp"] == naive_timestamp
