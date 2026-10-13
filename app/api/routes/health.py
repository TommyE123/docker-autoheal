"""Health & status endpoints."""

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api import state
from app.api.models import SystemStatus
from app.api.routes.containers import _inspect_containers
from app.config.config_manager import config_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint for the service itself"""
    docker_connected = (
        await asyncio.to_thread(state.docker_client.is_connected) if state.docker_client else False
    )
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "docker_connected": docker_connected,
        "monitoring_active": state.monitoring_engine._running if state.monitoring_engine else False,
    }


# PWA manifest route - testing
@router.get("/manifest.webmanifest", include_in_schema=False)
async def get_manifest():
    """Serve PWA manifest"""
    return FileResponse("static/manifest.webmanifest", media_type="application/manifest+json")


@router.get("/api/status", response_model=SystemStatus)
async def get_system_status():
    """Get overall system status"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        config = config_manager.get_config()
        # Get ALL containers (including stopped) for accurate count
        # One worker-thread hop for all Docker round trips (list + inspect each,
        # then connectivity); the per-container inspect is already fresh from list.
        inspected = (
            await asyncio.to_thread(_inspect_containers, docker_client, True)
            if docker_client
            else []
        )
        docker_connected = (
            await asyncio.to_thread(docker_client.is_connected) if docker_client else False
        )
        containers = [container for container, _info in inspected]
        monitored_count = 0

        # Count monitored containers
        for container, info in inspected:
            if monitoring_engine and info:
                if monitoring_engine.should_monitor_container(container, info):
                    monitored_count += 1

        maintenance_start = config_manager.get_maintenance_start_time()
        return SystemStatus(
            monitoring_active=monitoring_engine._running if monitoring_engine else False,
            docker_connected=docker_connected,
            total_containers=len(containers),
            monitored_containers=monitored_count,
            quarantined_containers=len(config_manager.get_quarantined_containers()),
            maintenance_mode=config_manager.is_maintenance_mode(),
            maintenance_start_time=maintenance_start.isoformat() if maintenance_start else None,
            config=config,
        )
    except Exception as e:
        logger.error("Error getting system status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
