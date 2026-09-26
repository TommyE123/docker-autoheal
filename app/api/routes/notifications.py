"""Notification configuration and service management endpoints."""

from fastapi import APIRouter, HTTPException

from app.api import state
from app.config.config_manager import NotificationService, config_manager

router = APIRouter()


@router.get("/api/notifications/config")
async def get_notifications_config():
    """Get current notification configuration"""
    try:
        config = config_manager.get_config()
        return {
            "enabled": config.notifications.enabled,
            "services": [service.model_dump() for service in config.notifications.services],
            "event_filters": config.notifications.event_filters
        }
    except Exception as e:
        state.logger.error(f"Error getting notifications config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/notifications/config")
async def update_notifications_config(notifications_config: dict):
    """Update notification configuration"""
    try:
        config = config_manager.get_config()

        if "enabled" in notifications_config:
            config.notifications.enabled = notifications_config["enabled"]

        if "event_filters" in notifications_config:
            config.notifications.event_filters = notifications_config["event_filters"]

        if "services" in notifications_config:
            # Parse and validate services
            services = []
            for service_data in notifications_config["services"]:
                service = NotificationService(**service_data)
                services.append(service)
            config.notifications.services = services

        config_manager.update_config(config)

        return {
            "status": "success",
            "message": "Notification configuration updated",
            "config": {
                "enabled": config.notifications.enabled,
                "services": [s.model_dump() for s in config.notifications.services],
                "event_filters": config.notifications.event_filters
            }
        }
    except Exception as e:
        state.logger.error(f"Error updating notifications config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/notifications/services")
async def add_notification_service(service: dict):
    """Add a new notification service"""
    try:
        config = config_manager.get_config()

        # Validate and create service
        new_service = NotificationService(**service)

        # Check if service with same name already exists
        for existing in config.notifications.services:
            if existing.name == new_service.name:
                raise HTTPException(status_code=400, detail=f"Service with name '{new_service.name}' already exists")

        config.notifications.services.append(new_service)
        config_manager.update_config(config)

        return {
            "status": "success",
            "message": f"Notification service '{new_service.name}' added",
            "service": new_service.model_dump()
        }
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error adding notification service: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/notifications/services/{service_name}")
async def update_notification_service(service_name: str, service: dict):
    """Update an existing notification service"""
    try:
        config = config_manager.get_config()

        # Find and update service
        updated_service = None
        found = False
        for i, existing in enumerate(config.notifications.services):
            if existing.name == service_name:
                # Preserve name if not provided
                if "name" not in service:
                    service["name"] = service_name
                updated_service = NotificationService(**service)
                config.notifications.services[i] = updated_service
                found = True
                break

        if not found:
            raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

        config_manager.update_config(config)

        return {
            "status": "success",
            "message": f"Notification service '{service_name}' updated",
            "service": updated_service.model_dump()
        }
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error updating notification service: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/notifications/services/{service_name}")
async def delete_notification_service(service_name: str):
    """Delete a notification service"""
    try:
        config = config_manager.get_config()

        # Find and remove service
        original_count = len(config.notifications.services)
        config.notifications.services = [
            s for s in config.notifications.services if s.name != service_name
        ]

        if len(config.notifications.services) == original_count:
            raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

        config_manager.update_config(config)

        return {
            "status": "success",
            "message": f"Notification service '{service_name}' deleted"
        }
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error deleting notification service: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/notifications/test/{service_name}")
async def test_notification_service(service_name: str):
    """Send a test notification to verify configuration"""
    try:
        result = await state.notification_manager.test_notification(service_name)

        if result["success"]:
            return {
                "status": "success",
                "message": result["message"]
            }
        raise HTTPException(status_code=400, detail=result["message"])

    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error testing notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))
