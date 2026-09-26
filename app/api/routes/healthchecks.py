"""Custom health check management endpoints."""

from fastapi import APIRouter, HTTPException

from app.api import state
from app.config.config_manager import HealthCheckConfig, config_manager

router = APIRouter()


@router.post("/api/healthchecks")
async def add_health_check(health_check: HealthCheckConfig):
    """Add custom health check for a container"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        # Get the container to resolve its stable identifier
        container = docker_client.get_container(health_check.container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = docker_client.get_container_info(container)
        if not info:
            raise HTTPException(status_code=500, detail="Unable to inspect container")

        stable_id = monitoring_engine.get_stable_identifier(info) if monitoring_engine else None
        if not stable_id:
            raise HTTPException(status_code=500, detail="Unable to resolve container stable identifier")

        # Store by stable_id so the check survives container recreation
        # (image updates, `docker compose up --force-recreate`, etc.),
        # matching how restart counts and quarantine status are tracked.
        health_check.container_id = stable_id

        config_manager.add_custom_health_check(health_check)
        return {"status": "success", "message": f"Health check added for container {health_check.container_id}"}
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error adding health check: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/healthchecks/{container_id}")
async def get_health_check(container_id: str):
    """Get custom health check for a container"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        # Get the container to resolve its stable identifier
        container = docker_client.get_container(container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = docker_client.get_container_info(container)
        if not info:
            raise HTTPException(status_code=500, detail="Unable to inspect container")

        stable_id = monitoring_engine.get_stable_identifier(info) if monitoring_engine else None
        if not stable_id:
            raise HTTPException(status_code=500, detail="Unable to resolve container stable identifier")

        health_check = config_manager.get_custom_health_check(stable_id)
        if not health_check:
            # Fall back to the container's current full Docker ID for checks
            # persisted before stable-ID storage that haven't been re-added.
            health_check = config_manager.get_custom_health_check(container.id)
        if not health_check:
            raise HTTPException(status_code=404, detail="No custom health check found for this container")
        return health_check
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error getting health check: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/healthchecks/{container_id}")
async def delete_health_check(container_id: str):
    """Delete custom health check for a container"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        # Get the container to resolve its stable identifier
        container = docker_client.get_container(container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = docker_client.get_container_info(container)
        if not info:
            raise HTTPException(status_code=500, detail="Unable to inspect container")

        stable_id = monitoring_engine.get_stable_identifier(info) if monitoring_engine else None
        if not stable_id:
            raise HTTPException(status_code=500, detail="Unable to resolve container stable identifier")

        # Remove whichever key the check is actually stored under: the
        # stable ID, or (for checks persisted before stable-ID storage)
        # the container's current full Docker ID.
        remove_key = stable_id
        if not config_manager.get_custom_health_check(remove_key):
            remove_key = container.id
        config_manager.remove_custom_health_check(remove_key)
        return {"status": "success", "message": f"Health check removed for container {container_id}"}
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error deleting health check: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/healthchecks")
async def list_health_checks():
    """List all custom health checks"""
    return config_manager.get_all_custom_health_checks()
