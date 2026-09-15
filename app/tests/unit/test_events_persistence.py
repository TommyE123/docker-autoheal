"""
Unit tests for the event log persisted by ConfigManager: adding events,
reading them back, and clearing the log.

Converted from the legacy `app/tests/test_clear_events.py` demo script, which
exercised the real (un-isolated) `config_manager` singleton and printed its
findings instead of asserting on them. This version uses the
`isolated_config_manager` fixture from `conftest.py` so it never touches the
real `/data` directory.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.config.config_manager import AutoHealEvent, LegacyAutoHealEvent


def _make_event(index: int) -> AutoHealEvent:
    return AutoHealEvent(
        timestamp=datetime.now(timezone.utc),
        container_id=f"test_container_{index}",
        container_name=f"test-container-{index}",
        event_type="restart",
        restart_count=index + 1,
        status="success",
        message=f"Test event {index + 1}",
    )


def _event_payload(index: int, timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "container_id": f"test_container_{index}",
        "container_name": f"test-container-{index}",
        "event_type": "restart",
        "restart_count": index + 1,
        "status": "success",
        "message": f"Test event {index + 1}",
    }


def test_add_event_appends_to_the_log(isolated_config_manager):
    for i in range(5):
        isolated_config_manager.add_event(_make_event(i))

    events = isolated_config_manager.get_events()
    assert len(events) == 5
    assert [e.container_name for e in events] == [f"test-container-{i}" for i in range(5)]


def test_clear_events_empties_the_log(isolated_config_manager):
    for i in range(5):
        isolated_config_manager.add_event(_make_event(i))
    assert len(isolated_config_manager.get_events()) == 5

    isolated_config_manager.clear_events()

    assert isolated_config_manager.get_events() == []


def test_utc_aware_timestamp_is_accepted():
    event = _make_event(0)

    assert event.timestamp.utcoffset() == timedelta(0)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        AutoHealEvent(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            container_id="test-container",
            container_name="test-container",
            event_type="restart",
            restart_count=1,
            status="success",
            message="naive timestamp",
        )


def test_non_utc_aware_timestamp_is_rejected():
    with pytest.raises(ValidationError, match="timestamp must be UTC"):
        AutoHealEvent(
            timestamp=datetime(
                2024, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=1))
            ),
            container_id="test-container",
            container_name="test-container",
            event_type="restart",
            restart_count=1,
            status="success",
            message="non-UTC timestamp",
        )


def test_utc_event_saves_and_reloads(isolated_config_manager):
    event = _make_event(0)
    isolated_config_manager.add_event(event)

    reloaded_events = isolated_config_manager._load_events()

    assert reloaded_events == [event]


def test_historical_naive_event_is_preserved_without_becoming_current_event(isolated_config_manager):
    naive_timestamp = "2024-01-01T12:00:00"
    isolated_config_manager.EVENTS_FILE.write_text(
        json.dumps([_event_payload(0, naive_timestamp)])
    )

    events = isolated_config_manager._load_events()

    assert len(events) == 1
    assert isinstance(events[0], LegacyAutoHealEvent)
    assert events[0].timestamp == naive_timestamp


@pytest.mark.parametrize(
    ("timestamp", "error"),
    [
        ("not-an-iso-timestamp", "legacy timestamp must be ISO 8601"),
        ("2024-01-01T12:00:00+00:00", "UTC timestamps must use AutoHealEvent"),
    ],
)
def test_legacy_event_rejects_invalid_or_current_utc_timestamps(timestamp, error):
    """Legacy records must be ISO timestamps that cannot use the current model."""
    with pytest.raises(ValidationError, match=error):
        LegacyAutoHealEvent(**_event_payload(0, timestamp))


def test_loading_events_skips_invalid_record_and_retains_valid_history(
    isolated_config_manager, caplog
):
    """One corrupt record must not discard current or valid legacy history."""
    isolated_config_manager.EVENTS_FILE.write_text(
        json.dumps(
            [
                _event_payload(0, "2024-01-01T12:00:00+00:00"),
                _event_payload(1, "2024-01-01T12:00:00"),
                _event_payload(2, "not-an-iso-timestamp"),
            ]
        )
    )

    events = isolated_config_manager._load_events()

    assert len(events) == 2
    assert [event.container_id for event in events] == [
        "test_container_0",
        "test_container_1",
    ]
    assert isinstance(events[0], AutoHealEvent)
    assert isinstance(events[1], LegacyAutoHealEvent)
    assert "Skipping invalid event 2 from disk" in caplog.text


def test_mixed_historical_and_utc_events_are_preserved_when_saved(isolated_config_manager):
    naive_timestamp = "2024-01-01T12:00:00"
    utc_timestamp = "2024-01-02T12:00:00+00:00"
    isolated_config_manager.EVENTS_FILE.write_text(
        json.dumps([
            _event_payload(0, naive_timestamp),
            _event_payload(1, utc_timestamp),
        ])
    )

    isolated_config_manager._event_log = isolated_config_manager._load_events()
    isolated_config_manager.add_event(_make_event(2))

    persisted_events = json.loads(isolated_config_manager.EVENTS_FILE.read_text())
    reloaded_events = isolated_config_manager._load_events()

    assert persisted_events[0]["timestamp"] == naive_timestamp
    persisted_utc_timestamp = datetime.fromisoformat(
        persisted_events[1]["timestamp"].replace("Z", "+00:00")
    )
    assert persisted_utc_timestamp.utcoffset() == timedelta(0)
    assert len(reloaded_events) == 3
    assert isinstance(reloaded_events[0], LegacyAutoHealEvent)
    assert reloaded_events[0].timestamp == naive_timestamp
    assert isinstance(reloaded_events[1], AutoHealEvent)
    assert isinstance(reloaded_events[2], AutoHealEvent)
