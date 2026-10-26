"""
Unit tests for the autouse ``mock_notification_manager`` fixture.

The fixture must stop notifications for every module that imports the shared manager, not
only the monitoring engine. A module the fixture missed would call the real manager while
its tests still passed, so each importer is checked here.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.api import state
from app.config.config_manager import AutoHealEvent
from app.main import notification_manager as main_notification_manager
from app.monitor.monitoring_engine import notification_manager as engine_notification_manager
from app.notifications.notification_manager import notification_manager


def test_every_importer_shares_the_patched_manager(mock_notification_manager):
    for module_manager in (engine_notification_manager, state.notification_manager):
        assert module_manager is notification_manager
        assert module_manager.send_event_notification is (
            mock_notification_manager.send_event_notification
        )
    assert main_notification_manager is notification_manager
    assert isinstance(notification_manager.send_event_notification, AsyncMock)


@pytest.mark.asyncio
async def test_an_event_sent_through_any_importer_is_recorded_not_delivered(
    mock_notification_manager,
):
    event = AutoHealEvent(
        timestamp=datetime.now(UTC),
        container_id="a" * 64,
        container_name="web",
        event_type="restart",
        restart_count=1,
        status="success",
        message="restarted",
    )

    await engine_notification_manager.send_event_notification(event)
    await state.notification_manager.send_event_notification(event)

    assert mock_notification_manager.send_event_notification.await_count == 2


def test_the_fixture_applies_without_being_requested():
    """The fixture is autouse, and each test starts with no recorded sends."""
    assert isinstance(notification_manager.send_event_notification, AsyncMock)
    assert notification_manager.send_event_notification.await_count == 0
