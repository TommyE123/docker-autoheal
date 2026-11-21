"""Custom health check management endpoints."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api import state
from app.api.errors import DockerClientDep  # noqa: TC001  (FastAPI resolves it at runtime)
from app.config.config_manager import HealthCheckConfig, config_manager
from app.monitor.health import CustomCheckLookup, find_custom_health_check

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/healthchecks")
async def add_health_check(docker_client: DockerClientDep, health_check: HealthCheckConfig):
    """Add custom health check for a container"""
    monitoring_engine = state.monitoring_engine
    # Get the container to resolve its stable identifier
    container = await asyncio.to_thread(docker_client.get_container, health_check.container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    info = await asyncio.to_thread(docker_client.get_container_info, container)
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
    return {
        "status": "success",
        "message": f"Health check added for container {health_check.container_id}",
    }


async def _lookup_health_check(
    docker_client: DockerClientDep, container_id: str
) -> CustomCheckLookup:
    """
    Resolve a container and find its custom health check, as the monitoring engine does

    Raises:
        HTTPException: 404 for an unknown container, 500 when it cannot be identified, 409 when
            the only check found is stored under the container's name and that name is also
            another container's stable identifier, 503 when Docker could not be listed to rule
            that out
    """
    monitoring_engine = state.monitoring_engine
    # Get the container to resolve its stable identifier
    container = await asyncio.to_thread(docker_client.get_container, container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    info = await asyncio.to_thread(docker_client.get_container_info, container)
    if not info:
        raise HTTPException(status_code=500, detail="Unable to inspect container")

    stable_id = monitoring_engine.get_stable_identifier(info) if monitoring_engine else None
    if not stable_id:
        raise HTTPException(status_code=500, detail="Unable to resolve container stable identifier")

    lookup = await asyncio.to_thread(find_custom_health_check, docker_client, info, stable_id)
    if lookup.check is None and lookup.skipped_name is not None:
        name = lookup.skipped_name
        if lookup.unverifiable:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Could not list Docker containers to confirm that the custom health check "
                    f"stored under '{name}' belongs to this container. Try again once Docker "
                    "responds."
                ),
            )
        raise HTTPException(
            status_code=409,
            detail=(
                f"The custom health check stored under '{name}' is ambiguous: '{name}' is this "
                f"container's name and also the stable identifier of "
                f"{', '.join(repr(owner) for owner in lookup.conflicting)}. Set a unique "
                "monitoring.id label on that container so the key identifies one container."
            ),
        )
    return lookup


_LOOKUP_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {"description": "The only check found may belong to another container"},
    503: {"description": "Docker could not be listed to attribute the check"},
}


@router.get("/api/healthchecks/{container_id}", responses=_LOOKUP_RESPONSES)
async def get_health_check(docker_client: DockerClientDep, container_id: str):
    """Get custom health check for a container"""
    # Looked up by stable_id, then the name, then the full Docker ID for checks persisted
    # under those before stable-ID storage
    lookup = await _lookup_health_check(docker_client, container_id)
    if not lookup.check:
        raise HTTPException(
            status_code=404,
            detail="No custom health check found for this container",
        )
    return lookup.check


@router.delete("/api/healthchecks/{container_id}", responses=_LOOKUP_RESPONSES)
async def delete_health_check(docker_client: DockerClientDep, container_id: str):
    """Delete custom health check for a container"""
    # Remove whichever key the check is actually stored under, the same one the monitoring
    # engine applies
    lookup = await _lookup_health_check(docker_client, container_id)
    if lookup.key is not None:
        config_manager.remove_custom_health_check(lookup.key)
    return {
        "status": "success",
        "message": f"Health check removed for container {container_id}",
    }


@router.get("/api/healthchecks")
async def list_health_checks():
    """List all custom health checks"""
    return config_manager.get_all_custom_health_checks()
