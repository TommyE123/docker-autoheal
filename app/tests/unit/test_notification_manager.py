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
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.config.config_manager import AutoHealEvent, NotificationService
from app.notifications.notification_manager import (
    NotificationManager,
    NotificationPriority,
)

_ACCEPTED_BODY = {"ok": True, "status": 1}


class _FakeResponse:
    """Fake response; ``body`` may be an Exception, which ``json()`` raises.

    ``method`` is the method of the final request, i.e. after any redirects.
    """

    def __init__(self, status: int = 200, body: Any = _ACCEPTED_BODY, method: str = "POST"):
        self.status = status
        self._body = body
        self.method = method

    async def text(self) -> str:
        return ""

    async def json(self, content_type=None) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    """Fake HTTP session satisfying the manager's session protocol.

    ``calls`` and ``closed`` are fake-only; use ``fake_session()`` to read them
    from a manager so they are typed on this class, not on the real session.
    """

    def __init__(self, status: int = 200, *, body: Any = _ACCEPTED_BODY, method: str = "POST"):
        self.status = status
        self.body = body
        self.method = method
        self.calls: list[dict] = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self.status, self.body, self.method)

    async def close(self) -> None:
        self.closed = True


def fake_session(manager: NotificationManager) -> _FakeSession:
    """Return the manager's session, narrowed to the fake installed by tests."""
    session = manager._session
    assert isinstance(session, _FakeSession)
    return session


@pytest.fixture
def manager() -> NotificationManager:
    """A standalone NotificationManager wired to a fake HTTP session."""
    instance = NotificationManager()
    instance._session = _FakeSession()
    return instance


def _make_event(event_type: str = "restart") -> AutoHealEvent:
    return AutoHealEvent(
        timestamp=datetime.now(UTC),
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


def test_event_filters_restrict_which_events_notify(
    isolated_config_manager, manager: NotificationManager
):
    _configure_webhook(isolated_config_manager, event_filters=["restart", "quarantine"])

    assert manager._should_notify_for_event(_make_event("restart")) is True
    assert manager._should_notify_for_event(_make_event("quarantine")) is True
    assert manager._should_notify_for_event(_make_event("auto_monitor")) is False


def test_empty_event_filters_notify_for_every_event(
    isolated_config_manager, manager: NotificationManager
):
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

    assert len(fake_session(manager).calls) == 1
    call = fake_session(manager).calls[0]
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
async def test_disabled_service_is_not_sent_to(
    isolated_config_manager, manager: NotificationManager
):
    config = _configure_webhook(isolated_config_manager, event_filters=["restart"])
    config.notifications.services[0].enabled = False
    isolated_config_manager.update_config(config)

    await manager._process_notification(_make_event("restart"))

    assert fake_session(manager).calls == []


@pytest.mark.asyncio
async def test_test_notification_reports_success_and_sends_a_test_payload(
    isolated_config_manager, manager
):
    _configure_webhook(isolated_config_manager)

    result = await manager.test_notification("Test Webhook")

    assert result == {"success": True, "message": "Test notification sent successfully"}
    assert len(fake_session(manager).calls) == 1
    assert fake_session(manager).calls[0]["json"]["event"]["type"] == "test"


@pytest.mark.asyncio
async def test_test_notification_reports_failure_for_unknown_service(
    isolated_config_manager, manager
):
    _configure_webhook(isolated_config_manager)

    result = await manager.test_notification("Nonexistent Service")

    assert result == {
        "success": False,
        "message": "Service 'Nonexistent Service' not found",
    }
    assert fake_session(manager).calls == []


@pytest.mark.asyncio
async def test_send_test_sends_unsaved_service_without_persisting(isolated_config_manager, manager):
    service = NotificationService(
        name="Unsaved", type="webhook", enabled=True, url="https://example.invalid/unsaved"
    )

    result = await manager.send_test(service)

    assert result == {"success": True, "message": "Test notification sent successfully"}
    assert fake_session(manager).calls[0]["json"]["event"]["type"] == "test"
    assert isolated_config_manager.get_config().notifications.services == []


@pytest.mark.asyncio
async def test_send_test_rejects_unsupported_type_without_sending(manager):
    service = NotificationService(
        name="Unsaved", type="bogus", enabled=True, url="https://example.invalid/secret"
    )

    result = await manager.send_test(service)

    assert result["success"] is False
    assert "secret" not in result["message"]
    assert fake_session(manager).calls == []


@pytest.mark.asyncio
async def test_send_test_reports_failure_when_delivery_fails(manager, monkeypatch):
    monkeypatch.setattr(manager, "_send_webhook", AsyncMock(return_value=False))
    service = NotificationService(
        name="Unsaved", type="webhook", enabled=True, url="https://example.invalid/unsaved"
    )

    result = await manager.send_test(service)

    assert result == {
        "success": False,
        "message": "Test notification to 'Unsaved' was not delivered, see logs",
    }


@pytest.mark.asyncio
async def test_send_test_does_not_echo_exception_text(manager, monkeypatch):
    monkeypatch.setattr(
        manager,
        "_send_webhook",
        AsyncMock(side_effect=RuntimeError("bad url https://example.invalid/secret-token")),
    )
    service = NotificationService(
        name="Unsaved", type="webhook", enabled=True, url="https://example.invalid/secret-token"
    )

    result = await manager.send_test(service)

    assert result["success"] is False
    assert "secret-token" not in result["message"]


def test_format_notification_maps_event_type_to_title_and_priority(
    manager: NotificationManager,
):
    title, _message, priority = manager._format_notification(_make_event("unquarantine"))
    assert title == "Container Unquarantined"
    assert priority == NotificationPriority.NORMAL

    title, _message, priority = manager._format_notification(_make_event("unknown_event"))
    assert title == "Unknown Event"
    assert priority == NotificationPriority.NORMAL


@pytest.mark.asyncio
async def test_send_discord_builds_embed_payload(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Discord",
            type="discord",
            enabled=True,
            url="https://example.invalid/discord",
        ),
    )

    await manager._process_notification(_make_event("quarantine"))

    call = fake_session(manager).calls[0]
    assert call["url"] == "https://example.invalid/discord"
    embed = call["json"]["embeds"][0]
    assert embed["title"] == "Container Quarantined"
    assert "**" not in embed["description"]
    assert embed["color"] == 0xF39C12  # HIGH priority -> orange
    assert call["json"]["username"] == "Docker Auto-Heal"


