"""Event log endpoints."""

from fastapi import APIRouter, HTTPException

from app.api import state
from app.config.config_manager import AutoHealEvent, config_manager

router = APIRouter()


@router.get("/api/events")
async def get_events(limit: int = 100):
    """Get recent auto-heal events"""
    try:
        events = config_manager.get_events(limit)
        return [
            {
                "timestamp": (
                    event.timestamp.isoformat()
                    if isinstance(event, AutoHealEvent)
                    else event.timestamp
                ),
                "container_id": event.container_id,
                "container_name": event.container_name,
                "event_type": event.event_type,
                "restart_count": event.restart_count,
                "status": event.status,
                "message": event.message
            }
            for event in events
        ]
    except Exception as e:
        state.logger.error(f"Error getting events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/events")
async def clear_events():
    """Clear all events from the log"""
    try:
        config_manager.clear_events()
        return {"status": "success", "message": "All events cleared"}
    except Exception as e:
        state.logger.error(f"Error clearing events: {e}")
        raise HTTPException(status_code=500, detail=str(e))
