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
from app.notifications.notification_manager import NotificationManager, NotificationPriority


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


# The remaining channels each build a distinct payload/URL/headers shape, so a
# bug in one wouldn't be caught by testing another - worth a case each, not
# just for the sake of it.


@pytest.mark.asyncio
async def test_send_discord_posts_an_embed(manager):
    service = NotificationService(name="Discord", type="discord", url="https://discord.invalid/hook")

    await manager._send_discord(service, "Title", "**bold** text", _make_event(), NotificationPriority.HIGH)

    call = manager._session.calls[0]
    assert call["url"] == "https://discord.invalid/hook"
    embed = call["json"]["embeds"][0]
    assert embed["title"] == "Title"
    assert embed["description"] == "bold text"  # ** markers stripped
    assert embed["color"] == 0xF39C12  # HIGH priority colour


@pytest.mark.asyncio
async def test_send_discord_skipped_without_a_url(manager):
    service = NotificationService(name="Discord", type="discord")

    await manager._send_discord(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)

    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_send_discord_error_response_is_logged_not_raised(manager):
    manager._session = _FakeSession(status=500)
    service = NotificationService(name="Discord", type="discord", url="https://discord.invalid/hook")

    await manager._send_discord(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)  # must not raise


@pytest.mark.asyncio
async def test_send_slack_posts_blocks(manager):
    service = NotificationService(name="Slack", type="slack", url="https://slack.invalid/hook")

    await manager._send_slack(service, "Title", "**bold**", _make_event(), NotificationPriority.NORMAL)

    call = manager._session.calls[0]
    assert call["json"]["text"] == "Title"
    assert call["json"]["blocks"][1]["text"]["text"] == "*bold*"  # ** -> * for Slack markdown


@pytest.mark.asyncio
async def test_send_telegram_posts_to_the_bot_api(manager):
    service = NotificationService(name="Telegram", type="telegram", bot_token="tok", chat_id="123")

    await manager._send_telegram(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)

    call = manager._session.calls[0]
    assert call["url"] == "https://api.telegram.org/bottok/sendMessage"
    assert call["json"]["chat_id"] == "123"
    assert call["json"]["text"] == "*Title*\n\nmsg"


@pytest.mark.asyncio
async def test_send_telegram_skipped_without_credentials(manager):
    service = NotificationService(name="Telegram", type="telegram")

    await manager._send_telegram(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)

    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_send_telegram_request_failure_is_logged_not_raised(manager):
    def _raise(*args, **kwargs):
        raise TimeoutError("no response")

    manager._session.post = _raise
    service = NotificationService(name="Telegram", type="telegram", bot_token="tok", chat_id="123")

    await manager._send_telegram(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)  # must not raise


@pytest.mark.asyncio
async def test_send_ntfy_posts_with_priority_and_basic_auth(manager):
    service = NotificationService(
        name="Ntfy", type="ntfy", topic="alerts", username="user", password="pass"
    )

    await manager._send_ntfy(service, "Title", "**msg**", _make_event(), NotificationPriority.CRITICAL)

    call = manager._session.calls[0]
    assert call["url"] == "https://ntfy.sh/alerts"
    assert call["headers"]["Priority"] == "5"
    assert call["headers"]["Authorization"].startswith("Basic ")
    assert call["data"] == "msg"


@pytest.mark.asyncio
async def test_send_ntfy_skipped_without_a_topic(manager):
    service = NotificationService(name="Ntfy", type="ntfy")

    await manager._send_ntfy(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)

    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_send_gotify_posts_with_priority(manager):
    service = NotificationService(
        name="Gotify", type="gotify", server_url="https://gotify.invalid", app_token="tok"
    )

    await manager._send_gotify(service, "Title", "**msg**", _make_event(), NotificationPriority.LOW)

    call = manager._session.calls[0]
    assert call["url"] == "https://gotify.invalid/message"
    assert call["headers"]["X-Gotify-Key"] == "tok"
    assert call["json"]["priority"] == 2


@pytest.mark.asyncio
async def test_send_gotify_skipped_without_credentials(manager):
    service = NotificationService(name="Gotify", type="gotify")

    await manager._send_gotify(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)

    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_send_pushover_posts_with_priority(manager):
    service = NotificationService(name="Pushover", type="pushover", user_key="user", api_token="tok")

    await manager._send_pushover(service, "Title", "**msg**", _make_event(), NotificationPriority.CRITICAL)

    call = manager._session.calls[0]
    assert call["url"] == "https://api.pushover.net/1/messages.json"
    assert call["data"]["priority"] == 2
    assert call["data"]["token"] == "tok"


@pytest.mark.asyncio
async def test_send_pushover_skipped_without_credentials(manager):
    service = NotificationService(name="Pushover", type="pushover")

    await manager._send_pushover(service, "Title", "msg", _make_event(), NotificationPriority.NORMAL)

    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_webhook_error_response_is_logged_not_raised(isolated_config_manager, manager):
    manager._session = _FakeSession(status=500)
    _configure_webhook(isolated_config_manager, event_filters=["restart"])

    await manager._process_notification(_make_event("restart"))  # must not raise


@pytest.mark.asyncio
async def test_webhook_request_failure_is_logged_not_raised(isolated_config_manager, manager):
    def _raise(*args, **kwargs):
        raise TimeoutError("no response")

    manager._session.post = _raise
    _configure_webhook(isolated_config_manager, event_filters=["restart"])

    await manager._process_notification(_make_event("restart"))  # must not raise


@pytest.mark.parametrize(
    "event_type,expected_priority,expected_title",
    [
        ("quarantine", NotificationPriority.HIGH, "Container Quarantined"),
        ("unquarantine", NotificationPriority.NORMAL, "Container Unquarantined"),
        ("health_check_failed", NotificationPriority.HIGH, "Health Check Failed"),
        ("auto_monitor", NotificationPriority.LOW, "Container Auto-Monitored"),
        ("some_new_event_type", NotificationPriority.NORMAL, " Some New Event Type"),
    ],
)
def test_format_notification_maps_event_type_to_priority_and_title(
    manager, event_type, expected_priority, expected_title
):
    title, message, priority = manager._format_notification(_make_event(event_type))

    assert priority == expected_priority
    assert title == expected_title
    assert event_type in message


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle():
    manager = NotificationManager()
    assert manager._running is False

    await manager.start()
    try:
        assert manager._running is True
        assert manager._session is not None
    finally:
        await manager.stop()

    assert manager._running is False
    assert manager._session is None


@pytest.mark.asyncio
async def test_start_is_idempotent():
    manager = NotificationManager()
    await manager.start()
    try:
        await manager.start()  # should log and return, not start a second worker
        assert manager._running is True
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_without_start_is_a_noop():
    await NotificationManager().stop()  # must not raise


@pytest.mark.asyncio
async def test_process_notification_dispatches_by_service_type(isolated_config_manager, manager):
    config = isolated_config_manager.get_config()
    config.notifications.enabled = True
    config.notifications.services = [
        NotificationService(name="D", type="discord", url="https://discord.invalid/hook"),
        NotificationService(name="S", type="slack", url="https://slack.invalid/hook"),
        NotificationService(name="U", type="unsupported-type", url="https://example.invalid"),
    ]
    isolated_config_manager.update_config(config)

    await manager._process_notification(_make_event())

    urls = {call["url"] for call in manager._session.calls}
    assert urls == {"https://discord.invalid/hook", "https://slack.invalid/hook"}
