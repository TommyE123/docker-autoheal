"""Container management endpoints."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from app.api import state
from app.api.models import ContainerInfo, ContainerSelectionRequest
from app.config.config_manager import AutoHealEvent, config_manager

if TYPE_CHECKING:
    from app.docker_client.docker_client_wrapper import DockerClientWrapper

logger = logging.getLogger(__name__)

router = APIRouter()


def _inspect_containers(docker_client: DockerClientWrapper, include_stopped: bool) -> list[tuple]:
    """List containers and inspect each one (blocking: run in a worker thread).

    ``containers.list()`` has just inspected every container it returns, so the
    per-container ``reload()`` in ``get_container_info`` would be a redundant
    second round trip.
    """
    containers = docker_client.list_containers(all_containers=include_stopped)
    return [(c, docker_client.get_container_info(c, refresh=False)) for c in containers]


@router.get("/api/containers", response_model=list[ContainerInfo])
async def list_containers(include_stopped: bool = False):
    """List all containers with their monitoring status"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        inspected = await asyncio.to_thread(_inspect_containers, docker_client, include_stopped)
        result = []

        # Get Uptime Kuma configuration
        config = config_manager.get_config()
        uptime_kuma_enabled = config.uptime_kuma.enabled

        # Use the uptime_kuma_monitor from monitoring_engine if available
        uptime_kuma_monitor = None
        if uptime_kuma_enabled and monitoring_engine:
            uptime_kuma_monitor = monitoring_engine.uptime_kuma_monitor

        for container, info in inspected:
            if not info:
                continue

            stable_id = info.get("stable_id")  # Get stable identifier

            # Check if monitored
            monitored = False
            if monitoring_engine:
                monitored = monitoring_engine.should_monitor_container(container, info)

            # Restart counts and quarantine are stored per replica (recovery_id)
            recovery_id = info.get("recovery_id")

            # Check if quarantined (use recovery_id, matching how quarantine is stored)
            quarantined = config_manager.is_quarantined(recovery_id)

            # Get locally tracked restart count (persists across container recreations)
            locally_tracked_restarts = config_manager.get_total_restart_count(recovery_id)

            # Check for Uptime Kuma mapping and status using uptime_kuma_monitor
            uptime_kuma_status = None
            uptime_kuma_monitor_name = None

            if uptime_kuma_enabled and uptime_kuma_monitor:
                # Check if container is mapped
                if uptime_kuma_monitor.is_container_mapped(stable_id):
                    # Get the monitor name from mappings
                    for mapping in config.uptime_kuma_mappings:
                        if mapping.container_id == stable_id:
                            uptime_kuma_monitor_name = mapping.monitor_friendly_name
                            break

                    # Get cached status from uptime_kuma_monitor
                    uptime_kuma_status = uptime_kuma_monitor.get_container_status(stable_id)
            elif uptime_kuma_enabled and not uptime_kuma_monitor:
                # Uptime-Kuma integration enabled but monitor not initialized
                uptime_kuma_status = 4  # Indicate unknown status
            else:
                uptime_kuma_status = 5  # Integration disabled

            container_info = ContainerInfo(
                id=info.get("id"),
                name=info.get("name"),
                image=info.get("image"),
                status=info.get("status"),
                state=info.get("state", {}),
                labels=info.get("labels", {}),
                health=info.get("health"),
                restart_count=locally_tracked_restarts,  # Use locally tracked count instead of Docker's
                monitored=monitored,
                quarantined=quarantined,
                uptime_kuma_status=uptime_kuma_status,
                uptime_kuma_monitor_name=uptime_kuma_monitor_name,
            )
            result.append(container_info)

        return result
    except Exception as e:
        logger.error("Error listing containers: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/containers/{container_id}",
    responses={500: {"description": "Container could not be inspected or identified"}},
)
async def get_container_details(container_id: str):
    """Get detailed information about a specific container"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        container = await asyncio.to_thread(docker_client.get_container, container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = await asyncio.to_thread(docker_client.get_container_info, container)
        if not info:
            raise HTTPException(status_code=500, detail="Unable to inspect container")

        # Use stable_id for tracking (persists across recreations)
        full_container_id = info.get("full_id")
        container_name = info.get("name")
        stable_id = info.get("stable_id")
        # Restart counts and quarantine are stored per replica (recovery_id)
        recovery_id = info.get("recovery_id")
        if (
            full_container_id is None
            or container_name is None
            or stable_id is None
            or recovery_id is None
        ):
            raise HTTPException(status_code=500, detail="Unable to resolve container identifiers")

        # Get locally tracked restart counts (using recovery_id)
        recent_restart_count = config_manager.get_restart_count(
            recovery_id, config_manager.get_config().restart.max_restarts_window_seconds
        )
        total_restart_count = config_manager.get_total_restart_count(recovery_id)

        # Check monitoring status
        monitored = False
        if monitoring_engine:
            monitored = monitoring_engine.should_monitor_container(container, info)

        # Check if quarantined (use recovery_id, matching how quarantine is stored)
        quarantined = config_manager.is_quarantined(recovery_id)

        # Get custom health check (by stable_id first for correctness, then fallback to name/ID for legacy compat)
        custom_hc = config_manager.get_custom_health_check(stable_id)
        if not custom_hc:
            custom_hc = config_manager.get_custom_health_check(container_name)
        if not custom_hc:
            custom_hc = config_manager.get_custom_health_check(full_container_id)

        # Override restart_count in info with locally tracked count
        info["restart_count"] = total_restart_count
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting container details: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
    else:
        return {
            **info,
            "monitored": monitored,
            "quarantined": quarantined,
            "recent_restart_count": recent_restart_count,
            "total_restart_count": total_restart_count,
            "custom_health_check": custom_hc,
        }


def _stable_id_from_info(info: dict | None) -> str | None:
    """
    Stable identifier for persisting a container selection.

    Uses the ``monitoring.id`` label, then the Compose project and service, then the
    name. None when the container could not be inspected or has none of these.
    """
    if not info:
        return None
    labels = info.get("labels", {})
    monitoring_id = labels.get("monitoring.id")
    compose_project = labels.get("com.docker.compose.project")
    compose_service = labels.get("com.docker.compose.service")

    if monitoring_id:
        return monitoring_id
    if compose_project and compose_service:
        return f"{compose_project}_{compose_service}"
    return info.get("name")


@router.post("/api/containers/select")
async def update_container_selection(request: ContainerSelectionRequest):
    """Enable or disable auto-heal for specific containers"""
    try:
        logger.debug(
            "Container selection request: containers=%s, enabled=%s",
            request.container_ids,
            request.enabled,
        )

        docker_client = state.docker_client
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        # Resolve every container first. The config snapshot is taken only after
        # the last await, so concurrent selection requests cannot overwrite each
        # other's updates with a stale copy.
        resolved: dict[str, dict | None] = {}
        for cid in request.container_ids:
            container = await asyncio.to_thread(docker_client.get_container, cid)
            resolved[cid] = (
                await asyncio.to_thread(docker_client.get_container_info, container)
                if container
                else None
            )

        config = config_manager.get_config()

        if request.enabled:
            # Add to selected list - resolve stable identifiers for persistence
            for cid in request.container_ids:
                # Try to get container to resolve its stable identifier
                info = resolved[cid]
                container_name = info.get("name") if info else None
                stable_id = _stable_id_from_info(info)
                if info is not None and stable_id is not None:
                    # Store by stable_id for persistence across recreations
                    if stable_id not in config.containers.selected:
                        config.containers.selected.append(stable_id)
                        logger.debug(
                            "Added container '%s' with stable_id '%s' to selected list (ID: %s)",
                            container_name,
                            stable_id,
                            cid,
                        )

                    # Remove from excluded if present (check stable_id, name, and ID)
                    for identifier in [
                        i for i in (stable_id, container_name, cid) if i is not None
                    ]:
                        if identifier in config.containers.excluded:
                            config.containers.excluded.remove(identifier)
                            logger.debug("Removed '%s' from excluded list", identifier)
                else:
                    # Fallback: store the identifier as-is
                    if cid not in config.containers.selected:
                        config.containers.selected.append(cid)
                        logger.debug(
                            "Added container %s to selected list (container not resolved)",
                            cid,
                        )
                    if cid in config.containers.excluded:
                        config.containers.excluded.remove(cid)
        else:
            # Add to excluded list - resolve stable identifiers for persistence
            for cid in request.container_ids:
                # Try to get container to resolve its stable identifier
                info = resolved[cid]
                container_name = info.get("name") if info else None
                stable_id = _stable_id_from_info(info)
                if info is not None and stable_id is not None:
                    # Store by stable_id for persistence across recreations
                    if stable_id not in config.containers.excluded:
                        config.containers.excluded.append(stable_id)
                        logger.debug(
                            "Added container '%s' with stable_id '%s' to excluded list (ID: %s)",
                            container_name,
                            stable_id,
                            cid,
                        )

                    # Remove from selected if present (check stable_id, name, and ID)
                    for identifier in [
                        i for i in (stable_id, container_name, cid) if i is not None
                    ]:
                        if identifier in config.containers.selected:
                            config.containers.selected.remove(identifier)
                            logger.debug("Removed '%s' from selected list", identifier)
                else:
                    # Fallback: store the identifier as-is
                    if cid not in config.containers.excluded:
                        config.containers.excluded.append(cid)
                        logger.debug(
                            "Added container %s to excluded list (container not resolved)",
                            cid,
                        )
                    if cid in config.containers.selected:
                        config.containers.selected.remove(cid)

        config_manager.update_config(config)

        logger.info(
            "Container selection updated: %s container(s) %s",
            len(request.container_ids),
            "enabled" if request.enabled else "disabled",
        )

        return {
            "status": "success",
            "message": f"Updated {len(request.container_ids)} containers",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating container selection: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/containers/{container_id}/restart")
async def restart_container_manual(container_id: str):
    """Manually restart a container"""
    docker_client = state.docker_client
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        container = await asyncio.to_thread(docker_client.get_container, container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        success = await asyncio.to_thread(docker_client.restart_container, container)

        if success:
            return {
                "status": "success",
                "message": f"Container {container_id} restarted",
            }
        raise HTTPException(status_code=500, detail="Failed to restart container")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error restarting container: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/api/containers/{container_id}/unquarantine",
    responses={500: {"description": "Container could not be inspected or identified"}},
)
async def unquarantine_container(container_id: str):
    """Remove container from quarantine"""
    docker_client = state.docker_client
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        # Get the container to resolve stable_id
        container = await asyncio.to_thread(docker_client.get_container, container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = await asyncio.to_thread(docker_client.get_container_info, container)
        if not info:
            raise HTTPException(status_code=500, detail="Unable to inspect container")
        container_name = info.get("name")
        recovery_id = info.get("recovery_id")
        full_container_id = info.get("full_id")
        if container_name is None or recovery_id is None or full_container_id is None:
            raise HTTPException(status_code=500, detail="Unable to resolve container identifiers")

        # Remove from quarantine using recovery_id (matches how quarantine is stored)
        config_manager.unquarantine_container(recovery_id)

        # Clear restart history using recovery_id
        config_manager.clear_restart_history(recovery_id)

        event = AutoHealEvent(
            timestamp=datetime.now(UTC),
            container_name=f"{container_name} ({recovery_id})",
            container_id=full_container_id,  # Store current ID for reference
            event_type="unquarantine",
            restart_count=0,
            status="success",
            message="Container un-quarantined by user request",
        )
        config_manager.add_event(event)

        # Send notification for quarantine event
        await state.notification_manager.send_event_notification(event)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error unquarantining container: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
    else:
        return {
            "status": "success",
            "message": f"Container {container_name} removed from quarantine",
        }