@pytest.mark.asyncio
async def test_send_slack_builds_blocks_payload(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Slack",
            type="slack",
            enabled=True,
            url="https://example.invalid/slack",
        ),
    )

    await manager._process_notification(_make_event("restart"))

    call = fake_session(manager).calls[0]
    payload = call["json"]
    assert payload["text"] == "Container Restarted"
    section_text = payload["blocks"][1]["text"]["text"]
    assert "*Container:*" in section_text
    assert "**" not in section_text


@pytest.mark.asyncio
async def test_send_telegram_builds_message_and_url(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Telegram",
            type="telegram",
            enabled=True,
            bot_token="abc123",
            chat_id="999",
        ),
    )

    await manager._process_notification(_make_event("restart"))

    call = fake_session(manager).calls[0]
    assert call["url"] == "https://api.telegram.org/botabc123/sendMessage"
    payload = call["json"]
    assert payload["chat_id"] == "999"
    assert payload["parse_mode"] == "HTML"
    assert payload["text"].startswith("<b>Container Restarted</b>")
    assert "<b>Container:</b>" in payload["text"]
    assert "**" not in payload["text"]


@pytest.mark.asyncio
async def test_send_telegram_escapes_special_characters(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Telegram",
            type="telegram",
            enabled=True,
            bot_token="abc123",
            chat_id="999",
        ),
    )
    event = _make_event("restart")
    event.container_name = "my_app_*db*<x>&y"
    event.message = "exit <1> & `crash` _x_"

    await manager._process_notification(event)

    text = fake_session(manager).calls[0]["json"]["text"]
    assert "<b>Container:</b> my_app_*db*&lt;x&gt;&amp;y" in text
    assert "exit &lt;1&gt; &amp; `crash` _x_" in text


@pytest.mark.asyncio
async def test_send_telegram_skips_when_not_configured(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(name="Telegram", type="telegram", enabled=True),
    )

    await manager._process_notification(_make_event("restart"))

    assert fake_session(manager).calls == []


@pytest.mark.asyncio
async def test_send_ntfy_builds_headers_with_auth(
    isolated_config_manager, manager: NotificationManager
):
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

    await manager._process_notification(_make_event("quarantine"))

    call = fake_session(manager).calls[0]
    assert call["url"] == "https://ntfy.example.invalid/alerts"
    assert call["headers"]["Priority"] == "4"  # HIGH priority
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"user:pass").decode()
    assert "**" not in call["data"]


@pytest.mark.asyncio
async def test_send_ntfy_without_credentials_sends_no_authorization(
    isolated_config_manager, manager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(name="Ntfy", type="ntfy", enabled=True, topic="alerts"),
    )

    await manager._process_notification(_make_event("health_check_failed"))

    assert "Authorization" not in fake_session(manager).calls[0]["headers"]


@pytest.mark.asyncio
async def test_send_ntfy_with_access_token_sends_bearer_header(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Ntfy",
            type="ntfy",
            enabled=True,
            topic="alerts",
            access_token="tk_secret",
        ),
    )

    await manager._process_notification(_make_event("health_check_failed"))

    assert fake_session(manager).calls[0]["headers"]["Authorization"] == "Bearer tk_secret"


@pytest.mark.asyncio
async def test_send_ntfy_access_token_takes_precedence_over_basic_auth(
    isolated_config_manager, manager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Ntfy",
            type="ntfy",
            enabled=True,
            topic="alerts",
            username="user",
            password="pass",
            access_token="tk_secret",
        ),
    )

    await manager._process_notification(_make_event("health_check_failed"))

    assert fake_session(manager).calls[0]["headers"]["Authorization"] == "Bearer tk_secret"


@pytest.mark.parametrize("status", [200, 500])
@pytest.mark.asyncio
async def test_send_ntfy_access_token_not_logged(
    caplog, isolated_config_manager, manager: NotificationManager, status
):
    manager._session = _FakeSession(status=status)
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Ntfy",
            type="ntfy",
            enabled=True,
            topic="alerts",
            access_token="tk_secret",
        ),
    )

    with caplog.at_level(logging.DEBUG):
        await manager._process_notification(_make_event("restart"))

    assert "tk_secret" not in caplog.text


@pytest.mark.asyncio
async def test_send_ntfy_access_token_not_logged_on_exception(
    caplog, isolated_config_manager, manager
):
    class _RaisingSession:
        def post(self, url, **kwargs):
            raise RuntimeError("connection refused")

    manager._session = _RaisingSession()
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Ntfy",
            type="ntfy",
            enabled=True,
            topic="alerts",
            access_token="tk_secret",
        ),
    )

    with caplog.at_level(logging.DEBUG):
        await manager._process_notification(_make_event("restart"))

    assert "Failed to send Ntfy notification" in caplog.text
    assert "tk_secret" not in caplog.text


@pytest.mark.asyncio
async def test_send_gotify_builds_payload(isolated_config_manager, manager: NotificationManager):
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

    call = fake_session(manager).calls[0]
    assert call["url"] == "https://gotify.example.invalid/message"
    assert call["headers"]["X-Gotify-Key"] == "tok123"
    assert call["json"]["priority"] == 2  # LOW priority


