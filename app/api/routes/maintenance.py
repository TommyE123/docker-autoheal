"""Maintenance mode endpoints."""

import logging

from fastapi import APIRouter

from app.config.config_manager import config_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/maintenance/enable")
async def enable_maintenance_mode():
    """Enable maintenance mode - stops all auto-healing"""
    config_manager.enable_maintenance_mode()
    maintenance_start = config_manager.get_maintenance_start_time()
    logger.info("Maintenance mode enabled")
    return {
        "status": "success",
        "message": "Maintenance mode enabled",
        "maintenance_mode": True,
        "maintenance_start_time": maintenance_start.isoformat() if maintenance_start else None,
    }


@router.post("/api/maintenance/disable")
async def disable_maintenance_mode():
    """Disable maintenance mode - resumes auto-healing"""
    config_manager.disable_maintenance_mode()
    logger.info("Maintenance mode disabled")
    return {
        "status": "success",
        "message": "Maintenance mode disabled",
        "maintenance_mode": False,
    }


@router.get("/api/maintenance/status")
async def get_maintenance_status():
    """Get current maintenance mode status"""
    maintenance_start = config_manager.get_maintenance_start_time()
    return {
        "maintenance_mode": config_manager.is_maintenance_mode(),
        "maintenance_start_time": maintenance_start.isoformat() if maintenance_start else None,
    }
