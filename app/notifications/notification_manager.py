"""
Notification Manager - Handles sending notifications to various services
Supports: Webhook, Discord, Slack, Telegram, Ntfy, Gotify, Pushover
"""

import asyncio
import html
import logging
import re
from contextlib import AbstractAsyncContextManager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlsplit

import aiohttp

from app.config.config_manager import AutoHealEvent, NotificationService, config_manager

logger = logging.getLogger(__name__)

# Only 2xx responses confirm delivery; redirects are not followed, so a 3xx is not success.
_HTTP_SUCCESS = range(200, 300)

# Field labels produced by ``_format_notification`` (``**Label:** value`` at line start).
_BOLD_LABEL = re.compile(r"^\*\*([^*\n]+:)\*\*", re.MULTILINE)


@dataclass(frozen=True)
class _Failure:
    """Why a send failed: ``reason`` is safe for the UI, ``detail`` is masked for the log."""

    reason: str
    detail: str


# Set by the sender that just failed. A ContextVar keeps concurrent tests from sharing it.
_last_failure: ContextVar[_Failure | None] = ContextVar("notification_last_failure", default=None)

_URL_IN_TEXT = re.compile(r"""[a-z][a-z0-9+.-]*://[^\s'"<>]+""", re.IGNORECASE)

# Fields that can hold credentials or a credential-bearing URL.
_SECRET_FIELDS = (
    "url",
    "server_url",
    "topic",
    "bot_token",
    "access_token",
    "password",
    "app_token",
    "api_token",
    "user_key",
)


def _mask_secrets(text: str, service: Any) -> str:
    """Replace every secret value of ``service`` found in ``text`` with ``***``."""
    secrets = [getattr(service, field, None) for field in _SECRET_FIELDS]
    secrets.extend((getattr(service, "headers", None) or {}).values())
    for secret in sorted({v for v in secrets if isinstance(v, str) and v}, key=len, reverse=True):
        text = text.replace(secret, "***")
    # Any other URL in an error can carry a token in its path or query.
    return _URL_IN_TEXT.sub("***", text)


def _origin(url: str | None) -> str:
    """Scheme and host of ``url`` only; the path and query can hold a token."""
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.hostname}" if parts.scheme and parts.hostname else "***"


class _HttpResponse(Protocol):
    """The slice of ``aiohttp.ClientResponse`` that delivery relies on."""

    @property
    def status(self) -> int: ...

    @property
    def method(self) -> str:
        """Method of the final request, which a redirect can change from POST to GET."""
        ...

    async def text(self) -> str: ...

    async def json(self, *, content_type: str | None = ...) -> Any: ...


class _HttpSession(Protocol):
    """
    The slice of ``aiohttp.ClientSession`` that delivery relies on.

    Typing ``_session`` structurally lets tests substitute a fake session
    without it having to claim to be an ``aiohttp.ClientSession``.
    """

    def post(
        self,
        url: str,
        *,
        json: Any = ...,
        data: Any = ...,
        headers: Any = ...,
        allow_redirects: bool = ...,
    ) -> AbstractAsyncContextManager[_HttpResponse]: ...

    async def close(self) -> None: ...


class NotificationType(StrEnum):
    """Types of notification services"""

    WEBHOOK = "webhook"
    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    NTFY = "ntfy"
    GOTIFY = "gotify"
    PUSHOVER = "pushover"


