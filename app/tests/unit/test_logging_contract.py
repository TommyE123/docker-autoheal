"""
Regression tests pinning the log records emitted on error and fallback paths.

These paths log at ERROR/WARNING from ``except`` blocks. The tests assert the
level, the rendered message and, where the call attaches one, the traceback
(``exc_info``), so a change to how a call is written (``exc_info=True`` versus
``.exception()``, an f-string versus lazy ``%`` formatting) cannot silently
change what operators see in the logs.
"""

import asyncio
import logging
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.models import ContainerSelectionRequest
from app.api.routes.config import update_observability_config
from app.api.routes.containers import update_container_selection
from app.config.config_manager import ConfigManager, config_manager
from app.config.init_defaults import init_data_file, initialize_defaults, reset_to_defaults
from app.docker_client.docker_client_wrapper import DockerClientWrapper
from app.main import AutoHealService
from app.main import main as app_main
from app.notifications.notification_manager import NotificationManager
from app.tests.unit.conftest import make_container
from app.tests.unit.test_notification_manager import (
    _configure_webhook,
    _FakeResponse,
    _FakeSession,
    _make_event,
)


@pytest.fixture(autouse=True)
def debug_logging(caplog):
    caplog.set_level(logging.DEBUG)


def record_for(caplog, message: str, level: int | None = None) -> logging.LogRecord:
    """Return the single record whose rendered message equals ``message``."""
    matches = [r for r in caplog.records if r.getMessage() == message]
    assert len(matches) == 1, [r.getMessage() for r in caplog.records]
    record = matches[0]
    if level is not None:
        assert record.levelno == level
    return record