@pytest.mark.asyncio
async def test_send_pushover_builds_form_payload(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Pushover",
            type="pushover",
            enabled=True,
            user_key="userkey",
            api_token="apitoken",
        ),
    )

    await manager._process_notification(_make_event("quarantine"))

    call = fake_session(manager).calls[0]
    assert call["url"] == "https://api.pushover.net/1/messages.json"
    assert call["data"]["user"] == "userkey"
    assert call["data"]["token"] == "apitoken"
    assert call["data"]["priority"] == 1  # HIGH priority


@pytest.mark.asyncio
async def test_send_pushover_critical_priority_avoids_emergency(
    isolated_config_manager, manager: NotificationManager
):
    service = _SERVICES_BY_LABEL["Pushover"]
    _configure_service(isolated_config_manager, service)

    delivered = await manager._send_pushover(
        service, "title", "message", _make_event("restart"), NotificationPriority.CRITICAL
    )

    assert delivered is True
    data = fake_session(manager).calls[0]["data"]
    assert data["priority"] == 1
    assert data["priority"] != 2 or ("retry" in data and "expire" in data)


@pytest.mark.asyncio
async def test_webhook_error_status_is_logged_not_raised(
    caplog, isolated_config_manager, manager: NotificationManager
):
    manager._session = _FakeSession(status=500)
    _configure_webhook(isolated_config_manager)

    with caplog.at_level(logging.ERROR):
        await manager._process_notification(_make_event("restart"))

    assert any("Webhook failed with status 500" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_webhook_exception_is_caught_and_logged(
    caplog, isolated_config_manager, manager: NotificationManager
):
    class _RaisingSession:
        def post(self, *args, **kwargs):
            raise ConnectionError("network unreachable")

        async def close(self) -> None:
            pass

    manager._session = _RaisingSession()
    _configure_webhook(isolated_config_manager)

    with caplog.at_level(logging.ERROR):
        await manager._process_notification(_make_event("restart"))

    assert any("Failed to send webhook notification" in r.message for r in caplog.records)


_SERVICES_BY_LABEL = {
    "webhook": NotificationService(
        name="svc", type="webhook", enabled=True, url="https://example.invalid/hook"
    ),
    "Discord": NotificationService(
        name="svc", type="discord", enabled=True, url="https://example.invalid/hook"
    ),
    "Slack": NotificationService(
        name="svc", type="slack", enabled=True, url="https://example.invalid/hook"
    ),
    "Telegram": NotificationService(
        name="svc", type="telegram", enabled=True, bot_token="abc", chat_id="1"
    ),
    "Ntfy": NotificationService(name="svc", type="ntfy", enabled=True, topic="alerts"),
    "Gotify": NotificationService(
        name="svc",
        type="gotify",
        enabled=True,
        server_url="https://gotify.example.invalid",
        app_token="tok",
    ),
    "Pushover": NotificationService(
        name="svc", type="pushover", enabled=True, api_token="tok", user_key="usr"
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_SERVICES_BY_LABEL))
async def test_missing_session_is_logged_per_provider_and_does_not_raise(
    label, caplog, isolated_config_manager
):
    unstarted = NotificationManager()
    assert unstarted._session is None
    _configure_service(isolated_config_manager, _SERVICES_BY_LABEL[label])

    with caplog.at_level(logging.ERROR):
        await unstarted._process_notification(_make_event("restart"))

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert messages == [
        f"Failed to send {label} notification: notification manager has no active session"
    ]


@pytest.mark.asyncio
async def test_process_notification_dispatches_only_to_enabled_known_services(
    caplog, isolated_config_manager, manager
):
    config = isolated_config_manager.get_config()
    config.notifications.enabled = True
    config.notifications.services = [
        NotificationService(
            name="Webhook",
            type="webhook",
            enabled=True,
            url="https://example.invalid/webhook",
        ),
        NotificationService(
            name="Disabled",
            type="webhook",
            enabled=False,
            url="https://example.invalid/off",
        ),
        NotificationService(name="Unknown", type="carrier-pigeon", enabled=True),
    ]
    isolated_config_manager.update_config(config)

    with caplog.at_level(logging.WARNING):
        await manager._process_notification(_make_event("restart"))

    assert len(fake_session(manager).calls) == 1
    assert fake_session(manager).calls[0]["url"] == "https://example.invalid/webhook"
    assert "Unsupported notification type: carrier-pigeon" in [
        r.getMessage() for r in caplog.records
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_type",
    ["webhook", "discord", "slack", "telegram", "ntfy", "gotify", "pushover"],
)
async def test_process_notification_dispatches_each_type_to_its_sender(
    monkeypatch, isolated_config_manager, manager, service_type
):
    """Each notification type must route to its own ``_send_<type>`` method."""
    senders = {t: AsyncMock(return_value=True) for t in manager._senders()}
    for t, mock in senders.items():
        monkeypatch.setattr(manager, f"_send_{t}", mock)
    config = isolated_config_manager.get_config()
    config.notifications.enabled = True
    config.notifications.services = [
        NotificationService(name="Svc", type=service_type, enabled=True)
    ]
    isolated_config_manager.update_config(config)

    await manager._process_notification(_make_event("restart"))

    for t, mock in senders.items():
        assert mock.await_count == (1 if t == service_type else 0)


@pytest.mark.asyncio
async def test_test_notification_reports_failure_for_disabled_service(
    isolated_config_manager, manager
):
    config = _configure_webhook(isolated_config_manager)
    config.notifications.services[0].enabled = False
    isolated_config_manager.update_config(config)

    result = await manager.test_notification("Test Webhook")

    assert result == {"success": False, "message": "Service 'Test Webhook' is disabled"}
    assert fake_session(manager).calls == []


@pytest.mark.asyncio
async def test_test_notification_reports_failure_for_unsupported_type(
    isolated_config_manager, manager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(name="Carrier Pigeon", type="carrier-pigeon", enabled=True),
    )

    result = await manager.test_notification("Carrier Pigeon")

    assert result == {
        "success": False,
        "message": "Unsupported notification type: carrier-pigeon",
    }


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
        if len(fake_session(manager).calls) >= 1:
            break
        await asyncio.sleep(0.01)

    manager._running = False
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker

    assert len(calls) == 2
    assert len(fake_session(manager).calls) == 1


@pytest.mark.asyncio
async def test_notification_worker_keeps_polling_after_queue_wait_timeout(
    caplog, monkeypatch, isolated_config_manager, manager
):
    """A queue-wait timeout must make the worker poll again, not stop."""
    _configure_webhook(isolated_config_manager)

    real_wait_for = asyncio.wait_for
    timeouts_raised = 0

    async def wait_for_timing_out_once(awaitable, **kwargs):
        nonlocal timeouts_raised
        if timeouts_raised == 0:
            timeouts_raised += 1
            awaitable.close()
            raise TimeoutError
        return await real_wait_for(awaitable, **kwargs)

    monkeypatch.setattr(
        "app.notifications.notification_manager.asyncio.wait_for",
        wait_for_timing_out_once,
    )

    manager._running = True
    await manager._notification_queue.put(_make_event("restart"))
    with caplog.at_level(logging.ERROR):
        worker = asyncio.create_task(manager._notification_worker())

        for _ in range(200):
            if fake_session(manager).calls:
                break
            await asyncio.sleep(0.01)

        manager._running = False
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker

    assert timeouts_raised == 1
    assert len(fake_session(manager).calls) == 1
    assert not any("Error in notification worker" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_start_stop_lifecycle_delivers_queued_notification(
    monkeypatch, isolated_config_manager
):
    monkeypatch.setattr(
        "app.notifications.notification_manager.aiohttp.ClientSession",
        _FakeAiohttpSession,
    )
    _configure_webhook(isolated_config_manager)

    instance = NotificationManager()
    await instance.start()
    assert instance._running is True
    assert instance._worker_task is not None
    started_session = fake_session(instance)

    await instance.send_event_notification(_make_event("restart"))

    for _ in range(200):
        if started_session.calls:
            break
        await asyncio.sleep(0.01)

    assert len(started_session.calls) == 1

    session = started_session
    await instance.stop()
    assert instance._running is False
    assert session.closed is True
    assert instance._session is None


class _GatedSession(_FakeAiohttpSession):
    """Fake session whose POST stays in flight until `release` is set.

    `started` records each POST that began; `completed` only those that ran to
    the end (a cancelled POST is started but never completed). With
    `hang=True` the POST never finishes on its own.
    """

    def __init__(self, hang: bool = False):
        super().__init__()
        self.hang = hang
        self.release = asyncio.Event()
        self.started: list[str] = []
        self.completed: list[str] = []

    def post(self, url, **kwargs):
        return _GatedResponse(self, kwargs["json"]["event"]["container_name"])


class _GatedResponse(_FakeResponse):
    def __init__(self, session: _GatedSession, name: str):
        super().__init__()
        self._session = session
        self._name = name

    async def __aenter__(self):
        self._session.started.append(self._name)
        if self._session.hang:
            await asyncio.Event().wait()
        await self._session.release.wait()
        self._session.completed.append(self._name)
        return self


def _named_event(name: str) -> AutoHealEvent:
    event = _make_event("restart")
    event.container_name = name
    return event


async def _started_manager(monkeypatch, isolated_config_manager, session: _GatedSession):
    monkeypatch.setattr(
        "app.notifications.notification_manager.aiohttp.ClientSession",
        lambda *args, **kwargs: session,
    )
    _configure_webhook(isolated_config_manager)
    instance = NotificationManager()
    await instance.start()
    return instance


async def _wait_until(predicate) -> None:
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_stop_delivers_notifications_queued_before_stop(
    caplog, monkeypatch, isolated_config_manager
):
    """Events queued but not yet picked up by the worker are sent, in order."""
    session = _GatedSession()
    session.release.set()
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)

    await instance.send_event_notification(_named_event("first"))
    await instance.send_event_notification(_named_event("second"))
    with caplog.at_level(logging.WARNING):
        await instance.stop()

    assert session.completed == ["first", "second"]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert instance._notification_queue.empty()
    assert session.closed is True
    assert instance._session is None


@pytest.mark.asyncio
async def test_stop_lets_in_flight_notification_finish(monkeypatch, isolated_config_manager):
    """A notification being sent when stop() is called is not cancelled mid-send."""
    session = _GatedSession()
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)

    await instance.send_event_notification(_named_event("in-flight"))
    await _wait_until(lambda: session.started)

    stop_task = asyncio.create_task(instance.stop())
    await asyncio.sleep(0.05)
    assert not stop_task.done()
    assert session.closed is False

    session.release.set()
    await asyncio.wait_for(stop_task, timeout=5)

    assert session.completed == ["in-flight"]
    assert session.closed is True


