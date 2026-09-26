"""
Configuration endpoints.

Also owns ``/api/config/observability`` - logically a configuration endpoint,
even though it originally lived under the "Event Log Endpoints" section in
the pre-split ``app/api/api.py`` (issue #321 split routes along logical
domains rather than preserving that historical placement).
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api import state
from app.config.config_manager import AutoHealConfig, MonitorConfig, RestartConfig, config_manager

router = APIRouter()


@router.get("/api/config", response_model=AutoHealConfig)
async def get_config():
    """Get current configuration"""
    return config_manager.get_config()


@router.put("/api/config")
async def update_config(config: AutoHealConfig):
    """Update configuration"""
    try:
        config_manager.update_config(config)
        return {"status": "success", "message": "Configuration updated"}
    except Exception as e:
        state.logger.error(f"Error updating config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/config/monitor")
async def update_monitor_config(monitor_config: MonitorConfig):
    """Update monitor configuration"""
    try:
        config = config_manager.get_config()
        config.monitor = monitor_config
        config_manager.update_config(config)
        return {"status": "success", "message": "Monitor configuration updated"}
    except Exception as e:
        state.logger.error(f"Error updating monitor config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/config/restart")
async def update_restart_config(restart_config: RestartConfig):
    """Update restart configuration"""
    try:
        config = config_manager.get_config()
        config.restart = restart_config
        config_manager.update_config(config)
        return {"status": "success", "message": "Restart configuration updated"}
    except Exception as e:
        state.logger.error(f"Error updating restart config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/config/export")
async def export_config():
    """Export configuration as JSON"""
    try:
        config_json = config_manager.export_config()

        # Return as downloadable file
        return JSONResponse(
            content=json.loads(config_json),
            headers={
                "Content-Disposition": f"attachment; filename=autoheal-config-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
            }
        )
    except Exception as e:
        state.logger.error(f"Error exporting config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/config/import")
async def import_config(file: UploadFile = File(...)):
    """Import configuration from JSON file"""
    try:
        content = await file.read()
        config_json = content.decode('utf-8')

        config_manager.import_config(config_json)

        return {"status": "success", "message": "Configuration imported successfully"}
    except Exception as e:
        state.logger.error(f"Error importing config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/config/observability")
async def update_observability_config(observability_config: dict):
    """Update observability configuration including log level"""
    try:
        config = config_manager.get_config()

        # Update observability config
        if "log_level" in observability_config:
            level_name = observability_config["log_level"]
            config.observability.log_level = level_name

            # Update log level directly without importing main
            level_map = {
                'DEBUG': logging.DEBUG,
                'INFO': logging.INFO,
                'WARNING': logging.WARNING,
                'ERROR': logging.ERROR,
                'CRITICAL': logging.CRITICAL
            }
            level = level_map.get(level_name.upper(), logging.INFO)

            # Set root logger level
            logging.getLogger().setLevel(level)

            # Disable uvicorn access logs completely
            logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
            logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
            logging.getLogger("uvicorn").setLevel(logging.WARNING)

            state.logger.info(f"Log level changed to: {level_name}")

        if "prometheus_enabled" in observability_config:
            config.observability.prometheus_enabled = observability_config["prometheus_enabled"]

        if "log_format" in observability_config:
            config.observability.log_format = observability_config["log_format"]

        config_manager.update_config(config)

        return {"status": "success", "message": "Observability configuration updated"}
    except Exception as e:
        state.logger.error(f"Error updating observability config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
