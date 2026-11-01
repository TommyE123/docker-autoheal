"""Notification configuration and service management endpoints."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from app.api import state
from app.config.config_manager import NotificationService, config_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/notifications/config")
async def get_notifications_config():
    """Get current notification configuration"""
    config = config_manager.get_config()
    return {
        "enabled": config.notifications.enabled,
        "services": [service.model_dump() for service in config.notifications.services],
        "event_filters": config.notifications.event_filters,
    }


@router.put("/api/notifications/config")
async def update_notifications_config(notifications_config: dict):
    """Update notification configuration"""
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
            "event_filters": config.notifications.event_filters,
        },
    }


@router.post("/api/notifications/services")
async def add_notification_service(service: dict):
    """Add a new notification service"""
    config = config_manager.get_config()

    # Validate and create service
    new_service = NotificationService(**service)

    # Check if service with same name already exists
    for existing in config.notifications.services:
        if existing.name == new_service.name:
            raise HTTPException(
                status_code=400,
                detail=f"Service with name '{new_service.name}' already exists",
            )

    config.notifications.services.append(new_service)
    config_manager.update_config(config)

    return {
        "status": "success",
        "message": f"Notification service '{new_service.name}' added",
        "service": new_service.model_dump(),
    }


@router.put("/api/notifications/services/{service_name}")
async def update_notification_service(service_name: str, service: dict):
    """Update an existing notification service"""
    config = config_manager.get_config()

    # Find and update service
    updated_service = None
    for i, existing in enumerate(config.notifications.services):
        if existing.name == service_name:
            # Preserve name if not provided
            if "name" not in service:
                service["name"] = service_name
            updated_service = NotificationService(**service)
            config.notifications.services[i] = updated_service
            break

    if updated_service is None:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

    config_manager.update_config(config)

    return {
        "status": "success",
        "message": f"Notification service '{service_name}' updated",
        "service": updated_service.model_dump(),
    }


@router.delete("/api/notifications/services/{service_name}")
async def delete_notification_service(service_name: str):
    """Delete a notification service"""
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
        "message": f"Notification service '{service_name}' deleted",
    }


@router.post(
    "/api/notifications/test",
    responses={
        400: {"description": "Test notification was not delivered"},
        422: {"description": "Service values are invalid"},
        500: {"description": "Unexpected error while sending the test notification"},
    },
)
async def test_unsaved_notification_service(service: Annotated[Any, Body()]):
    """Send a test notification from unsaved service values, without persisting them"""
    # The body is bound as ``Any`` and checked by hand: FastAPI's own validation errors echo the
    # submitted input, which can contain tokens and webhook URLs.
    if not isinstance(service, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    try:
        parsed = NotificationService.model_validate(service)
    except ValidationError as e:
        # Report field locations and messages only: pydantic errors echo the submitted input.
        errors = [{"loc": err["loc"], "msg": err["msg"]} for err in e.errors(include_input=False)]
        raise HTTPException(status_code=422, detail=errors) from None

    try:
        result = await state.notification_manager.send_test(parsed)

        if result["success"]:
            return {"status": "success", "message": result["message"]}
        raise HTTPException(status_code=400, detail=result["message"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error testing notification: %s", type(e).__name__, exc_info=False)
        raise HTTPException(
            status_code=500, detail="Failed to send test notification, see logs"
        ) from None


@router.post(
    "/api/notifications/test/{service_name}",
    responses={
        400: {"description": "Service not found, disabled, or the test was not delivered"},
        500: {"description": "Unexpected error while sending the test notification"},
    },
)
async def test_notification_service(service_name: str):
    """Send a test notification to verify configuration"""
    try:
        result = await state.notification_manager.test_notification(service_name)

        if result["success"]:
            return {"status": "success", "message": result["message"]}
        raise HTTPException(status_code=400, detail=result["message"])

    except HTTPException:
        raise
    except Exception as e:
        # Name the exception type only: the message can embed the service URL or token.
        logger.error("Error testing notification: %s", type(e).__name__, exc_info=False)
        raise HTTPException(
            status_code=500, detail="Failed to send test notification, see logs"
        ) from None