@pytest.mark.asyncio
async def test_send_event_notification_after_stop_is_dropped_and_logged(
    caplog, monkeypatch, isolated_config_manager
):
    session = _GatedSession()
    session.release.set()
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)
    await instance.stop()

    with caplog.at_level(logging.WARNING):
        await instance.send_event_notification(_named_event("late"))

    assert instance._notification_queue.empty()
    assert any(
        r.levelno == logging.WARNING and "stopped" in r.message and "restart" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_send_event_notification_during_drain_is_dropped_and_logged(
    caplog, monkeypatch, isolated_config_manager
):
    """An event arriving while stop() is still draining is refused, not queued."""
    session = _GatedSession()
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)

    await instance.send_event_notification(_named_event("in-flight"))
    await _wait_until(lambda: session.started)

    stop_task = asyncio.create_task(instance.stop())
    await _wait_until(lambda: instance._stopping)
    assert not stop_task.done()

    with caplog.at_level(logging.WARNING):
        await instance.send_event_notification(_named_event("during-drain"))

    assert instance._notification_queue.empty()
    assert any(
        r.levelno == logging.WARNING
        and r.getMessage()
        == "Notification manager is stopped; dropping notification for event: restart"
        for r in caplog.records
    )

    session.release.set()
    await asyncio.wait_for(stop_task, timeout=5)

    await instance.start()
    await instance.send_event_notification(_named_event("after-restart"))
    await asyncio.wait_for(instance.stop(), timeout=5)

    assert session.completed == ["in-flight", "after-restart"]


