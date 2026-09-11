"""
Unit tests for NotificationManager: event filtering and webhook delivery.

Converted from the root-level `test_notifications.py` manual script, which
sent a real webhook to https://httpbin.org/post (an external network
dependency) and printed its findings instead of asserting on them. This
version fakes the aiohttp session so delivery is verified without any network
access, and drives `_process_notification` directly instead of sleeping while
the background worker drains the queue.
"""

from datetime import datetime, timezone

import pytest

from app.config.config_manager import AutoHealEvent, NotificationService
from app.notifications.notification_manager import NotificationManager


class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status

    async def text(self) -> str:
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self.status)


@pytest.fixture
def manager() -> NotificationManager:
    """A standalone NotificationManager wired to a fake HTTP session."""
    instance = NotificationManager()
    instance._session = _FakeSession()
    return instance


def _make_event(event_type: str = "restart") -> AutoHealEvent:
    return AutoHealEvent(
        timestamp=datetime.now(timezone.utc),
        container_id="test-container-123",
        container_name="nginx-test",
        event_type=event_type,
        restart_count=1,
        status="success",
        message=f"Test {event_type} event",
    )


def _configure_webhook(isolated_config_manager, event_filters=None, enabled=True):
    config = isolated_config_manager.get_config()
    config.notifications.enabled = enabled
    config.notifications.services = [
        NotificationService(
            name="Test Webhook",
            type="webhook",
            enabled=True,
            url="https://example.invalid/webhook",
        )
    ]
    config.notifications.event_filters = event_filters if event_filters is not None else []
    isolated_config_manager.update_config(config)
    return config


def test_event_filters_restrict_which_events_notify(isolated_config_manager, manager):
    _configure_webhook(isolated_config_manager, event_filters=["restart", "quarantine"])

    assert manager._should_notify_for_event(_make_event("restart")) is True
    assert manager._should_notify_for_event(_make_event("quarantine")) is True
    assert manager._should_notify_for_event(_make_event("auto_monitor")) is False


def test_empty_event_filters_notify_for_every_event(isolated_config_manager, manager):
    _configure_webhook(isolated_config_manager, event_filters=[])

    assert manager._should_notify_for_event(_make_event("auto_monitor")) is True


@pytest.mark.asyncio
async def test_send_event_notification_queues_and_delivers_to_webhook(
    isolated_config_manager, manager
):
    _configure_webhook(isolated_config_manager, event_filters=["restart"])
    event = _make_event("restart")

    await manager.send_event_notification(event)
    assert manager._notification_queue.qsize() == 1

    queued_event = await manager._notification_queue.get()
    await manager._process_notification(queued_event)

    assert len(manager._session.calls) == 1
    call = manager._session.calls[0]
    assert call["url"] == "https://example.invalid/webhook"
    assert call["json"]["event"]["container_name"] == "nginx-test"
    assert call["json"]["event"]["type"] == "restart"


@pytest.mark.asyncio
async def test_send_event_notification_skips_filtered_out_event_types(
    isolated_config_manager, manager
):
    _configure_webhook(isolated_config_manager, event_filters=["restart", "quarantine"])

    await manager.send_event_notification(_make_event("auto_monitor"))

    assert manager._notification_queue.qsize() == 0


@pytest.mark.asyncio
async def test_send_event_notification_noop_when_notifications_disabled(
    isolated_config_manager, manager
):
    _configure_webhook(isolated_config_manager, event_filters=["restart"], enabled=False)

    await manager.send_event_notification(_make_event("restart"))

    assert manager._notification_queue.qsize() == 0


@pytest.mark.asyncio
async def test_disabled_service_is_not_sent_to(isolated_config_manager, manager):
    config = _configure_webhook(isolated_config_manager, event_filters=["restart"])
    config.notifications.services[0].enabled = False
    isolated_config_manager.update_config(config)

    await manager._process_notification(_make_event("restart"))

    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_test_notification_reports_success_and_sends_a_test_payload(
    isolated_config_manager, manager
):
    _configure_webhook(isolated_config_manager)

    result = await manager.test_notification("Test Webhook")

    assert result == {"success": True, "message": "Test notification sent successfully"}
    assert len(manager._session.calls) == 1
    assert manager._session.calls[0]["json"]["event"]["type"] == "test"


@pytest.mark.asyncio
async def test_test_notification_reports_failure_for_unknown_service(
    isolated_config_manager, manager
):
    _configure_webhook(isolated_config_manager)

    result = await manager.test_notification("Nonexistent Service")

    assert result == {"success": False, "message": "Service 'Nonexistent Service' not found"}
    assert manager._session.calls == []
