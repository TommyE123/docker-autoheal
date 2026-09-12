"""
Unit tests for NotificationManager: event filtering and webhook delivery.

Converted from the root-level `test_notifications.py` manual script, which
sent a real webhook to https://httpbin.org/post (an external network
dependency) and printed its findings instead of asserting on them. This
version fakes the aiohttp session so delivery is verified without any network
access, and drives `_process_notification` directly instead of sleeping while
the background worker drains the queue.
"""

import asyncio
import base64
import logging
from datetime import datetime, timezone

import pytest

from app.config.config_manager import AutoHealEvent, NotificationService
from app.notifications.notification_manager import (
    NotificationManager,
    NotificationPriority,
)


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


def _configure_service(isolated_config_manager, service, enabled=True):
    """Configure the global config with a single (arbitrary-type) service."""
    config = isolated_config_manager.get_config()
    config.notifications.enabled = enabled
    config.notifications.services = [service]
    isolated_config_manager.update_config(config)
    return config


class _FakeAiohttpSession(_FakeSession):
    """Stands in for aiohttp.ClientSession for start()/stop() lifecycle tests."""

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.closed = False

    async def close(self):
        self.closed = True


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


def test_format_notification_maps_event_type_to_title_and_priority(manager):
    title, _message, priority = manager._format_notification(_make_event("unquarantine"))
    assert title == "Container Unquarantined"
    assert priority == NotificationPriority.NORMAL

    title, _message, priority = manager._format_notification(_make_event("unknown_event"))
    assert title == " Unknown Event"
    assert priority == NotificationPriority.NORMAL


@pytest.mark.asyncio
async def test_send_discord_builds_embed_payload(isolated_config_manager, manager):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Discord", type="discord", enabled=True, url="https://example.invalid/discord"
        ),
    )

    await manager._process_notification(_make_event("quarantine"))

    call = manager._session.calls[0]
    assert call["url"] == "https://example.invalid/discord"
    embed = call["json"]["embeds"][0]
    assert embed["title"] == "Container Quarantined"
    assert "**" not in embed["description"]
    assert embed["color"] == 0xF39C12  # HIGH priority -> orange
    assert call["json"]["username"] == "Docker Auto-Heal"


@pytest.mark.asyncio
async def test_send_slack_builds_blocks_payload(isolated_config_manager, manager):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Slack", type="slack", enabled=True, url="https://example.invalid/slack"
        ),
    )

    await manager._process_notification(_make_event("restart"))

    call = manager._session.calls[0]
    payload = call["json"]
    assert payload["text"] == "Container Restarted"
    section_text = payload["blocks"][1]["text"]["text"]
    assert "*Container:*" in section_text
    assert "**" not in section_text


@pytest.mark.asyncio
async def test_send_telegram_builds_message_and_url(isolated_config_manager, manager):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Telegram", type="telegram", enabled=True, bot_token="abc123", chat_id="999"
        ),
    )

    await manager._process_notification(_make_event("restart"))

    call = manager._session.calls[0]
    assert call["url"] == "https://api.telegram.org/botabc123/sendMessage"
    payload = call["json"]
    assert payload["chat_id"] == "999"
    assert payload["text"].startswith("*Container Restarted*")


@pytest.mark.asyncio
async def test_send_telegram_skips_when_not_configured(isolated_config_manager, manager):
    _configure_service(
        isolated_config_manager,
        NotificationService(name="Telegram", type="telegram", enabled=True),
    )

    await manager._process_notification(_make_event("restart"))

    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_send_ntfy_builds_headers_with_auth(isolated_config_manager, manager):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Ntfy",
            type="ntfy",
            enabled=True,
            topic="alerts",
            server_url="https://ntfy.example.invalid",
            username="user",
            password="pass",
        ),
    )

    await manager._process_notification(_make_event("health_check_failed"))

    call = manager._session.calls[0]
    assert call["url"] == "https://ntfy.example.invalid/alerts"
    assert call["headers"]["Priority"] == "4"  # HIGH priority
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"user:pass").decode()
    assert "**" not in call["data"]


@pytest.mark.asyncio
async def test_send_gotify_builds_payload(isolated_config_manager, manager):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Gotify",
            type="gotify",
            enabled=True,
            server_url="https://gotify.example.invalid",
            app_token="tok123",
        ),
    )

    await manager._process_notification(_make_event("auto_monitor"))

    call = manager._session.calls[0]
    assert call["url"] == "https://gotify.example.invalid/message"
    assert call["headers"]["X-Gotify-Key"] == "tok123"
    assert call["json"]["priority"] == 2  # LOW priority


@pytest.mark.asyncio
async def test_send_pushover_builds_form_payload(isolated_config_manager, manager):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Pushover", type="pushover", enabled=True, user_key="userkey", api_token="apitoken"
        ),
    )

    await manager._process_notification(_make_event("quarantine"))

    call = manager._session.calls[0]
    assert call["url"] == "https://api.pushover.net/1/messages.json"
    assert call["data"]["user"] == "userkey"
    assert call["data"]["token"] == "apitoken"
    assert call["data"]["priority"] == 1  # HIGH priority