@pytest.mark.asyncio
async def test_stop_drain_is_bounded_and_logs_dropped_count(
    caplog, monkeypatch, isolated_config_manager
):
    """An unreachable provider cannot hold shutdown open; the loss is logged."""
    session = _GatedSession(hang=True)
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)
    monkeypatch.setattr(instance, "SHUTDOWN_DRAIN_TIMEOUT_SECONDS", 0.1)

    await instance.send_event_notification(_named_event("stuck"))
    await _wait_until(lambda: session.started)
    await instance.send_event_notification(_named_event("queued-1"))
    await instance.send_event_notification(_named_event("queued-2"))

    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(instance.stop(), timeout=5)

    assert session.completed == []
    assert session.closed is True
    assert instance._session is None
    assert instance._worker_task is not None
    assert instance._worker_task.done()
    assert instance._notification_queue.empty()
    assert any(
        r.levelno == logging.WARNING
        and r.getMessage()
        == "Notification manager stopped with 3 undelivered notification(s) dropped"
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_events_dropped_by_timed_out_stop_are_not_sent_after_restart(
    monkeypatch, isolated_config_manager
):
    """Events reported as dropped must really be dropped, not delivered on a later start()."""
    session = _GatedSession(hang=True)
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)
    monkeypatch.setattr(instance, "SHUTDOWN_DRAIN_TIMEOUT_SECONDS", 0.1)

    await instance.send_event_notification(_named_event("stuck"))
    await _wait_until(lambda: session.started)
    await instance.send_event_notification(_named_event("stale"))
    await asyncio.wait_for(instance.stop(), timeout=5)

    session.hang = False
    session.release.set()
    await instance.start()
    await asyncio.wait_for(instance.stop(), timeout=5)

    assert session.completed == []


@pytest.mark.asyncio
async def test_cancelled_stop_still_releases_worker_and_session(
    monkeypatch, isolated_config_manager
):
    """Cancelling stop() while it drains must not leak the worker or the HTTP session."""
    session = _GatedSession(hang=True)
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)

    await instance.send_event_notification(_named_event("stuck"))
    await _wait_until(lambda: session.started)

    stop_task = asyncio.create_task(instance.stop())
    await asyncio.sleep(0.05)
    stop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert instance._running is False
    assert instance._worker_task is not None
    assert instance._worker_task.done()
    assert session.closed is True
    assert instance._session is None


@pytest.mark.asyncio
async def test_stop_with_nothing_queued_reports_no_dropped_notifications(
    caplog, monkeypatch, isolated_config_manager
):
    """A manager that never sent anything stops quietly, without a false drop warning."""
    session = _GatedSession()
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)

    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(instance.stop(), timeout=5)

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.asyncio
async def test_stop_tolerates_running_manager_without_worker_or_session():
    """A partially started manager (no worker/session yet) can still be stopped."""
    instance = NotificationManager()
    instance._running = True

    await asyncio.wait_for(instance.stop(), timeout=5)

    assert instance._running is False
    assert instance._session is None


@pytest.mark.asyncio
async def test_manager_accepts_notifications_again_after_restart(
    monkeypatch, isolated_config_manager
):
    session = _GatedSession()
    session.release.set()
    instance = await _started_manager(monkeypatch, isolated_config_manager, session)
    await instance.stop()

    await instance.start()
    await instance.send_event_notification(_named_event("after-restart"))
    await instance.stop()

    assert session.completed == ["after-restart"]


