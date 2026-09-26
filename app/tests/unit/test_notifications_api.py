"""
Unit tests for the notification configuration and service CRUD endpoints in
``app/api/routes/notifications.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client - ``config_manager`` is isolated per test
(see ``conftest.py``).
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routes.notifications import (
    add_notification_service,
    delete_notification_service,
    get_notifications_config,
    update_notification_service,
    update_notifications_config,
)
from app.api.routes.notifications import test_notification_service as api_test_notification_service
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
            NotificationService(
                name="Slack", type="slack", url="https://example.invalid/slack"
            )
        ]
        config_manager.update_config(config)

        result = await get_notifications_config()

        assert result["enabled"] is True
        assert result["services"][0]["name"] == "Slack"

    async def test_update_notifications_config_updates_enabled_and_filters(self):
        result = await update_notifications_config(
            {"enabled": True, "event_filters": ["restart"]}
        )

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

    async def test_update_notification_service_unknown_name_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            await update_notification_service("does-not-exist", {"type": "webhook"})

        assert exc_info.value.status_code == 404

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
            "app.api.state.notification_manager.test_notification", fake_test_notification
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
            "app.api.state.notification_manager.test_notification", fake_test_notification
        )

        with pytest.raises(HTTPException) as exc_info:
            await api_test_notification_service("Webhook")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Service 'Webhook' not found"
