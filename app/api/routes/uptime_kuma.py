"""Uptime-Kuma integration endpoints."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api import state
from app.config.config_manager import UptimeKumaMapping, config_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _stripped(value: Any) -> Any:
    """Strip surrounding whitespace from string values; pass anything else through."""
    return value.strip() if isinstance(value, str) else value


@router.post("/api/uptime-kuma/test-connection")
async def test_uptime_kuma_connection(config_data: dict):
    """Test connection to Uptime-Kuma server"""
    # Imported here (rather than at module level) so that patching
    # ``app.uptime_kuma.uptime_kuma_client.UptimeKumaClient`` in tests is
    # picked up on every call.
    from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient

    try:
        client = UptimeKumaClient(
            _stripped(config_data.get("server_url")) or "",
            _stripped(config_data.get("api_token")) or "",  # password (API key or user password)
            _stripped(config_data.get("username", "")),  # username (optional, empty for API key)
        )
        success = await client.connect()

        if success:
            # Fetch monitors to validate full access
            monitors = await client.get_all_monitors() or []
            return {
                "success": True,
                "message": "Connection successful",
                "monitor_count": len(monitors),
            }
    except Exception as e:
        logger.error("Uptime-Kuma connection test failed: %s", e)
        return {"success": False, "message": f"Connection error: {e!s}"}
    else:
        return {
            "success": False,
            "message": "Connection failed - check URL and credentials",
        }


@router.post(
    "/api/uptime-kuma/enable",
    responses={400: {"description": "server_url and api_token are required"}},
)
async def enable_uptime_kuma_integration(integration_config: dict):
    """Enable Uptime-Kuma integration and fetch monitors"""
    from app.uptime_kuma.matching import MonitorInfo, match_uptime_kuma_monitors
    from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient

    server_url = integration_config.get("server_url")
    api_token = integration_config.get("api_token")
    if not (
        isinstance(server_url, str)
        and server_url.strip()
        and isinstance(api_token, str)
        and api_token.strip()
    ):
        raise HTTPException(status_code=400, detail="server_url and api_token are required")
    server_url = server_url.strip()
    api_token = api_token.strip()

    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        username = _stripped(integration_config.get("username", ""))

        # Fetch monitors
        client = UptimeKumaClient(
            server_url,
            api_token,  # password (API key or user password)
            username,  # username (optional, empty for API key)
        )
        monitors = await client.get_all_monitors() or []

        # Perform auto-mapping
        if docker_client is None:
            raise RuntimeError("Docker client not initialized")
        containers = await asyncio.to_thread(docker_client.list_containers, all_containers=False)
        container_infos = []
        for container in containers:
            info = await asyncio.to_thread(docker_client.get_container_info, container)
            if not info or not info.get("stable_id"):
                continue
            container_infos.append(info)

        # The matcher only needs each monitor's friendly name.
        monitor_infos: list[MonitorInfo] = [{"friendly_name": m["friendly_name"]} for m in monitors]
        matches = match_uptime_kuma_monitors(container_infos, monitor_infos)
        auto_mappings = [
            UptimeKumaMapping(
                container_id=match["container_id"],
                monitor_friendly_name=match["monitor_friendly_name"],
                auto_mapped=True,
            )
            for match in matches
        ]

        # Applied in one mutate() after all the awaits above, so a change made
        # meanwhile (such as a manual mapping) is merged rather than overwritten.
        with config_manager.mutate() as config:
            config.uptime_kuma.enabled = True
            config.uptime_kuma.server_url = server_url
            config.uptime_kuma.username = username
            config.uptime_kuma.api_token = api_token
            config.uptime_kuma.auto_restart_on_down = integration_config.get(
                "auto_restart_on_down", True
            )

            # Manual mappings are explicit user decisions: keep them and let them
            # win over any freshly generated auto-mapping for the same container.
            manual_mappings = [
                mapping for mapping in config.uptime_kuma_mappings if not mapping.auto_mapped
            ]
            manual_container_ids = {mapping.container_id for mapping in manual_mappings}
            auto_mappings = [
                mapping
                for mapping in auto_mappings
                if mapping.container_id not in manual_container_ids
            ]

            config.uptime_kuma_mappings = manual_mappings + auto_mappings

        # Restart Uptime-Kuma monitor
        if monitoring_engine and monitoring_engine.uptime_kuma_monitor:
            await monitoring_engine.uptime_kuma_monitor.stop()
            await monitoring_engine.uptime_kuma_monitor.start()

        logger.info(
            "Uptime-Kuma integration enabled with %s auto-mappings using monitoring interval: %ss",
            len(auto_mappings),
            config.monitor.interval_seconds,
        )

        return {
            "success": True,
            "monitors": monitors,
            "auto_mappings": [m.model_dump() for m in auto_mappings],
        }

    except Exception as e:
        logger.error("Failed to enable Uptime-Kuma: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/uptime-kuma/monitors")
async def get_uptime_kuma_monitors():
    """Get all Uptime-Kuma monitors"""
    from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient

    config = config_manager.get_config()

    if not config.uptime_kuma.enabled:
        raise HTTPException(status_code=400, detail="Uptime-Kuma integration not enabled")

    try:
        client = UptimeKumaClient(
            config.uptime_kuma.server_url,
            config.uptime_kuma.api_token,  # password (API key or user password)
            config.uptime_kuma.username,  # username (optional, empty for API key)
        )
        monitors = await client.get_all_monitors() or []
    except Exception as e:
        logger.error("Failed to fetch Uptime-Kuma monitors: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
    else:
        return {"monitors": monitors}


@router.get("/api/uptime-kuma/mappings")
async def get_uptime_kuma_mappings():
    """Get all container-to-monitor mappings"""
    config = config_manager.get_config()
    return {"mappings": [m.model_dump() for m in config.uptime_kuma_mappings]}


@router.post(
    "/api/uptime-kuma/mappings",
    responses={500: {"description": "Container could not be mapped"}},
)
async def create_uptime_kuma_mapping(mapping: dict):
    """Create a new container-to-monitor mapping"""
    docker_client = state.docker_client
    try:
        # Get the container to resolve stable_id
        if docker_client is None:
            raise RuntimeError("Docker client not initialized")
        container = await asyncio.to_thread(docker_client.get_container, mapping["container_id"])
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = await asyncio.to_thread(docker_client.get_container_info, container)
        stable_id = info.get("stable_id")
        if stable_id is None:
            raise HTTPException(
                status_code=500, detail="Unable to resolve container stable identifier"
            )

        config = config_manager.get_config()
        new_mapping = UptimeKumaMapping(
            container_id=stable_id,
            monitor_friendly_name=mapping["monitor_friendly_name"],
            auto_mapped=False,
        )

        config.uptime_kuma_mappings.append(new_mapping)
        config_manager.update_config(config)

        logger.info(
            "Created Uptime-Kuma mapping: %s -> %s",
            mapping["container_id"],
            mapping["monitor_friendly_name"],
        )

        return {"success": True, "mapping": new_mapping.model_dump()}
    except Exception as e:
        logger.error("Failed to create Uptime-Kuma mapping: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/uptime-kuma/mappings/{container_id}")
async def delete_uptime_kuma_mapping(container_id: str):
    """Delete a container-to-monitor mapping (container_id is actually stable_id)"""
    try:
        config = config_manager.get_config()
        config.uptime_kuma_mappings = [
            m for m in config.uptime_kuma_mappings if m.container_id != container_id
        ]
        config_manager.update_config(config)

        logger.info("Deleted Uptime-Kuma mapping for stable_id: %s", container_id)
    except Exception as e:
        logger.error("Failed to delete Uptime-Kuma mapping: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
    else:
        return {"success": True}


@router.post("/api/uptime-kuma/disable")
async def disable_uptime_kuma_integration():
    """Disable Uptime-Kuma integration"""
    monitoring_engine = state.monitoring_engine
    try:
        config = config_manager.get_config()
        config.uptime_kuma.enabled = False
        config_manager.update_config(config)

        # Stop monitoring
        if monitoring_engine and monitoring_engine.uptime_kuma_monitor:
            await monitoring_engine.uptime_kuma_monitor.stop()

        logger.info("Uptime-Kuma integration disabled")
    except Exception as e:
        logger.error("Failed to disable Uptime-Kuma: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
    else:
        return {"success": True}