@pytest.mark.asyncio
async def test_start_when_already_running_is_a_noop(monkeypatch, isolated_config_manager):
    monkeypatch.setattr(
        "app.notifications.notification_manager.aiohttp.ClientSession",
        _FakeAiohttpSession,
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


# ---------------------------------------------------------------------------
# Gap-fill: missing credentials, HTTP failures and request exceptions for
# providers not already covered above (webhook 4xx/5xx + exception, telegram
# missing-config, and every provider's payload/priority shape already have
# dedicated tests further up this file).
# ---------------------------------------------------------------------------


def _service_missing_webhook_url():
    return NotificationService(name="Webhook", type="webhook", enabled=True)


def _service_missing_discord_url():
    return NotificationService(name="Discord", type="discord", enabled=True)


def _service_missing_slack_url():
    return NotificationService(name="Slack", type="slack", enabled=True)


def _service_missing_ntfy_topic():
    return NotificationService(name="Ntfy", type="ntfy", enabled=True)


def _service_missing_gotify_credentials():
    return NotificationService(name="Gotify", type="gotify", enabled=True)


def _service_missing_pushover_credentials():
    return NotificationService(name="Pushover", type="pushover", enabled=True)


@pytest.mark.parametrize(
    ("service_factory", "expected_warning"),
    [
        (_service_missing_webhook_url, "Webhook URL not configured"),
        (_service_missing_discord_url, "Discord webhook URL not configured"),
        (_service_missing_slack_url, "Slack webhook URL not configured"),
        (_service_missing_ntfy_topic, "Ntfy topic not configured"),
        (
            _service_missing_gotify_credentials,
            "Gotify server URL or app token not configured",
        ),
        (
            _service_missing_pushover_credentials,
            "Pushover user key or API token not configured",
        ),
    ],
)
@pytest.mark.asyncio
async def test_missing_credentials_skip_request_without_calling_session(
    caplog, isolated_config_manager, manager, service_factory, expected_warning
):
    """Each provider must bail out before touching the HTTP session."""
    _configure_service(isolated_config_manager, service_factory())

    with caplog.at_level(logging.WARNING):
        await manager._process_notification(_make_event("restart"))

    assert fake_session(manager).calls == []
    assert any(expected_warning in r.message for r in caplog.records)


def _service_discord():
    return NotificationService(
        name="Discord",
        type="discord",
        enabled=True,
        url="https://example.invalid/discord",
    )


def _service_slack():
    return NotificationService(
        name="Slack", type="slack", enabled=True, url="https://example.invalid/slack"
    )


def _service_telegram():
    return NotificationService(
        name="Telegram",
        type="telegram",
        enabled=True,
        bot_token="abc123",
        chat_id="999",
    )


def _service_ntfy():
    return NotificationService(name="Ntfy", type="ntfy", enabled=True, topic="alerts")


def _service_gotify():
    return NotificationService(
        name="Gotify",
        type="gotify",
        enabled=True,
        server_url="https://gotify.example.invalid",
        app_token="tok123",
    )


def _service_pushover():
    return NotificationService(
        name="Pushover",
        type="pushover",
        enabled=True,
        user_key="userkey",
        api_token="apitoken",
    )


@pytest.mark.parametrize(
    ("service_factory", "expected_log"),
    [
        (_service_discord, "Discord webhook failed with status 500"),
        (_service_slack, "Slack webhook failed with status 500"),
        (_service_telegram, "Telegram API failed with status 500"),
        (_service_ntfy, "Ntfy failed with status 500"),
        (_service_gotify, "Gotify failed with status 500"),
        (_service_pushover, "Pushover failed with status 500"),
    ],
)
@pytest.mark.asyncio
async def test_http_error_status_is_logged_not_raised(
    caplog, isolated_config_manager, manager, service_factory, expected_log
):
    """A 5xx response must be logged, not propagated to the caller."""
    manager._session = _FakeSession(status=500)
    _configure_service(isolated_config_manager, service_factory())

    with caplog.at_level(logging.ERROR):
        await manager._process_notification(_make_event("restart"))

    assert any(expected_log in r.message for r in caplog.records)


@pytest.mark.parametrize(
    ("service_factory", "expected_log"),
    [
        (_service_discord, "Failed to send Discord notification"),
        (_service_slack, "Failed to send Slack notification"),
        (_service_telegram, "Failed to send Telegram notification"),
        (_service_ntfy, "Failed to send Ntfy notification"),
        (_service_gotify, "Failed to send Gotify notification"),
        (_service_pushover, "Failed to send Pushover notification"),
    ],
)
@pytest.mark.asyncio
async def test_request_exception_is_caught_and_logged(
    caplog, isolated_config_manager, manager, service_factory, expected_log
):
    """A raised connection error must be caught and logged per provider."""

    class _RaisingSession:
        def post(self, *args, **kwargs):
            raise ConnectionError("network unreachable")

    manager._session = _RaisingSession()
    _configure_service(isolated_config_manager, service_factory())

    with caplog.at_level(logging.ERROR):
        await manager._process_notification(_make_event("restart"))

    assert any(expected_log in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "service_factory",
    [
        lambda: NotificationService(
            name="svc", type="webhook", enabled=True, url="https://example.invalid/hook"
        ),
        _service_discord,
        _service_slack,
        _service_telegram,
        _service_ntfy,
        _service_gotify,
        _service_pushover,
    ],
)
@pytest.mark.asyncio
async def test_sender_exception_text_is_not_logged_or_returned(caplog, manager, service_factory):
    """A request error can embed the URL or token, so only its type may reach logs or results."""

    class _RaisingSession:
        def post(self, *args, **kwargs):
            raise ConnectionError("cannot reach https://example.invalid/SECRET-TOKEN-123")

    manager._session = _RaisingSession()

    with caplog.at_level(logging.DEBUG):
        result = await manager.send_test(service_factory())

    assert result["success"] is False
    assert "SECRET-TOKEN-123" not in caplog.text
    assert "SECRET-TOKEN-123" not in result["message"]
    assert "ConnectionError" in caplog.text


@pytest.mark.asyncio
async def test_send_webhook_includes_priority_and_custom_headers(
    isolated_config_manager, manager: NotificationManager
):
    """Webhook is the only provider whose payload carries a raw priority value
    and supports arbitrary custom headers; neither is exercised elsewhere."""
    _configure_service(
        isolated_config_manager,
        NotificationService(
            name="Webhook",
            type="webhook",
            enabled=True,
            url="https://example.invalid/webhook",
            headers={"X-Api-Key": "secret123"},
        ),
    )

    await manager._process_notification(_make_event("quarantine"))

    call = fake_session(manager).calls[0]
    assert call["json"]["priority"] == "high"
    assert call["headers"]["X-Api-Key"] == "secret123"
    assert call["headers"]["Content-Type"] == "application/json"


class _StartBarrier:
    """Releases every waiter only once `count` providers have started
    sending. A sequential implementation would await one provider to
    completion before starting the next, so the second provider would never
    reach the barrier and every waiter would hang forever; only genuine
    concurrent execution (e.g. via asyncio.gather) lets all of them arrive
    and proceed."""

    def __init__(self, count: int):
        self._count = count
        self._arrived = 0
        self._event = asyncio.Event()

    async def wait_for_all(self) -> None:
        self._arrived += 1
        if self._arrived >= self._count:
            self._event.set()
        await self._event.wait()


class _BarrierResponse:
    def __init__(self, barrier: _StartBarrier, *, fail: bool, status: int = 200):
        self._barrier = barrier
        self._fail = fail
        self.status = status

    async def text(self) -> str:
        return ""

    async def __aenter__(self):
        await self._barrier.wait_for_all()
        if self._fail:
            raise ConnectionError("network unreachable")
        return self

    async def __aexit__(self, *exc_info):
        return False


class _PerUrlBarrierSession:
    """Fake session where behaviour depends on the target URL, so one
    provider can fail while another succeeds in the same notification run.
    Each response only resolves once every provider has started sending,
    which proves they run concurrently rather than one after another."""

    def __init__(self, failing_url: str, barrier: _StartBarrier):
        self._failing_url = failing_url
        self._barrier = barrier
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _BarrierResponse(self._barrier, fail=(url == self._failing_url))


@pytest.mark.asyncio
async def test_one_provider_failure_does_not_block_other_notifications(
    caplog, isolated_config_manager, manager
):
    """A single failing service must not stop sibling services in the same
    notification batch (they run concurrently via asyncio.gather).

    Both fake responses only resolve once both providers have started
    sending (see `_StartBarrier`), so this test would hang and time out
    under a sequential implementation that awaits one provider before
    starting the next -- it only passes when the providers genuinely run
    concurrently.
    """
    failing_url = "https://example.invalid/webhook"
    working_url = "https://example.invalid/discord"
    barrier = _StartBarrier(count=2)
    session = _PerUrlBarrierSession(failing_url=failing_url, barrier=barrier)
    manager._session = session

    config = isolated_config_manager.get_config()
    config.notifications.enabled = True
    config.notifications.services = [
        NotificationService(name="Webhook", type="webhook", enabled=True, url=failing_url),
        NotificationService(name="Discord", type="discord", enabled=True, url=working_url),
    ]
    isolated_config_manager.update_config(config)

    with caplog.at_level(logging.ERROR):
        await asyncio.wait_for(manager._process_notification(_make_event("restart")), timeout=2)

    called_urls = {call["url"] for call in session.calls}
    assert called_urls == {failing_url, working_url}
    assert any("Failed to send webhook notification" in r.message for r in caplog.records)


class _RaisingSession:
    def post(self, *args, **kwargs):
        raise ConnectionError("network unreachable")

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_SERVICES_BY_LABEL))
async def test_test_notification_reports_success_for_each_provider(
    label, isolated_config_manager, manager: NotificationManager
):
    _configure_service(isolated_config_manager, _SERVICES_BY_LABEL[label])

    result = await manager.test_notification("svc")

    assert result == {"success": True, "message": "Test notification sent successfully"}


