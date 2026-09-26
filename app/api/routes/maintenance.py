"""Maintenance mode endpoints."""

from fastapi import APIRouter, HTTPException

from app.api import state
from app.config.config_manager import config_manager

router = APIRouter()


@router.post("/api/maintenance/enable")
async def enable_maintenance_mode():
    """Enable maintenance mode - stops all auto-healing"""
    try:
        config_manager.enable_maintenance_mode()
        state.logger.info("Maintenance mode enabled")
        return {
            "status": "success",
            "message": "Maintenance mode enabled",
            "maintenance_mode": True,
            "maintenance_start_time": config_manager.get_maintenance_start_time().isoformat()
        }
    except Exception as e:
        state.logger.error(f"Error enabling maintenance mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/maintenance/disable")
async def disable_maintenance_mode():
    """Disable maintenance mode - resumes auto-healing"""
    try:
        config_manager.disable_maintenance_mode()
        state.logger.info("Maintenance mode disabled")
        return {
            "status": "success",
            "message": "Maintenance mode disabled",
            "maintenance_mode": False
        }
    except Exception as e:
        state.logger.error(f"Error disabling maintenance mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/maintenance/status")
async def get_maintenance_status():
    """Get current maintenance mode status"""
    try:
        maintenance_start = config_manager.get_maintenance_start_time()
        return {
            "maintenance_mode": config_manager.is_maintenance_mode(),
            "maintenance_start_time": maintenance_start.isoformat() if maintenance_start else None
        }
    except Exception as e:
        state.logger.error(f"Error getting maintenance status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
