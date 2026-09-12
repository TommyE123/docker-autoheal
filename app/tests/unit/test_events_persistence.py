"""
Unit tests for the event log persisted by ConfigManager: adding events,
reading them back, and clearing the log.

Converted from the legacy `app/tests/test_clear_events.py` demo script, which
exercised the real (un-isolated) `config_manager` singleton and printed its
findings instead of asserting on them. This version uses the
`isolated_config_manager` fixture from `conftest.py` so it never touches the
real `/data` directory.
"""

from datetime import datetime, timezone

from app.config.config_manager import AutoHealEvent


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
