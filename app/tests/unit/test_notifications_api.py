"""
Unit tests for the notification configuration and service CRUD endpoints in
``app/api/routes/notifications.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client - ``config_manager`` is isolated per test
(see ``conftest.py``).
"""

from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes.notifications import (
    add_notification_service,
    delete_notification_service,
    get_notifications_config,
    update_notification_service,
    update_notifications_config,
)
from app.api.routes.notifications import (
    test_notification_service as api_test_notification_service,
)
from app.api.routes.notifications import (
    test_unsaved_notification_service as api_test_unsaved_notification_service,
)
from app.config.config_manager import NotificationService, config_manager


@pytest.mark.asyncio
class TestNotificationsConfig:
    async def test_get_notifications_config_returns_defaults(self):
        result = await get_notifications_config()

        assert result["enabled"] is False
        assert result["services"] == []
        assert "restart" in result["event_filters"]

    async def test_get_notifications_config_reflects_current_state(self):
        config = config_manager.get_config()
        config.notifications.enabled = True
        config.notifications.services = [
            NotificationService(name="Slack", type="slack", url="https://example.invalid/slack")
        ]
        config_manager.update_config(config)

        result = await get_notifications_config()

        assert result["enabled"] is True
        assert result["services"][0]["name"] == "Slack"

    async def test_update_notifications_config_updates_enabled_and_filters(self):
        result = await update_notifications_config({"enabled": True, "event_filters": ["restart"]})

        assert result["status"] == "success"
        updated = config_manager.get_config()
        assert updated.notifications.enabled is True
        assert updated.notifications.event_filters == ["restart"]

    async def test_update_notifications_config_replaces_services(self):
        result = await update_notifications_config(
            {
                "services": [
                    {
                        "name": "Webhook",
                        "type": "webhook",
                        "url": "https://example.invalid/hook",
                    }
                ]
            }
        )

        assert result["config"]["services"][0]["name"] == "Webhook"
        assert config_manager.get_config().notifications.services[0].name == "Webhook"

    async def test_update_notifications_config_invalid_service_returns_500(self):
        # Missing the required "type" field, so NotificationService(**data) raises.
        with pytest.raises(HTTPException) as exc_info:
            await update_notifications_config({"services": [{"name": "Missing Type"}]})

        assert exc_info.value.status_code == 500

    async def test_get_notifications_config_error_returns_500(self, monkeypatch):
        monkeypatch.setattr(
            config_manager,
            "get_config",
            MagicMock(side_effect=RuntimeError("config unavailable")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_notifications_config()

        assert exc_info.value.status_code == 500

    async def test_update_notifications_config_persistence_error_returns_500(self, monkeypatch):
        monkeypatch.setattr(
            config_manager,
            "update_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_notifications_config({"enabled": True})

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestNotificationServiceCrud:
    async def test_add_notification_service_success(self):
        result = await add_notification_service(
            {
                "name": "Webhook",
                "type": "webhook",
                "url": "https://example.invalid/hook",
            }
        )

        assert result["status"] == "success"
        assert result["service"]["name"] == "Webhook"
        assert config_manager.get_config().notifications.services[0].name == "Webhook"

    async def test_add_notification_service_validation_error_hides_credentials(self, caplog):
        with pytest.raises(HTTPException) as exc_info:
            await add_notification_service(
                {
                    "name": "Ntfy",
                    "type": "ntfy",
                    "topic": "alerts",
                    "access_token": {"value": "tk_leak_check"},
                }
            )

        assert exc_info.value.status_code == 500
        assert "access_token" in exc_info.value.detail
        assert "tk_leak_check" not in exc_info.value.detail
        assert "Error adding notification service" in caplog.text
        assert "tk_leak_check" not in caplog.text

    async def test_add_notification_service_duplicate_name_returns_400(self):
        await add_notification_service(
            {
                "name": "Webhook",
                "type": "webhook",
                "url": "https://example.invalid/hook",
            }
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_notification_service(
                {
                    "name": "Webhook",
                    "type": "slack",
                    "url": "https://example.invalid/other",
                }
            )

        assert exc_info.value.status_code == 400
        assert len(config_manager.get_config().notifications.services) == 1

    async def test_add_notification_service_with_a_different_existing_name(self):
        await add_notification_service(
            {"name": "Webhook", "type": "webhook", "url": "https://example.invalid/hook"}
        )

        await add_notification_service(
            {"name": "Slack", "type": "slack", "url": "https://example.invalid/slack"}
        )

        names = [s.name for s in config_manager.get_config().notifications.services]
        assert names == ["Webhook", "Slack"]

    async def test_add_notification_service_invalid_payload_returns_500(self):
        with pytest.raises(HTTPException) as exc_info:
            await add_notification_service({"name": "Missing Type"})

        assert exc_info.value.status_code == 500

    async def test_update_notification_service_preserves_name_when_omitted(self):
        await add_notification_service(
            {
                "name": "Webhook",
                "type": "webhook",
                "url": "https://example.invalid/hook",
            }
        )

        result = await update_notification_service(
            "Webhook", {"type": "webhook", "url": "https://example.invalid/updated"}
        )

        assert result["status"] == "success"
        assert result["service"]["name"] == "Webhook"
        assert result["service"]["url"] == "https://example.invalid/updated"
        stored = config_manager.get_config().notifications.services[0]
        assert stored.url == "https://example.invalid/updated"

    async def test_update_notification_service_uses_provided_name(self):
        await add_notification_service(
            {
                "name": "Webhook",
                "type": "webhook",
                "url": "https://example.invalid/hook",
            }
        )

        result = await update_notification_service(
            "Webhook",
            {
                "name": "Renamed webhook",
                "type": "webhook",
                "url": "https://example.invalid/updated",
            },
        )

        assert result["service"]["name"] == "Renamed webhook"

    async def test_update_notification_service_skips_non_matching_services(self):
        await add_notification_service(
            {"name": "Webhook", "type": "webhook", "url": "https://example.invalid/hook"}
        )
        await add_notification_service(
            {"name": "Slack", "type": "slack", "url": "https://example.invalid/slack"}
        )

        result = await update_notification_service(
            "Slack", {"type": "slack", "url": "https://example.invalid/new"}
        )

        assert result["service"]["url"] == "https://example.invalid/new"
        services = config_manager.get_config().notifications.services
        assert services[0].url == "https://example.invalid/hook"
        assert services[1].url == "https://example.invalid/new"

    async def test_update_notification_service_unknown_name_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            await update_notification_service("does-not-exist", {"type": "webhook"})

        assert exc_info.value.status_code == 404

    async def test_update_notification_service_persistence_error_returns_500(self, monkeypatch):
        await add_notification_service(
            {
                "name": "Webhook",
                "type": "webhook",
                "url": "https://example.invalid/hook",
            }
        )
        monkeypatch.setattr(
            config_manager,
            "update_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_notification_service("Webhook", {"type": "webhook"})

        assert exc_info.value.status_code == 500

    async def test_delete_notification_service_success(self):
        await add_notification_service(
            {
                "name": "Webhook",
                "type": "webhook",
                "url": "https://example.invalid/hook",
            }
        )

        result = await delete_notification_service("Webhook")

        assert result["status"] == "success"
        assert config_manager.get_config().notifications.services == []

    async def test_delete_notification_service_unknown_name_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            await delete_notification_service("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_delete_notification_service_persistence_error_returns_500(self, monkeypatch):
        await add_notification_service(
            {
                "name": "Webhook",
                "type": "webhook",
                "url": "https://example.invalid/hook",
            }
        )
        monkeypatch.setattr(
            config_manager,
            "update_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await delete_notification_service("Webhook")

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestNotificationServiceTest:
    """Delegation only; delivery itself is covered by NotificationManager's own tests."""

    async def test_success_delegates_to_notification_manager(self, monkeypatch):
        fake_test_notification = AsyncMock(
            return_value={
                "success": True,
                "message": "Test notification sent successfully",
            }
        )
        monkeypatch.setattr(
            "app.api.state.notification_manager.test_notification",
            fake_test_notification,
        )

        result = await api_test_notification_service("Webhook")

        assert result == {
            "status": "success",
            "message": "Test notification sent successfully",
        }
        fake_test_notification.assert_awaited_once_with("Webhook")

    async def test_failure_result_raises_400_with_manager_message(self, monkeypatch):
        fake_test_notification = AsyncMock(
            return_value={"success": False, "message": "Service 'Webhook' not found"}
        )
        monkeypatch.setattr(
            "app.api.state.notification_manager.test_notification",
            fake_test_notification,
        )

        with pytest.raises(HTTPException) as exc_info:
            await api_test_notification_service("Webhook")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Service 'Webhook' not found"

    async def test_manager_error_returns_500(self, monkeypatch):
        monkeypatch.setattr(
            "app.api.state.notification_manager.test_notification",
            AsyncMock(
                side_effect=RuntimeError("manager unavailable https://example.invalid/secret")
            ),
        )

        with pytest.raises(HTTPException) as exc_info:
            await api_test_notification_service("Webhook")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to send test notification, see logs"

    async def test_manager_error_is_not_logged_with_its_text(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "app.api.state.notification_manager.test_notification",
            AsyncMock(side_effect=RuntimeError("boom https://example.invalid/secret")),
        )

        with pytest.raises(HTTPException):
            await api_test_notification_service("Webhook")

        assert "secret" not in caplog.text
        assert "RuntimeError" in caplog.text


@pytest.mark.asyncio
class TestUnsavedNotificationServiceTest:
    """Delegation only; delivery itself is covered by NotificationManager's own tests."""

    PAYLOAD: ClassVar[dict[str, str]] = {
        "name": "Draft",
        "type": "webhook",
        "url": "https://example.invalid/secret-hook",
    }

    async def test_success_sends_without_saving(self, monkeypatch):
        fake_send_test = AsyncMock(
            return_value={"success": True, "message": "Test notification sent successfully"}
        )
        monkeypatch.setattr("app.api.state.notification_manager.send_test", fake_send_test)

        result = await api_test_unsaved_notification_service(dict(self.PAYLOAD))

        assert result == {"status": "success", "message": "Test notification sent successfully"}
        fake_send_test.assert_awaited_once()
        sent = fake_send_test.await_args_list[0].args[0]
        assert sent.name == "Draft"
        assert sent.url == self.PAYLOAD["url"]
        assert config_manager.get_config().notifications.services == []

    async def test_failure_result_raises_400(self, monkeypatch):
        monkeypatch.setattr(
            "app.api.state.notification_manager.send_test",
            AsyncMock(return_value={"success": False, "message": "not delivered"}),
        )

        with pytest.raises(HTTPException) as exc_info:
            await api_test_unsaved_notification_service(dict(self.PAYLOAD))

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "not delivered"

    async def test_invalid_payload_returns_422_without_echoing_values(self):
        with pytest.raises(HTTPException) as exc_info:
            await api_test_unsaved_notification_service(
                {"type": "webhook", "url": "https://example.invalid/secret-hook"}
            )

        assert exc_info.value.status_code == 422
        assert "secret-hook" not in str(exc_info.value.detail)

    async def test_manager_error_returns_generic_500(self, monkeypatch):
        monkeypatch.setattr(
            "app.api.state.notification_manager.send_test",
            AsyncMock(side_effect=RuntimeError("boom secret-hook")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await api_test_unsaved_notification_service(dict(self.PAYLOAD))

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to send test notification, see logs"
        assert "secret-hook" not in str(exc_info.value.detail)