def record_starting(caplog, prefix: str, level: int) -> logging.LogRecord:
    """Return the single record whose message starts with ``prefix`` (OS error text varies)."""
    matches = [r for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(matches) == 1, [r.getMessage() for r in caplog.records]
    assert matches[0].levelno == level
    assert not matches[0].exc_info
    return matches[0]


def assert_error_with_traceback(caplog, message: str, exc_type: type[BaseException]) -> None:
    record = record_for(caplog, message, logging.ERROR)
    assert record.exc_info is not None
    assert record.exc_info[0] is exc_type
    assert exc_type.__name__ in caplog.text  # the traceback is rendered


def assert_error_without_traceback(caplog, message: str) -> None:
    record = record_for(caplog, message, logging.ERROR)
    assert not record.exc_info


# ---------------------------------------------------------------------------
# Error paths that log with a traceback
# ---------------------------------------------------------------------------


class TestErrorsLoggedWithTraceback:
    @pytest.mark.asyncio
    async def test_observability_update_failure(self, caplog, monkeypatch):
        monkeypatch.setattr(config_manager, "update_config", MagicMock(side_effect=RuntimeError("boom")))

        with pytest.raises(HTTPException) as exc_info:
            await update_observability_config({"log_format": "text"})

        assert exc_info.value.status_code == 500
        assert_error_with_traceback(caplog, "Error updating observability config: boom", RuntimeError)

    @pytest.mark.asyncio
    async def test_container_selection_failure(self, caplog, monkeypatch, docker_client, engine):
        monkeypatch.setattr("app.api.state.docker_client", docker_client)
        monkeypatch.setattr("app.api.state.monitoring_engine", engine)
        monkeypatch.setattr(config_manager, "update_config", MagicMock(side_effect=RuntimeError("boom")))

        with pytest.raises(HTTPException) as exc_info:
            await update_container_selection(
                ContainerSelectionRequest(container_ids=["ghost"], enabled=True)
            )

        assert exc_info.value.status_code == 500
        assert_error_with_traceback(caplog, "Error updating container selection: boom", RuntimeError)

    @pytest.mark.asyncio
    async def test_service_start_failure(self, caplog):
        config = MagicMock()
        config.observability.log_level = "INFO"
        config.monitor.interval_seconds = 30
        with patch("app.main.config_manager") as mock_cm, \
             patch("app.main.DockerClientWrapper", side_effect=RuntimeError("docker unavailable")), \
             patch("app.main.notification_manager") as mock_notif:
            mock_cm.get_config.return_value = config
            mock_notif.stop = AsyncMock()
            service = AutoHealService()

            with pytest.raises(RuntimeError, match="docker unavailable"):
                await service.start()

        assert_error_with_traceback(caplog, "Failed to start service: docker unavailable", RuntimeError)

    @pytest.mark.asyncio
    async def test_main_entry_point_failure(self, caplog):
        failing_service = MagicMock()
        failing_service.run.side_effect = RuntimeError("cannot run")
        failing_service.running = False

        with patch("app.main.signal.signal"), \
             patch("app.main.AutoHealService", return_value=failing_service), \
             patch("app.main.run_api_server", new=AsyncMock()):
            await app_main()

        assert_error_with_traceback(caplog, "Service error: cannot run", RuntimeError)

    @pytest.mark.asyncio
    async def test_monitor_loop_error_is_logged_and_retried(self, caplog, engine, recorded_sleeps):
        async def failing_check():
            engine._running = False
            raise RuntimeError("check exploded")

        engine._check_containers = failing_check
        engine._running = True

        await engine._monitor_loop()

        assert_error_with_traceback(caplog, "Error in monitoring loop: check exploded", RuntimeError)
        assert recorded_sleeps == [5]

    @pytest.mark.asyncio
    async def test_check_containers_error(self, caplog, engine, docker_client):
        docker_client.list_containers_error = RuntimeError("list failed")

        await engine._check_containers()

        assert_error_with_traceback(caplog, "Error checking containers: list failed", RuntimeError)

    @pytest.mark.asyncio
    async def test_single_container_check_error_has_no_traceback(self, caplog, engine, docker_client):
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        engine._check_single_container = AsyncMock(side_effect=RuntimeError("bad container"))

        await engine._check_containers()

        assert_error_without_traceback(caplog, "Error checking container web: bad container")

    @pytest.mark.asyncio
    async def test_initial_scan_per_container_error(self, caplog, engine, docker_client):
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        docker_client.info_errors[container.id] = RuntimeError("inspect failed")

        await engine._scan_existing_containers()

        assert_error_with_traceback(
            caplog, "Error processing container during initial scan: inspect failed", RuntimeError
        )
        assert "Initial scan complete: no new containers to add" in caplog.text

    @pytest.mark.asyncio
    async def test_initial_scan_error(self, caplog, engine, docker_client):
        docker_client.list_containers_error = RuntimeError("list failed")

        await engine._scan_existing_containers()

        assert_error_with_traceback(caplog, "Error during initial container scan: list failed", RuntimeError)

    @pytest.mark.asyncio
    async def test_event_thread_error(self, caplog, engine, docker_client, monkeypatch):
        release = threading.Event()
        monkeypatch.setattr("time.sleep", lambda seconds: None)
        attempts = []

        def broken_then_idle():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("stream disconnected")
            engine._running = False
            release.wait(timeout=5)
            return iter(())

        docker_client.events = broken_then_idle
        engine._running = True
        try:
            await asyncio.wait_for(engine._event_listener_loop(), timeout=10)
        finally:
            release.set()

        assert_error_with_traceback(
            caplog, "Error in event listener thread: stream disconnected", RuntimeError
        )

    @pytest.mark.asyncio
    async def test_event_queue_consumer_error(self, caplog, engine, docker_client, monkeypatch, recorded_sleeps):
        release = threading.Event()
        event = {"Actor": {"ID": "a" * 64, "Attributes": {"name": "web"}}}

        def event_stream():
            yield event
            release.wait(timeout=5)

        async def failing_process(received):
            engine._running = False
            raise RuntimeError("cannot process")

        docker_client.events = event_stream()
        monkeypatch.setattr(engine, "_process_container_start_event", failing_process)
        engine._running = True
        try:
            await asyncio.wait_for(engine._event_listener_loop(), timeout=10)
        finally:
            release.set()

        assert_error_with_traceback(
            caplog, "Error processing event from queue: cannot process", RuntimeError
        )
        assert 1 in recorded_sleeps

    @pytest.mark.asyncio
    async def test_container_start_event_error(self, caplog, engine, docker_client):
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        docker_client.info_errors[container.id] = RuntimeError("inspect failed")
        event = {"Actor": {"ID": container.id, "Attributes": {"name": "web"}}}

        await engine._process_container_start_event(event)

        assert_error_with_traceback(
            caplog, "Error processing container start event: inspect failed", RuntimeError
        )

    @pytest.mark.asyncio
    async def test_notification_worker_error(self, caplog, monkeypatch):
        manager = NotificationManager()
        manager._running = True

        async def failing_process(event):
            manager._running = False
            raise RuntimeError("cannot notify")

        monkeypatch.setattr(manager, "_process_notification", failing_process)
        await manager._notification_queue.put(_make_event("restart"))

        await manager._notification_worker()

        assert_error_with_traceback(caplog, "Error in notification worker: cannot notify", RuntimeError)


# ---------------------------------------------------------------------------
# Fallback and failure paths that were previously unexercised
# ---------------------------------------------------------------------------


class TestUnexercisedFallbackLogging:
    def test_data_directory_fallback_is_logged(self, caplog, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        manager = ConfigManager.__new__(ConfigManager)
        manager.DATA_DIR = blocker / "data"

        manager._ensure_data_directory()

        assert record_starting(caplog, "Failed to create data directory: ", logging.ERROR)
        record_for(caplog, "Using fallback data directory: data", logging.WARNING)

    def test_unreadable_events_file_is_logged(self, caplog):
        config_manager.EVENTS_FILE.write_text("{not json")

        assert config_manager._load_events() == []

        [record] = [r for r in caplog.records if r.getMessage().startswith("Failed to load events from disk: ")]
        assert record.levelno == logging.WARNING
        assert not record.exc_info

    def test_init_data_file_failure(self, caplog, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        target = blocker / "config.json"

        assert init_data_file(target, {}, "config.json") is False

        record_starting(caplog, f"Failed to create config.json at {target}: ", logging.ERROR)

    def test_initialize_defaults_directory_fallback(self, caplog, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        data_dir = blocker / "data"

        initialize_defaults(data_dir)

        record_starting(caplog, f"Failed to create data directory {data_dir}: ", logging.ERROR)
        record_for(caplog, "Using fallback data directory: data", logging.WARNING)

    def test_initialize_defaults_logs_directory_failure(self, caplog, tmp_path):
        (tmp_path / "logs").write_text("not a directory")

        initialize_defaults(tmp_path)

        record_starting(caplog, "Failed to create logs directory: ", logging.ERROR)

    def test_reset_to_defaults_write_failure(self, caplog, tmp_path):
        missing = tmp_path / "missing"

        reset_to_defaults(missing)

        for filename in ("config.json", "events.json", "quarantine.json", "maintenance.json"):
            record_starting(caplog, f"Failed to reset {filename}: ", logging.ERROR)
        record_for(caplog, "Reset to defaults complete", logging.INFO)

    def test_http_health_check_without_ip_address(self, caplog):
        container = MagicMock()
        container.name = "web"
        container.attrs = {"NetworkSettings": {"Networks": {}}}
        client = DockerClientWrapper.__new__(DockerClientWrapper)

        assert client.check_http_health(container, "http://localhost/health") is False

        record_for(caplog, "Cannot get IP address for container web", logging.WARNING)

    def test_http_health_check_request_failure(self, caplog):
        container = MagicMock()
        container.name = "web"
        container.reload.side_effect = RuntimeError("reload failed")
        client = DockerClientWrapper.__new__(DockerClientWrapper)

        assert client.check_http_health(container, "http://localhost/health") is False

        record_for(caplog, "HTTP health check failed for web: reload failed", logging.WARNING)

    @pytest.mark.asyncio
    async def test_notification_preparation_error(self, caplog, isolated_config_manager, monkeypatch):
        manager = NotificationManager()
        _configure_webhook(isolated_config_manager)
        monkeypatch.setattr(manager, "_send_webhook", MagicMock(side_effect=RuntimeError("prep failed")))

        await manager._process_notification(_make_event("restart"))

        assert_error_without_traceback(caplog, "Error preparing notification for webhook: prep failed")

    @pytest.mark.asyncio
    async def test_gathered_notification_failure(self, caplog, isolated_config_manager, monkeypatch):
        manager = NotificationManager()
        _configure_webhook(isolated_config_manager)
        monkeypatch.setattr(manager, "_send_webhook", AsyncMock(side_effect=RuntimeError("send failed")))

        await manager._process_notification(_make_event("restart"))

        assert_error_without_traceback(caplog, "Notification failed: send failed")

    @pytest.mark.asyncio
    async def test_test_notification_failure(self, caplog, isolated_config_manager, monkeypatch):
        manager = NotificationManager()
        _configure_webhook(isolated_config_manager)
        monkeypatch.setattr(manager, "_send_webhook", AsyncMock(side_effect=RuntimeError("send failed")))
        service_name = isolated_config_manager.get_config().notifications.services[0].name

        result = await manager.test_notification(service_name)

        assert result == {"success": False, "message": "Failed to send test notification: send failed"}
        assert_error_without_traceback(caplog, "Failed to send test notification: send failed")


# ---------------------------------------------------------------------------
# Webhook failure logging: the response body is awaited while building the message
# ---------------------------------------------------------------------------


class _BodyResponse(_FakeResponse):
    def __init__(self, status: int, body: str | Exception):
        super().__init__(status)
        self._body = body

    async def text(self) -> str:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _BodySession(_FakeSession):
    def __init__(self, response: _BodyResponse):
        super().__init__(response.status)
        self._response = response

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._response


class TestWebhookFailureLogging:
    @pytest.mark.asyncio
    async def test_error_status_includes_response_body(self, caplog, isolated_config_manager):
        manager = NotificationManager()
        manager._session = _BodySession(_BodyResponse(502, "upstream said no"))
        _configure_webhook(isolated_config_manager)

        await manager._process_notification(_make_event("restart"))

        assert_error_without_traceback(caplog, "Webhook failed with status 502: upstream said no")

    @pytest.mark.asyncio
    async def test_unreadable_response_body_falls_into_the_generic_handler(
        self, caplog, isolated_config_manager
    ):
        manager = NotificationManager()
        manager._session = _BodySession(_BodyResponse(500, RuntimeError("body unreadable")))
        _configure_webhook(isolated_config_manager)

        await manager._process_notification(_make_event("restart"))

        assert_error_without_traceback(caplog, "Failed to send webhook notification: body unreadable")
        assert not [r for r in caplog.records if r.getMessage().startswith("Webhook failed with status")]

    @pytest.mark.asyncio
    async def test_body_is_read_even_when_error_logging_is_disabled(self, isolated_config_manager):
        body_reads = []

        class _CountingResponse(_BodyResponse):
            async def text(self) -> str:
                body_reads.append(1)
                return "ignored"

        manager = NotificationManager()
        manager._session = _BodySession(_CountingResponse(500, ""))
        _configure_webhook(isolated_config_manager)
        logging.getLogger("app.notifications.notification_manager").setLevel(logging.CRITICAL)
        try:
            await manager._process_notification(_make_event("restart"))
        finally:
            logging.getLogger("app.notifications.notification_manager").setLevel(logging.NOTSET)

        assert body_reads == [1]