@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_SERVICES_BY_LABEL))
async def test_test_notification_reports_failure_on_http_error_status(
    label, isolated_config_manager, manager: NotificationManager
):
    manager._session = _FakeSession(status=500)
    _configure_service(isolated_config_manager, _SERVICES_BY_LABEL[label])

    result = await manager.test_notification("svc")

    assert result["success"] is False
    assert "not delivered" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_SERVICES_BY_LABEL))
async def test_test_notification_reports_failure_when_request_raises(
    label, isolated_config_manager, manager: NotificationManager
):
    manager._session = _RaisingSession()
    _configure_service(isolated_config_manager, _SERVICES_BY_LABEL[label])

    result = await manager.test_notification("svc")

    assert result["success"] is False
    assert "not delivered" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("label", list(_SERVICES_BY_LABEL))
async def test_test_notification_reports_failure_when_no_session_is_active(
    label, isolated_config_manager
):
    unstarted = NotificationManager()
    assert unstarted._session is None
    _configure_service(isolated_config_manager, _SERVICES_BY_LABEL[label])

    result = await unstarted.test_notification("svc")

    assert result["success"] is False
    assert "not delivered" in result["message"]


@pytest.mark.asyncio
async def test_test_notification_reports_failure_when_service_is_not_configured(
    isolated_config_manager, manager: NotificationManager
):
    _configure_service(
        isolated_config_manager,
        NotificationService(name="svc", type="webhook", enabled=True, url=""),
    )

    result = await manager.test_notification("svc")

    assert result["success"] is False
    assert "not delivered" in result["message"]
    assert fake_session(manager).calls == []


