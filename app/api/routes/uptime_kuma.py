"""Uptime-Kuma integration endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from app.api import state
from app.config.config_manager import UptimeKumaMapping, config_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/uptime-kuma/test-connection")
async def test_uptime_kuma_connection(config_data: dict):
    """Test connection to Uptime-Kuma server"""
    # Imported here (rather than at module level) so that patching
    # ``app.uptime_kuma.uptime_kuma_client.UptimeKumaClient`` in tests is
    # picked up on every call.
    from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient

    try:
        client = UptimeKumaClient(
            config_data.get('server_url'),
            config_data.get('api_token'),      # password (API key or user password)
            config_data.get('username', '')    # username (optional, empty for API key)
        )
        success = await client.connect()

        if success:
            # Fetch monitors to validate full access
            monitors = await client.get_all_monitors()
            return {
                "success": True,
                "message": "Connection successful",
                "monitor_count": len(monitors)
            }
        return {
            "success": False,
            "message": "Connection failed - check URL and credentials"
        }
    except Exception as e:
        logger.error(f"Uptime-Kuma connection test failed: {e}")
        return {
            "success": False,
            "message": f"Connection error: {e!s}"
        }


@router.post("/api/uptime-kuma/enable")
async def enable_uptime_kuma_integration(integration_config: dict):
    """Enable Uptime-Kuma integration and fetch monitors"""
    from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient
    from app.uptime_kuma.matching import match_uptime_kuma_monitors

    docker_client = state.docker_client
    monitoring_engine = state.monitoring_engine
    try:
        # Update configuration
        config = config_manager.get_config()
        config.uptime_kuma.enabled = True
        config.uptime_kuma.server_url = integration_config.get('server_url')
        config.uptime_kuma.username = integration_config.get('username', '')
        config.uptime_kuma.api_token = integration_config.get('api_token')
        config.uptime_kuma.auto_restart_on_down = integration_config.get('auto_restart_on_down', True)

        # Fetch monitors
        client = UptimeKumaClient(
            config.uptime_kuma.server_url,
            config.uptime_kuma.api_token,      # password (API key or user password)
            config.uptime_kuma.username        # username (optional, empty for API key)
        )
        monitors = await client.get_all_monitors()

        # Perform auto-mapping
        containers = docker_client.list_containers(all_containers=False)
        container_infos = []
        for container in containers:
            info = docker_client.get_container_info(container)
            if not info or not info.get("stable_id"):
                continue
            container_infos.append(info)

        matches = match_uptime_kuma_monitors(container_infos, monitors)
        auto_mappings = [
            UptimeKumaMapping(
                container_id=match["container_id"],
                monitor_friendly_name=match["monitor_friendly_name"],
                auto_mapped=True,
            )
            for match in matches
        ]

        # Add auto-mappings to config
        config.uptime_kuma_mappings = auto_mappings
        config_manager.update_config(config)

        # Restart Uptime-Kuma monitor
        if hasattr(monitoring_engine, 'uptime_kuma_monitor'):
            await monitoring_engine.uptime_kuma_monitor.stop()
            await monitoring_engine.uptime_kuma_monitor.start()

        logger.info(
            f"Uptime-Kuma integration enabled with {len(auto_mappings)} auto-mappings "
            f"using monitoring interval: {config.monitor.interval_seconds}s"
        )

        return {
            "success": True,
            "monitors": monitors,
            "auto_mappings": [m.model_dump() for m in auto_mappings]
        }

    except Exception as e:
        logger.error(f"Failed to enable Uptime-Kuma: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            config.uptime_kuma.api_token,      # password (API key or user password)
            config.uptime_kuma.username        # username (optional, empty for API key)
        )
        monitors = await client.get_all_monitors()
        return {"monitors": monitors}
    except Exception as e:
        logger.error(f"Failed to fetch Uptime-Kuma monitors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/uptime-kuma/mappings")
async def get_uptime_kuma_mappings():
    """Get all container-to-monitor mappings"""
    config = config_manager.get_config()
    return {
        "mappings": [m.model_dump() for m in config.uptime_kuma_mappings]
    }


@router.post("/api/uptime-kuma/mappings")
async def create_uptime_kuma_mapping(mapping: dict):
    """Create a new container-to-monitor mapping"""
    docker_client = state.docker_client
    try:
        # Get the container to resolve stable_id
        container = docker_client.get_container(mapping['container_id'])
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        info = docker_client.get_container_info(container)
        stable_id = info.get("stable_id")

        config = config_manager.get_config()
        new_mapping = UptimeKumaMapping(
            container_id=stable_id,
            monitor_friendly_name=mapping['monitor_friendly_name'],
            auto_mapped=False
        )

        config.uptime_kuma_mappings.append(new_mapping)
        config_manager.update_config(config)

        logger.info(
            f"Created Uptime-Kuma mapping: {mapping['container_id']} -> {mapping['monitor_friendly_name']}"
        )

        return {"success": True, "mapping": new_mapping.model_dump()}
    except Exception as e:
        logger.error(f"Failed to create Uptime-Kuma mapping: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/uptime-kuma/mappings/{container_id}")
async def delete_uptime_kuma_mapping(container_id: str):
    """Delete a container-to-monitor mapping (container_id is actually stable_id)"""
    try:
        config = config_manager.get_config()
        config.uptime_kuma_mappings = [
            m for m in config.uptime_kuma_mappings if m.container_id != container_id
        ]
        config_manager.update_config(config)

        logger.info(f"Deleted Uptime-Kuma mapping for stable_id: {container_id}")

        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to delete Uptime-Kuma mapping: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/uptime-kuma/disable")
async def disable_uptime_kuma_integration():
    """Disable Uptime-Kuma integration"""
    monitoring_engine = state.monitoring_engine
    try:
        config = config_manager.get_config()
        config.uptime_kuma.enabled = False
        config_manager.update_config(config)

        # Stop monitoring
        if hasattr(monitoring_engine, 'uptime_kuma_monitor'):
            await monitoring_engine.uptime_kuma_monitor.stop()

        logger.info("Uptime-Kuma integration disabled")

        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to disable Uptime-Kuma: {e}")
        raise HTTPException(status_code=500, detail=str(e))