class NotificationPriority(StrEnum):
    """Notification priority levels"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationManager:
    """
    Manages notification delivery to various services
    """

    # Upper bound on how long stop() waits for queued notifications to be
    # delivered before dropping the rest, so an unreachable provider cannot
    # delay process exit.
    SHUTDOWN_DRAIN_TIMEOUT_SECONDS = 5.0

    def __init__(self) -> None:
        """Initialize notification manager"""
        self._session: _HttpSession | None = None
        self._notification_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._running = False
        # True once stop() has begun; new events are refused until start().
        self._stopping = False
        self._in_flight = False

    async def start(self) -> None:
        """Start the notification manager"""
        if self._running:
            logger.warning("Notification manager already running")
            return

        self._running = True
        self._stopping = False
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self._worker_task = asyncio.create_task(self._notification_worker())
        logger.info("Notification manager started")

    async def stop(self) -> None:
        """Stop the notification manager"""
        if not self._running:
            return

        # Refuse new events, then give the worker a bounded time to deliver
        # what is already queued (including a notification mid-send).
        self._stopping = True

        try:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._notification_queue.join(),
                    timeout=self.SHUTDOWN_DRAIN_TIMEOUT_SECONDS,
                )
        finally:
            self._running = False
            # Anything still queued or mid-send now (drain timed out, or stop()
            # was cancelled) will not be delivered. Count it before cancelling.
            dropped = self._notification_queue.qsize() + int(self._in_flight)

            if self._worker_task:
                self._worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._worker_task

            # Discard what is left so it is not sent after a later start() and
            # the queue's unfinished-task count stays consistent.
            while not self._notification_queue.empty():
                self._notification_queue.get_nowait()
                self._notification_queue.task_done()

            if dropped:
                logger.warning(
                    "Notification manager stopped with %d undelivered notification(s) dropped",
                    dropped,
                )

            if self._session:
                await self._session.close()
                self._session = None

        logger.info("Notification manager stopped")

    def _fail(
        self,
        service: Any,
        kind: str,
        *,
        status: int | None = None,
        url: str | None = None,
        exc: Exception | None = None,
    ) -> bool:
        """
        Record why a send failed, for ``send_test`` to report, and return False.

        The UI reason names the provider, a category and an HTTP status only. The log
        detail adds the underlying error text with the service's secrets masked.
        """
        provider = str(service.type).capitalize()
        if kind == "status":
            reason = f"{provider} rejected the request (HTTP {status})"
            detail = f"HTTP {status} from {_origin(url)}/***"
        elif kind == "error":
            error_name = type(exc).__name__
            if isinstance(exc, TimeoutError):
                reason = "the request timed out"
            elif isinstance(exc, aiohttp.ClientConnectionError):
                reason = "could not connect to the server"
            else:
                reason = f"unexpected error ({error_name})"
            detail = _mask_secrets(f"{error_name}: {exc}", service)
        else:
            reason = {
                "unconfigured": f"{provider} settings are incomplete",
                "no_session": "the notification manager is not running",
                "redirected": f"{provider} redirected the request instead of accepting it",
                "unconfirmed": f"{provider} did not confirm delivery",
            }[kind]
            detail = reason
        _last_failure.set(_Failure(reason, detail))
        return False

    def _get_session(self, service_label: str) -> _HttpSession | None:
        """
        Return the HTTP session, or log and return None when it is unavailable.

        The session only exists between start() and stop(), so callers should
        skip the send when this returns None rather than retry.
        """
        if self._session is None:
            logger.error(
                "Failed to send %s notification: notification manager has no active session",
                service_label,
            )
        return self._session

    async def send_event_notification(self, event: AutoHealEvent) -> None:
        """
        Send notification for an auto-heal event

        Args:
            event: The event to send notification for
        """

        logger.info("Preparing to send notification for event: %s", event.event_type)

        config = config_manager.get_config()

        # Check if notifications are enabled
        if not config.notifications.enabled:
            logger.debug("Notifications disabled, skipping")
            return

        # Check event filters
        if not self._should_notify_for_event(event):
            logger.debug("Event type '%s' filtered out, skipping notification", event.event_type)
            return

        if self._stopping:
            logger.warning(
                "Notification manager is stopped; dropping notification for event: %s",
                event.event_type,
            )
            return

        # Queue the notification
        await self._notification_queue.put(event)
        logger.debug("Queued notification for event: %s", event.event_type)

    def _should_notify_for_event(self, event: AutoHealEvent) -> bool:
        """
        Check if we should send notification for this event type

        Args:
            event: The event to check

        Returns:
            True if notification should be sent
        """
        config = config_manager.get_config()
        event_filters = config.notifications.event_filters

        # If no filters specified, notify for all events
        if not event_filters:
            return True

        # Check if event type matches any filter
        return event.event_type in event_filters

    async def _notification_worker(self) -> None:
        """Background worker that processes notification queue"""
        while self._running:
            try:
                # Wait for notification with timeout to allow checking _running flag
                try:
                    event = await asyncio.wait_for(self._notification_queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                # Process the notification
                self._in_flight = True
                try:
                    await self._process_notification(event)
                finally:
                    self._in_flight = False
                    self._notification_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in notification worker: %s", e)
                await asyncio.sleep(1)

    async def _process_notification(self, event: AutoHealEvent) -> None:
        """
        Process and send notification for an event

        Args:
            event: The event to send notification for
        """
        config = config_manager.get_config()
        notifications_config = config.notifications

        # Prepare notification content
        title, message, priority = self._format_notification(event)

        # Send to all enabled services
        tasks = []

        for service in notifications_config.services:
            if not service.enabled:
                continue

            try:
                if service.type == NotificationType.WEBHOOK:
                    tasks.append(self._send_webhook(service, title, message, event, priority))
                elif service.type == NotificationType.DISCORD:
                    tasks.append(self._send_discord(service, title, message, event, priority))
                elif service.type == NotificationType.SLACK:
                    tasks.append(self._send_slack(service, title, message, event, priority))
                elif service.type == NotificationType.TELEGRAM:
                    tasks.append(self._send_telegram(service, title, message, event, priority))
                elif service.type == NotificationType.NTFY:
                    tasks.append(self._send_ntfy(service, title, message, event, priority))
                elif service.type == NotificationType.GOTIFY:
                    tasks.append(self._send_gotify(service, title, message, event, priority))
                elif service.type == NotificationType.PUSHOVER:
                    tasks.append(self._send_pushover(service, title, message, event, priority))
                else:
                    logger.warning("Unsupported notification type: %s", service.type)

            except Exception as e:
                logger.error("Error preparing notification for %s: %s", service.type, e)

        # Send all notifications concurrently
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error("Notification failed: %s", result)

    def _format_notification(self, event: AutoHealEvent) -> tuple[str, str, NotificationPriority]:
        """
        Format notification content based on event

        Args:
            event: The event to format

        Returns:
            Tuple of (title, message, priority)
        """
        # Determine priority based on event type
        priority = NotificationPriority.NORMAL
        if event.event_type == "quarantine":
            priority = NotificationPriority.HIGH
        elif event.event_type in ("unquarantine", "restart"):
            priority = NotificationPriority.NORMAL
        elif event.event_type == "auto_monitor":
            priority = NotificationPriority.LOW

        # Format title
        title_map = {
            "restart": "Container Restarted",
            "quarantine": "Container Quarantined",
            "auto_monitor": "Container Auto-Monitored",
            "unquarantine": "Container Unquarantined",
            "auto_unquarantine": "Container Auto-Unquarantined",
        }
        title = title_map.get(event.event_type, f"{event.event_type.replace('_', ' ').title()}")

        # Format message
        timestamp = event.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        message = (
            f"**Container:** {event.container_name}\n"
            f"**Event:** {event.event_type}\n"
            f"**Status:** {event.status}\n"
            f"**Restart Count:** {event.restart_count}\n"
            f"**Time:** {timestamp}\n"
            f"**Message:** {event.message}"
        )

        return title, message, priority

    async def _send_webhook(
        self,
        service: Any,
        title: str,
        message: str,
        event: AutoHealEvent,
        priority: NotificationPriority,
    ) -> bool:
        """Send generic webhook notification"""
        if not service.url:
            logger.warning("Webhook URL not configured")
            return self._fail(service, "unconfigured")

        payload = {
            "title": title,
            "message": message,
            "priority": priority.value,
            "event": {
                "type": event.event_type,
                "container_id": event.container_id,
                "container_name": event.container_name,
                "status": event.status,
                "restart_count": event.restart_count,
                "timestamp": event.timestamp.isoformat(),
            },
        }

        # Add custom headers if configured
        headers = {"Content-Type": "application/json"}
        if service.headers:
            headers.update(service.headers)

        session = self._get_session("webhook")
        if session is None:
            return self._fail(service, "no_session")

        try:
            # Redirects are not followed: aiohttp would turn a redirected POST into a GET
            # and could report a 200 for a request that never delivered the notification.
            async with session.post(
                service.url, json=payload, headers=headers, allow_redirects=False
            ) as response:
                if response.status not in _HTTP_SUCCESS:
                    # Status only: a server can reflect the request path (which may hold a
                    # token) in its error body, so the body is not logged.
                    logger.error("Webhook failed with status %s", response.status)
                    return self._fail(service, "status", status=response.status, url=service.url)
                logger.info("Webhook notification sent successfully to %s", service.name)
                return True
        except Exception as e:
            # Name the exception type only: its message can embed the request URL or token.
            logger.error(
                "Failed to send webhook notification: %s", type(e).__name__, exc_info=False
            )
            return self._fail(service, "error", exc=e)

    async def _send_discord(
        self,
        service: Any,
        title: str,
        message: str,
        event: AutoHealEvent,
        priority: NotificationPriority,
    ) -> bool:
        """Send Discord webhook notification"""
        if not service.url:
            logger.warning("Discord webhook URL not configured")
            return self._fail(service, "unconfigured")

        # Color based on priority
        color_map = {
            NotificationPriority.LOW: 0x95A5A6,  # Gray
            NotificationPriority.NORMAL: 0x3498DB,  # Blue
            NotificationPriority.HIGH: 0xF39C12,  # Orange
            NotificationPriority.CRITICAL: 0xE74C3C,  # Red
        }

        embed = {
            "title": title,
            "description": message.replace("**", ""),
            "color": color_map.get(priority, 0x3498DB),
            "timestamp": event.timestamp.isoformat(),
            "footer": {"text": "Docker Auto-Heal"},
        }

        payload = {
            "embeds": [embed],
            "username": service.username or "Docker Auto-Heal",
        }

        session = self._get_session("Discord")
        if session is None:
            return self._fail(service, "no_session")

        try:
            async with session.post(service.url, json=payload, allow_redirects=False) as response:
                if response.status not in _HTTP_SUCCESS:
                    logger.error("Discord webhook failed with status %s", response.status)
                    return self._fail(service, "status", status=response.status, url=service.url)
                logger.info("Discord notification sent successfully to %s", service.name)
                return True
        except Exception as e:
            logger.error(
                "Failed to send Discord notification: %s", type(e).__name__, exc_info=False
            )
            return self._fail(service, "error", exc=e)

    async def _send_slack(
        self,
        service: Any,
        title: str,
        message: str,
        event: AutoHealEvent,  # noqa: ARG002 - senders share one signature
        priority: NotificationPriority,  # noqa: ARG002 - senders share one signature
    ) -> bool:
        """Send Slack webhook notification"""
        if not service.url:
            logger.warning("Slack webhook URL not configured")
            return self._fail(service, "unconfigured")

        # Format message for Slack
        slack_message = message.replace("**", "*")

        payload = {
            "text": title,
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": title}},
                {"type": "section", "text": {"type": "mrkdwn", "text": slack_message}},
            ],
        }

        session = self._get_session("Slack")
        if session is None:
            return self._fail(service, "no_session")

        try:
            async with session.post(service.url, json=payload, allow_redirects=False) as response:
                if response.status not in _HTTP_SUCCESS:
                    logger.error("Slack webhook failed with status %s", response.status)
                    return self._fail(service, "status", status=response.status, url=service.url)
                logger.info("Slack notification sent successfully to %s", service.name)
                return True
        except Exception as e:
            logger.error("Failed to send Slack notification: %s", type(e).__name__, exc_info=False)
            return self._fail(service, "error", exc=e)

    async def _send_telegram(
        self,
        service: Any,
        title: str,
        message: str,
        event: AutoHealEvent,  # noqa: ARG002 - senders share one signature
        priority: NotificationPriority,  # noqa: ARG002 - senders share one signature
    ) -> bool:
        """Send Telegram notification"""
        if not service.bot_token or not service.chat_id:
            logger.warning("Telegram bot token or chat ID not configured")
            return self._fail(service, "unconfigured")

        # Telegram HTML mode only needs &, < and > escaped, unlike legacy Markdown,
        # which rejects unbalanced "_" or "*" in container names and event text.
        escaped_message = _BOLD_LABEL.sub(r"<b>\1</b>", html.escape(message, quote=False))
        telegram_message = f"<b>{html.escape(title, quote=False)}</b>\n\n{escaped_message}"

        url = f"https://api.telegram.org/bot{service.bot_token}/sendMessage"
        payload = {
            "chat_id": service.chat_id,
            "text": telegram_message,
            "parse_mode": "HTML",
        }

        session = self._get_session("Telegram")
        if session is None:
            return self._fail(service, "no_session")

        try:
            async with session.post(url, json=payload) as response:
                if response.status not in _HTTP_SUCCESS:
                    logger.error("Telegram API failed with status %s", response.status)
                    return self._fail(service, "status", status=response.status, url=url)
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = None
                if not isinstance(body, dict) or body.get("ok") is not True:
                    detail = body.get("description") if isinstance(body, dict) else None
                    logger.error(
                        "Telegram API did not confirm notification: %s",
                        detail or "response was not a JSON object with ok=true",
                    )
                    return self._fail(service, "unconfirmed")
                logger.info("Telegram notification sent successfully to %s", service.name)
                return True
        except Exception as e:
            logger.error(
                "Failed to send Telegram notification: %s", type(e).__name__, exc_info=False
            )
            return self._fail(service, "error", exc=e)

    async def _send_ntfy(
        self,
        service: Any,
        title: str,
        message: str,
        event: AutoHealEvent,  # noqa: ARG002 - senders share one signature
        priority: NotificationPriority,
    ) -> bool:
        """Send ntfy.sh notification"""
        if not service.topic:
            logger.warning("Ntfy topic not configured")
            return self._fail(service, "unconfigured")

        # Ntfy priority mapping (1-5)
        priority_map = {
            NotificationPriority.LOW: "1",
            NotificationPriority.NORMAL: "3",
            NotificationPriority.HIGH: "4",
            NotificationPriority.CRITICAL: "5",
        }

        server_url = service.server_url or "https://ntfy.sh"
        url = f"{server_url}/{service.topic}"

        headers = {
            "Title": title,
            "Priority": priority_map.get(priority, "3"),
            "Tags": "whale,docker",
        }

        # Add authentication if configured (access token takes precedence)
        if service.access_token:
            headers["Authorization"] = f"Bearer {service.access_token}"
        elif service.username and service.password:
            import base64

            credentials = f"{service.username}:{service.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        session = self._get_session("Ntfy")
        if session is None:
            return self._fail(service, "no_session")

        try:
            async with session.post(
                url, data=message.replace("**", ""), headers=headers
            ) as response:
                # aiohttp turns a redirected 301/302/303 POST into a GET; 307/308 stay a POST.
                if response.method != "POST":
                    logger.error(
                        "Ntfy request was redirected and is no longer a POST (final method %s)",
                        response.method,
                    )
                    return self._fail(service, "redirected")
                if response.status not in _HTTP_SUCCESS:
                    logger.error("Ntfy failed with status %s", response.status)
                    return self._fail(service, "status", status=response.status, url=url)
                logger.info("Ntfy notification sent successfully to %s", service.name)
                return True
        except Exception as e:
            logger.error("Failed to send Ntfy notification: %s", type(e).__name__, exc_info=False)
            return self._fail(service, "error", exc=e)

    async def _send_gotify(
        self,
        service: Any,
        title: str,
        message: str,
        event: AutoHealEvent,  # noqa: ARG002 - senders share one signature
        priority: NotificationPriority,
    ) -> bool:
        """Send Gotify notification"""
        if not service.server_url or not service.app_token:
            logger.warning("Gotify server URL or app token not configured")
            return self._fail(service, "unconfigured")

        # Gotify priority mapping (0-10)
        priority_map = {
            NotificationPriority.LOW: 2,
            NotificationPriority.NORMAL: 5,
            NotificationPriority.HIGH: 8,
            NotificationPriority.CRITICAL: 10,
        }

        url = f"{service.server_url}/message"
        payload = {
            "title": title,
            "message": message.replace("**", ""),
            "priority": priority_map.get(priority, 5),
        }

        headers = {"X-Gotify-Key": service.app_token}

        session = self._get_session("Gotify")
        if session is None:
            return self._fail(service, "no_session")

        try:
            async with session.post(url, json=payload, headers=headers) as response:
                # aiohttp turns a redirected 301/302/303 POST into a GET; 307/308 stay a POST.
                if response.method != "POST":
                    logger.error(
                        "Gotify request was redirected and is no longer a POST (final method %s)",
                        response.method,
                    )
                    return self._fail(service, "redirected")
                if response.status not in _HTTP_SUCCESS:
                    logger.error("Gotify failed with status %s", response.status)
                    return self._fail(service, "status", status=response.status, url=url)
                logger.info("Gotify notification sent successfully to %s", service.name)
                return True
        except Exception as e:
            logger.error("Failed to send Gotify notification: %s", type(e).__name__, exc_info=False)
            return self._fail(service, "error", exc=e)

    async def _send_pushover(
        self,
        service: Any,
        title: str,
        message: str,
        event: AutoHealEvent,  # noqa: ARG002 - senders share one signature
        priority: NotificationPriority,
    ) -> bool:
        """Send Pushover notification"""
        if not service.user_key or not service.api_token:
            logger.warning("Pushover user key or API token not configured")
            return self._fail(service, "unconfigured")

        # Pushover priority mapping. Priority 2 (emergency) is avoided because
        # the API rejects it unless `retry` and `expire` are also sent.
        priority_map = {
            NotificationPriority.LOW: -1,
            NotificationPriority.NORMAL: 0,
            NotificationPriority.HIGH: 1,
            NotificationPriority.CRITICAL: 1,
        }

        url = "https://api.pushover.net/1/messages.json"
        payload = {
            "token": service.api_token,
            "user": service.user_key,
            "title": title,
            "message": message.replace("**", ""),
            "priority": priority_map.get(priority, 0),
        }

        session = self._get_session("Pushover")
        if session is None:
            return self._fail(service, "no_session")

        try:
            async with session.post(url, data=payload) as response:
                if response.status not in _HTTP_SUCCESS:
                    logger.error("Pushover failed with status %s", response.status)
                    return self._fail(service, "status", status=response.status, url=url)
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = None
                if not isinstance(body, dict) or body.get("status") != 1:
                    logger.error("Pushover did not accept notification: %s", body)
                    return self._fail(service, "unconfirmed")
                logger.info("Pushover notification sent successfully to %s", service.name)
                return True
        except Exception as e:
            logger.error(
                "Failed to send Pushover notification: %s", type(e).__name__, exc_info=False
            )
            return self._fail(service, "error", exc=e)

    async def test_notification(self, service_name: str) -> dict[str, Any]:
        """
        Send a test notification to verify configuration

        Args:
            service_name: Name of the service to test

        Returns:
            Dict with success status and message
        """
        config = config_manager.get_config()

        # Find the service
        service = None
        for s in config.notifications.services:
            if s.name == service_name:
                service = s
                break

        if not service:
            return {"success": False, "message": f"Service '{service_name}' not found"}

        if not service.enabled:
            return {
                "success": False,
                "message": f"Service '{service_name}' is disabled",
            }

        return await self.send_test(service)

    async def send_test(self, service: NotificationService) -> dict[str, Any]:
        """
        Send a test notification using the given service, saved or not

        Nothing is persisted, and the result message never includes the service values.

        Args:
            service: Service configuration to test

        Returns:
            Dict with success status and message
        """
        # Create a test event
        test_event = AutoHealEvent(
            timestamp=datetime.now(UTC),
            container_id="test-container-id",
            container_name="test-container",
            event_type="test",
            restart_count=0,
            status="success",
            message="This is a test notification from Docker Auto-Heal",
        )

        title = "🧪 Test Notification"
        message = "This is a test notification from Docker Auto-Heal. If you received this, your notification service is configured correctly!"
        priority = NotificationPriority.NORMAL

        _last_failure.set(None)
        try:
            if service.type == NotificationType.WEBHOOK:
                delivered = await self._send_webhook(service, title, message, test_event, priority)
            elif service.type == NotificationType.DISCORD:
                delivered = await self._send_discord(service, title, message, test_event, priority)
            elif service.type == NotificationType.SLACK:
                delivered = await self._send_slack(service, title, message, test_event, priority)
            elif service.type == NotificationType.TELEGRAM:
                delivered = await self._send_telegram(service, title, message, test_event, priority)
            elif service.type == NotificationType.NTFY:
                delivered = await self._send_ntfy(service, title, message, test_event, priority)
            elif service.type == NotificationType.GOTIFY:
                delivered = await self._send_gotify(service, title, message, test_event, priority)
            elif service.type == NotificationType.PUSHOVER:
                delivered = await self._send_pushover(service, title, message, test_event, priority)
            else:
                return {
                    "success": False,
                    "message": f"Unsupported notification type: {service.type}",
                }

            if not delivered:
                failure = _last_failure.get()
                if failure is None:
                    return {
                        "success": False,
                        "message": f"Test notification to '{service.name}' was not delivered, see logs",
                    }
                logger.error(
                    "Test notification failed for '%s' (%s): %s",
                    service.name,
                    service.type,
                    failure.detail,
                )
                return {
                    "success": False,
                    "message": f"Test notification to '{service.name}' failed: {failure.reason}",
                }

            return {"success": True, "message": "Test notification sent successfully"}

        except Exception as e:
            # Name the exception type only: the message can embed the request URL or token.
            logger.error("Failed to send test notification: %s", type(e).__name__, exc_info=False)
            return {
                "success": False,
                "message": "Failed to send test notification, see logs",
            }


# Global notification manager instance
notification_manager = NotificationManager()

__all__ = ["NotificationManager"]
