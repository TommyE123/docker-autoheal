"""
Unit tests for the events API endpoints (GET/DELETE /api/events).

Calls the endpoint functions directly rather than over HTTP - config_manager
is isolated per test (see conftest.py) and neither endpoint touches Docker,
so a real HTTP round-trip against a running service would add nothing and
risks clearing a real installation's event history.
"""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api.routes.events import clear_events, get_events
from app.config.config_manager import AutoHealEvent
from app.tests.unit.test_api_routing import _request


def test_delete_events_clears_a_seeded_event(isolated_config_manager):
    isolated_config_manager.add_event(
        AutoHealEvent(
            timestamp=datetime.now(UTC),
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
    timestamp = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
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


def test_get_events_failure_becomes_http_500(isolated_config_manager, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("event log unreadable")

    monkeypatch.setattr(isolated_config_manager, "get_events", explode)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_events())

    assert exc_info.value.status_code == 500
    assert "event log unreadable" in str(exc_info.value.detail)


def test_clear_events_failure_becomes_http_500(isolated_config_manager, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("event log locked")

    monkeypatch.setattr(isolated_config_manager, "clear_events", explode)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(clear_events())

    assert exc_info.value.status_code == 500
    assert "event log locked" in str(exc_info.value.detail)


def _seed(manager, *specs):
    """Add one event per ``(container_name, event_type)`` pair, oldest first."""
    for index, (name, event_type) in enumerate(specs):
        manager.add_event(
            AutoHealEvent(
                timestamp=datetime(2024, 1, 1, 12, index, tzinfo=UTC),
                container_id=f"id-{index}",
                container_name=name,
                event_type=event_type,
                restart_count=index,
                status="success",
                message=f"event {index}",
            )
        )


def test_events_can_be_filtered_by_event_type(isolated_config_manager):
    _seed(
        isolated_config_manager,
        ("web", "restart"),
        ("web", "quarantine"),
        ("db", "restart"),
    )

    events = asyncio.run(get_events(event_type="restart"))

    assert [e["container_name"] for e in events] == ["web", "db"]


def test_events_can_be_filtered_by_container_substring_ignoring_case(isolated_config_manager):
    _seed(
        isolated_config_manager,
        ("Web (stack_web)", "restart"),
        ("db (stack_db)", "restart"),
    )

    events = asyncio.run(get_events(container="WEB"))

    assert [e["container_name"] for e in events] == ["Web (stack_web)"]


def test_filters_combine(isolated_config_manager):
    _seed(
        isolated_config_manager,
        ("web", "restart"),
        ("web", "quarantine"),
        ("db", "quarantine"),
    )

    events = asyncio.run(get_events(event_type="quarantine", container="web"))

    assert [(e["container_name"], e["event_type"]) for e in events] == [("web", "quarantine")]


def test_empty_event_type_matches_only_events_with_an_empty_type(isolated_config_manager):
    _seed(
        isolated_config_manager,
        ("web", "restart"),
        ("cache", ""),
        ("db", "quarantine"),
    )

    events = asyncio.run(get_events(event_type=""))

    assert [e["container_name"] for e in events] == ["cache"]


def test_empty_container_matches_every_event(isolated_config_manager):
    _seed(isolated_config_manager, ("web", "restart"), ("db", "quarantine"))

    events = asyncio.run(get_events(container=""))

    assert [e["container_name"] for e in events] == ["web", "db"]


def test_limit_applies_after_filtering_and_keeps_the_most_recent(isolated_config_manager):
    _seed(
        isolated_config_manager,
        ("web", "restart"),
        ("web", "restart"),
        ("db", "quarantine"),
        ("web", "restart"),
    )

    events = asyncio.run(get_events(limit=2, event_type="restart"))

    assert [e["restart_count"] for e in events] == [1, 3]


def test_no_filters_returns_the_most_recent_events_up_to_limit(isolated_config_manager):
    _seed(isolated_config_manager, ("a", "restart"), ("b", "restart"), ("c", "restart"))

    events = asyncio.run(get_events(limit=2))

    assert [e["container_name"] for e in events] == ["b", "c"]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["0", "-1", "abc"])
async def test_invalid_limit_is_rejected_with_422(isolated_config_manager, limit):
    _seed(isolated_config_manager, ("web", "restart"))

    status, _, _ = await _request("GET", "/api/events", query=f"limit={limit}")

    assert status == 422


@pytest.mark.asyncio
async def test_filters_are_honoured_over_http(isolated_config_manager):
    _seed(isolated_config_manager, ("web", "restart"), ("db", "quarantine"))

    status, body, _ = await _request("GET", "/api/events", query="event_type=quarantine")

    assert status == 200
    assert [e["container_name"] for e in json.loads(body)] == ["db"]
