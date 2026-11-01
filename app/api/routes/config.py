"""
Configuration endpoints.

Also owns ``/api/config/observability`` - logically a configuration endpoint,
even though it originally lived under the "Event Log Endpoints" section in
the pre-split ``app/api/api.py`` (issue #321 split routes along logical
domains rather than preserving that historical placement).
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.config.config_manager import (
    AutoHealConfig,
    MonitorConfig,
    RestartConfig,
    config_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/config", response_model=AutoHealConfig)
async def get_config():
    """Get current configuration"""
    return config_manager.get_config()


@router.put("/api/config")
async def update_config(config: AutoHealConfig):
    """Update configuration"""
    config_manager.update_config(config)
    return {"status": "success", "message": "Configuration updated"}


@router.put("/api/config/monitor")
async def update_monitor_config(monitor_config: MonitorConfig):
    """Update monitor configuration"""
    config = config_manager.get_config()
    config.monitor = monitor_config
    config_manager.update_config(config)
    return {"status": "success", "message": "Monitor configuration updated"}


@router.put("/api/config/restart")
async def update_restart_config(restart_config: RestartConfig):
    """Update restart configuration"""
    config = config_manager.get_config()
    config.restart = restart_config
    config_manager.update_config(config)
    return {"status": "success", "message": "Restart configuration updated"}


@router.get("/api/config/export")
async def export_config():
    """Export configuration as JSON"""
    config_json = config_manager.export_config()

    # Return as downloadable file
    return JSONResponse(
        content=json.loads(config_json),
        headers={
            "Content-Disposition": f"attachment; filename=autoheal-config-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
        },
    )


@router.post("/api/config/import")
async def import_config(file: Annotated[UploadFile, File()]):
    """Import configuration from JSON file"""
    content = await file.read()
    config_json = content.decode("utf-8")

    config_manager.import_config(config_json)
    return {"status": "success", "message": "Configuration imported successfully"}


@router.put("/api/config/observability")
async def update_observability_config(observability_config: dict):
    """Update observability configuration including log level"""
    config = config_manager.get_config()

    # Update observability config
    if "log_level" in observability_config:
        level_name = observability_config["log_level"]
        config.observability.log_level = level_name

        # Update log level directly without importing main
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        level = level_map.get(level_name.upper(), logging.INFO)

        # Set root logger level
        logging.getLogger().setLevel(level)

        # Disable uvicorn access logs completely
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
        logging.getLogger("uvicorn").setLevel(logging.WARNING)

        logger.info("Log level changed to: %s", level_name)

    if "prometheus_enabled" in observability_config:
        config.observability.prometheus_enabled = observability_config["prometheus_enabled"]

    if "log_format" in observability_config:
        config.observability.log_format = observability_config["log_format"]

    config_manager.update_config(config)
    return {"status": "success", "message": "Observability configuration updated"}