@pytest.mark.asyncio
async def test_send_telegram_ok_false_with_http_200_is_failure_and_logs_description(
    caplog, isolated_config_manager, manager: NotificationManager
):
    class _TelegramRejectedResponse(_FakeResponse):
        async def json(self, content_type=None) -> Any:
            return {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}

    class _TelegramRejectedSession(_FakeSession):
        def post(self, url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            return _TelegramRejectedResponse(200)

    manager._session = _TelegramRejectedSession()
    _configure_service(isolated_config_manager, _SERVICES_BY_LABEL["Telegram"])
    service = _SERVICES_BY_LABEL["Telegram"]

    with caplog.at_level(logging.ERROR):
        delivered = await manager._send_telegram(
            service, "title", "message", _make_event("restart"), NotificationPriority.NORMAL
        )

    assert delivered is False
    assert any("Bad Request: chat not found" in r.message for r in caplog.records)


async def _send_via(manager: NotificationManager, label: str) -> bool:
    """Call the provider's sender directly with a minimal event."""
    sender = getattr(manager, f"_send_{label.lower()}")
    return await sender(
        _SERVICES_BY_LABEL[label],
        "title",
        "message",
        _make_event("restart"),
        NotificationPriority.NORMAL,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected_log"),
    [
        (ValueError("not JSON"), "ok=true"),
        ({}, "ok=true"),
        ({"description": "no acknowledgement"}, "no acknowledgement"),
        ({"ok": None}, "ok=true"),
        ({"ok": "true"}, "ok=true"),
        ({"ok": 1}, "ok=true"),
        ({"ok": False, "description": "Bad Request: chat not found"}, "chat not found"),
        ([], "ok=true"),
        ("ok", "ok=true"),
        (None, "ok=true"),
    ],
)
async def test_send_telegram_unconfirmed_http_200_is_failure_and_logged(
    body, expected_log, caplog, manager: NotificationManager
):
    manager._session = _FakeSession(body=body)

    with caplog.at_level(logging.ERROR):
        delivered = await _send_via(manager, "Telegram")

    assert delivered is False
    assert any(expected_log in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_send_telegram_ok_true_is_success(manager: NotificationManager):
    manager._session = _FakeSession(body={"ok": True, "result": {"message_id": 1}})

    assert await _send_via(manager, "Telegram") is True


@pytest.mark.asyncio
async def test_send_telegram_redirect_status_is_failure(manager: NotificationManager):
    manager._session = _FakeSession(status=302)

    assert await _send_via(manager, "Telegram") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Discord", "Slack"])
@pytest.mark.parametrize("status", [200, 204])
async def test_discord_and_slack_2xx_is_success_without_following_redirects(
    label, status, manager: NotificationManager
):
    manager._session = _FakeSession(status=status)

    assert await _send_via(manager, label) is True
    assert fake_session(manager).calls[0]["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Discord", "Slack"])
@pytest.mark.parametrize("status", [301, 302, 307, 400, 500])
async def test_discord_and_slack_non_2xx_is_failure(
    label, status, caplog, manager: NotificationManager
):
    manager._session = _FakeSession(status=status)

    with caplog.at_level(logging.ERROR):
        delivered = await _send_via(manager, label)

    assert delivered is False
    assert any(f"failed with status {status}" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Gotify", "Ntfy"])
async def test_gotify_and_ntfy_follow_redirects_that_stay_a_post(
    label, manager: NotificationManager
):
    # A 307/308 behind a reverse proxy keeps the method, so the final request is still a POST.
    manager._session = _FakeSession(status=200, method="POST")

    assert await _send_via(manager, label) is True
    assert "allow_redirects" not in fake_session(manager).calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Gotify", "Ntfy"])
async def test_gotify_and_ntfy_redirect_that_became_a_get_is_failure(
    label, caplog, manager: NotificationManager
):
    # aiohttp turns a redirected 301/302/303 POST into a GET; a 200 from it is not delivery.
    manager._session = _FakeSession(status=200, method="GET")

    with caplog.at_level(logging.ERROR):
        delivered = await _send_via(manager, label)

    assert delivered is False
    assert any("no longer a POST" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Gotify", "Ntfy"])
@pytest.mark.parametrize("status", [302, 304, 400, 500])
async def test_gotify_and_ntfy_non_2xx_is_failure(
    label, status, caplog, manager: NotificationManager
):
    manager._session = _FakeSession(status=status)

    with caplog.at_level(logging.ERROR):
        delivered = await _send_via(manager, label)

    assert delivered is False
    assert any(f"failed with status {status}" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_send_pushover_status_zero_with_http_200_is_failure(
    caplog, isolated_config_manager, manager: NotificationManager
):
    class _PushoverRejectedResponse(_FakeResponse):
        async def json(self, content_type=None) -> Any:
            return {"status": 0, "errors": ["user identifier is invalid"]}

    class _PushoverRejectedSession(_FakeSession):
        def post(self, url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            return _PushoverRejectedResponse(200)

    manager._session = _PushoverRejectedSession()
    service = _SERVICES_BY_LABEL["Pushover"]
    _configure_service(isolated_config_manager, service)

    with caplog.at_level(logging.ERROR):
        delivered = await manager._send_pushover(
            service, "title", "message", _make_event("restart"), NotificationPriority.NORMAL
        )

    assert delivered is False
    assert any("user identifier is invalid" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_pushover_non_json_body_with_http_200_is_failure(
    isolated_config_manager, manager: NotificationManager
):
    class _PushoverHtmlResponse(_FakeResponse):
        async def json(self, content_type=None) -> Any:
            raise ValueError("not json")

    class _PushoverHtmlSession(_FakeSession):
        def post(self, url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            return _PushoverHtmlResponse(200)

    manager._session = _PushoverHtmlSession()
    service = _SERVICES_BY_LABEL["Pushover"]
    _configure_service(isolated_config_manager, service)

    delivered = await manager._send_pushover(
        service, "title", "message", _make_event("restart"), NotificationPriority.NORMAL
    )

    assert delivered is False


@pytest.mark.asyncio
async def test_send_webhook_redirect_is_failure_and_not_followed(
    isolated_config_manager, manager: NotificationManager
):
    manager._session = _FakeSession(status=302)
    service = _SERVICES_BY_LABEL["webhook"]
    _configure_service(isolated_config_manager, service)

    delivered = await manager._send_webhook(
        service, "title", "message", _make_event("restart"), NotificationPriority.NORMAL
    )

    assert delivered is False
    assert fake_session(manager).calls[0]["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 304])
async def test_send_pushover_redirect_status_is_failure_despite_accepted_body(
    status, caplog, manager: NotificationManager
):
    manager._session = _FakeSession(status=status, body={"status": 1})

    with caplog.at_level(logging.ERROR):
        delivered = await _send_via(manager, "Pushover")

    assert delivered is False
    assert any(f"failed with status {status}" in r.getMessage() for r in caplog.records)
