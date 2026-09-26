"""Container management endpoints."""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException

from app.api import state
from app.api.models import ContainerInfo, ContainerSelectionRequest
from app.config.config_manager import AutoHealEvent, config_manager

router = APIRouter()


@router.get("/api/containers", response_model=List[ContainerInfo])
async def list_containers(include_stopped: bool = False):
    """List all containers with their monitoring status"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        containers = docker_client.list_containers(all_containers=include_stopped)
        result = []

        # Get Uptime Kuma configuration
        config = config_manager.get_config()
        uptime_kuma_enabled = config.uptime_kuma.enabled

        # Use the uptime_kuma_monitor from monitoring_engine if available
        uptime_kuma_monitor = None
        if uptime_kuma_enabled and monitoring_engine and hasattr(monitoring_engine, 'uptime_kuma_monitor'):
            uptime_kuma_monitor = monitoring_engine.uptime_kuma_monitor

        for container in containers:
            info = docker_client.get_container_info(container)
            if not info:
                continue

            stable_id = info.get("stable_id")  # Get stable identifier

            # Check if monitored
            monitored = False
            if monitoring_engine:
                monitored = monitoring_engine.should_monitor_container(container, info)

            # Check if quarantined (use stable_id, matching how quarantine is stored)
            quarantined = config_manager.is_quarantined(stable_id)

            # Get locally tracked restart count (persists across container recreations)
            locally_tracked_restarts = config_manager.get_total_restart_count(stable_id)

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
            elif not uptime_kuma_enabled:
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
                uptime_kuma_monitor_name=uptime_kuma_monitor_name
            )
            result.append(container_info)

        return result
    except Exception as e:
        state.logger.error(f"Error listing containers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/containers/{container_id}")
async def get_container_details(container_id: str):
    """Get detailed information about a specific container"""
    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        container = docker_client.get_container(container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = docker_client.get_container_info(container)

        # Use stable_id for tracking (persists across recreations)
        full_container_id = info.get("full_id")
        container_name = info.get("name")
        stable_id = info.get("stable_id")

        # Get locally tracked restart counts (using stable_id)
        recent_restart_count = config_manager.get_restart_count(
            stable_id,
            config_manager.get_config().restart.max_restarts_window_seconds
        )
        total_restart_count = config_manager.get_total_restart_count(stable_id)

        # Check monitoring status
        monitored = False
        if monitoring_engine:
            monitored = monitoring_engine.should_monitor_container(container, info)

        # Check if quarantined (use stable_id, matching how quarantine is stored)
        quarantined = config_manager.is_quarantined(stable_id)

        # Get custom health check (by stable_id first for correctness, then fallback to name/ID for legacy compat)
        custom_hc = config_manager.get_custom_health_check(stable_id)
        if not custom_hc:
            custom_hc = config_manager.get_custom_health_check(container_name)
        if not custom_hc:
            custom_hc = config_manager.get_custom_health_check(full_container_id)

        # Override restart_count in info with locally tracked count
        info["restart_count"] = total_restart_count

        return {
            **info,
            "monitored": monitored,
            "quarantined": quarantined,
            "recent_restart_count": recent_restart_count,
            "total_restart_count": total_restart_count,
            "custom_health_check": custom_hc
        }
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error getting container details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/containers/select")
async def update_container_selection(request: ContainerSelectionRequest):
    """Enable or disable auto-heal for specific containers"""
    try:
        state.logger.debug(
            f"Container selection request: containers={request.container_ids}, enabled={request.enabled}"
        )
        config = config_manager.get_config()

        if request.enabled:
            # Add to selected list - resolve stable identifiers for persistence
            for cid in request.container_ids:
                # Try to get container to resolve its stable identifier
                container = state.docker_client.get_container(cid)
                if container:
                    info = state.docker_client.get_container_info(container)
                    container_name = info.get("name")

                    # Get stable identifier (handles all edge cases)
                    labels = info.get("labels", {})
                    monitoring_id = labels.get("monitoring.id")
                    compose_project = labels.get("com.docker.compose.project")
                    compose_service = labels.get("com.docker.compose.service")

                    if monitoring_id:
                        stable_id = monitoring_id
                    elif compose_project and compose_service:
                        stable_id = f"{compose_project}_{compose_service}"
                    else:
                        stable_id = container_name

                    # Store by stable_id for persistence across recreations
                    if stable_id not in config.containers.selected:
                        config.containers.selected.append(stable_id)
                        state.logger.debug(
                            f"Added container '{container_name}' with stable_id '{stable_id}' to selected list (ID: {cid})"
                        )

                    # Remove from excluded if present (check stable_id, name, and ID)
                    for identifier in [stable_id, container_name, cid]:
                        if identifier in config.containers.excluded:
                            config.containers.excluded.remove(identifier)
                            state.logger.debug(f"Removed '{identifier}' from excluded list")
                else:
                    # Fallback: store the identifier as-is
                    if cid not in config.containers.selected:
                        config.containers.selected.append(cid)
                        state.logger.debug(f"Added container {cid} to selected list (container not resolved)")
                    if cid in config.containers.excluded:
                        config.containers.excluded.remove(cid)
        else:
            # Add to excluded list - resolve stable identifiers for persistence
            for cid in request.container_ids:
                # Try to get container to resolve its stable identifier
                container = state.docker_client.get_container(cid)
                if container:
                    info = state.docker_client.get_container_info(container)
                    container_name = info.get("name")

                    # Get stable identifier
                    labels = info.get("labels", {})
                    monitoring_id = labels.get("monitoring.id")
                    compose_project = labels.get("com.docker.compose.project")
                    compose_service = labels.get("com.docker.compose.service")

                    if monitoring_id:
                        stable_id = monitoring_id
                    elif compose_project and compose_service:
                        stable_id = f"{compose_project}_{compose_service}"
                    else:
                        stable_id = container_name

                    # Store by stable_id for persistence across recreations
                    if stable_id not in config.containers.excluded:
                        config.containers.excluded.append(stable_id)
                        state.logger.debug(
                            f"Added container '{container_name}' with stable_id '{stable_id}' to excluded list (ID: {cid})"
                        )

                    # Remove from selected if present (check stable_id, name, and ID)
                    for identifier in [stable_id, container_name, cid]:
                        if identifier in config.containers.selected:
                            config.containers.selected.remove(identifier)
                            state.logger.debug(f"Removed '{identifier}' from selected list")
                else:
                    # Fallback: store the identifier as-is
                    if cid not in config.containers.excluded:
                        config.containers.excluded.append(cid)
                        state.logger.debug(f"Added container {cid} to excluded list (container not resolved)")
                    if cid in config.containers.selected:
                        config.containers.selected.remove(cid)

        config_manager.update_config(config)

        state.logger.info(
            f"Container selection updated: {len(request.container_ids)} container(s) "
            f"{'enabled' if request.enabled else 'disabled'}"
        )

        return {"status": "success", "message": f"Updated {len(request.container_ids)} containers"}
    except Exception as e:
        state.logger.error(f"Error updating container selection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/containers/{container_id}/restart")
async def restart_container_manual(container_id: str):
    """Manually restart a container"""
    docker_client = state.docker_client
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        container = docker_client.get_container(container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        success = docker_client.restart_container(container)

        if success:
            return {"status": "success", "message": f"Container {container_id} restarted"}
        raise HTTPException(status_code=500, detail="Failed to restart container")
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error restarting container: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/containers/{container_id}/unquarantine")
async def unquarantine_container(container_id: str):
    """Remove container from quarantine"""
    docker_client = state.docker_client
    try:
        if not docker_client:
            raise HTTPException(status_code=500, detail="Docker client not initialized")

        # Get the container to resolve stable_id
        container = docker_client.get_container(container_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = docker_client.get_container_info(container)
        container_name = info.get("name")
        stable_id = info.get("stable_id")

        # Remove from quarantine using stable_id (matches how quarantine is stored)
        config_manager.unquarantine_container(stable_id)

        # Clear restart history using stable_id
        config_manager.clear_restart_history(stable_id)

        event = AutoHealEvent(
            timestamp=datetime.now(timezone.utc),
            container_name=f"{container_name} ({stable_id})",
            container_id=info.get("full_id"),  # Store current ID for reference
            event_type="unquarantine",
            restart_count=0,
            status="success",
            message="Container un-quarantined by user request"
        )
        config_manager.add_event(event)

        # Send notification for quarantine event
        await state.notification_manager.send_event_notification(event)

        return {"status": "success", "message": f"Container {container_name} removed from quarantine"}
    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error unquarantining container: {e}")
        raise HTTPException(status_code=500, detail=str(e))