@pytest.mark.asyncio
async def test_webhook_error_status_is_logged_not_raised(caplog, isolated_config_manager, manager):
    manager._session = _FakeSession(status=500)
    _configure_webhook(isolated_config_manager)

    with caplog.at_level(logging.ERROR):
        await manager._process_notification(_make_event("restart"))

    assert any("Webhook failed with status 500" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_webhook_exception_is_caught_and_logged(caplog, isolated_config_manager, manager):
    class _RaisingSession:
        def post(self, *args, **kwargs):
            raise ConnectionError("network unreachable")

    manager._session = _RaisingSession()
    _configure_webhook(isolated_config_manager)

    with caplog.at_level(logging.ERROR):
        await manager._process_notification(_make_event("restart"))

    assert any("Failed to send webhook notification" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_process_notification_dispatches_only_to_enabled_known_services(
    caplog, isolated_config_manager, manager
):
    config = isolated_config_manager.get_config()
    config.notifications.enabled = True
    config.notifications.services = [
        NotificationService(
            name="Webhook", type="webhook", enabled=True, url="https://example.invalid/webhook"
        ),
        NotificationService(
            name="Disabled", type="webhook", enabled=False, url="https://example.invalid/off"
        ),
        NotificationService(name="Unknown", type="carrier-pigeon", enabled=True),
    ]
    isolated_config_manager.update_config(config)

    with caplog.at_level(logging.WARNING):
        await manager._process_notification(_make_event("restart"))

    assert len(manager._session.calls) == 1
    assert manager._session.calls[0]["url"] == "https://example.invalid/webhook"
    assert any("Unsupported notification type" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_test_notification_reports_failure_for_disabled_service(
    isolated_config_manager, manager
):
    config = _configure_webhook(isolated_config_manager)
    config.notifications.services[0].enabled = False
    isolated_config_manager.update_config(config)

    result = await manager.test_notification("Test Webhook")

    assert result == {"success": False, "message": "Service 'Test Webhook' is disabled"}
    assert manager._session.calls == []


@pytest.mark.asyncio
async def test_test_notification_reports_failure_for_unsupported_type(
    isolated_config_manager, manager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(name="Carrier Pigeon", type="carrier-pigeon", enabled=True),
    )

    result = await manager.test_notification("Carrier Pigeon")

    assert result == {"success": False, "message": "Unsupported notification type: carrier-pigeon"}


@pytest.mark.asyncio
async def test_notification_worker_recovers_after_processing_error(
    monkeypatch, isolated_config_manager, manager
):
    """A failure processing one queued event must not stop the worker loop."""
    _configure_webhook(isolated_config_manager)

    calls: list[AutoHealEvent] = []
    real_process = manager._process_notification

    async def flaky_process(event):
        calls.append(event)
        if len(calls) == 1:
            raise RuntimeError("boom")
        await real_process(event)

    monkeypatch.setattr(manager, "_process_notification", flaky_process)

    manager._running = True
    await manager._notification_queue.put(_make_event("restart"))
    await manager._notification_queue.put(_make_event("restart"))
    worker = asyncio.create_task(manager._notification_worker())

    for _ in range(200):
        if len(manager._session.calls) >= 1:
            break
        await asyncio.sleep(0.01)

    manager._running = False
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    assert len(calls) == 2
    assert len(manager._session.calls) == 1


@pytest.mark.asyncio
async def test_start_stop_lifecycle_delivers_queued_notification(
    monkeypatch, isolated_config_manager
):
    monkeypatch.setattr(
        "app.notifications.notification_manager.aiohttp.ClientSession", _FakeAiohttpSession
    )
    _configure_webhook(isolated_config_manager)

    instance = NotificationManager()
    await instance.start()
    assert instance._running is True
    assert instance._worker_task is not None
    assert instance._session is not None

    await instance.send_event_notification(_make_event("restart"))

    for _ in range(200):
        if instance._session.calls:
            break
        await asyncio.sleep(0.01)

    assert len(instance._session.calls) == 1

    session = instance._session
    await instance.stop()
    assert instance._running is False
    assert session.closed is True
    assert instance._session is None


@pytest.mark.asyncio
async def test_start_when_already_running_is_a_noop(monkeypatch, isolated_config_manager):
    monkeypatch.setattr(
        "app.notifications.notification_manager.aiohttp.ClientSession", _FakeAiohttpSession
    )

    instance = NotificationManager()
    await instance.start()
    session_first = instance._session
    task_first = instance._worker_task

    await instance.start()

    assert instance._session is session_first
    assert instance._worker_task is task_first

    await instance.stop()


@pytest.mark.asyncio
async def test_stop_when_not_running_is_a_noop():
    instance = NotificationManager()

    await instance.stop()

    assert instance._running is False
    assert instance._session is None
