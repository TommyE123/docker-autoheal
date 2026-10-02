"""Event log endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.config.config_manager import AutoHealEvent, config_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/events")
async def get_events(
    limit: Annotated[int, Query(ge=1)] = 100,
    event_type: str | None = None,
    container: str | None = None,
):
    """
    Get recent auto-heal events.

    ``event_type`` keeps only events of that exact type and ``container`` keeps
    events whose container name contains the text (case-insensitive). Both are
    applied before ``limit``, which then keeps the most recent matches.
    """
    try:
        events = config_manager.get_events()
        if event_type is not None:
            events = [event for event in events if event.event_type == event_type]
        if container is not None:
            needle = container.lower()
            events = [event for event in events if needle in event.container_name.lower()]
        events = events[-limit:]
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
        logger.error(f"Error getting events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/events")
async def clear_events():
    """Clear all events from the log"""
    try:
        config_manager.clear_events()
        return {"status": "success", "message": "All events cleared"}
    except Exception as e:
        logger.error(f"Error clearing events: {e}")
        raise HTTPException(status_code=500, detail=str(e))
