"""Health & status endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api import state
from app.api.models import SystemStatus
from app.config.config_manager import config_manager

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint for the service itself"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "docker_connected": state.docker_client.is_connected() if state.docker_client else False,
        "monitoring_active": state.monitoring_engine._running if state.monitoring_engine else False
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
        containers = docker_client.list_containers(all_containers=True) if docker_client else []
        monitored_count = 0

        # Count monitored containers
        for container in containers:
            info = docker_client.get_container_info(container)
            if monitoring_engine and info:
                if monitoring_engine.should_monitor_container(container, info):
                    monitored_count += 1

        maintenance_start = config_manager.get_maintenance_start_time()
        return SystemStatus(
            monitoring_active=monitoring_engine._running if monitoring_engine else False,
            docker_connected=docker_client.is_connected() if docker_client else False,
            total_containers=len(containers),
            monitored_containers=monitored_count,
            quarantined_containers=len(config_manager.get_quarantined_containers()),
            maintenance_mode=config_manager.is_maintenance_mode(),
            maintenance_start_time=maintenance_start.isoformat() if maintenance_start else None,
            config=config
        )
    except Exception as e:
        state.logger.error(f"Error getting system status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
