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

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api.errors import escape_for_log, invalid_input_as_422
from app.config.config_manager import (
    AutoHealConfig,
    ConfigImportError,
    MonitorConfig,
    ObservabilityConfig,
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
async def update_restart_config(restart_config: dict):
    """Update restart configuration"""
    # Validated here, not as a typed body, so a rejected value (for example a mistyped
    # mode) is not echoed back in FastAPI's own 422 detail.
    with invalid_input_as_422():
        validated = RestartConfig.model_validate(restart_config)
    config = config_manager.get_config()
    config.restart = validated
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


@router.post(
    "/api/config/import",
    responses={422: {"description": "File is not UTF-8 JSON or is not a valid configuration"}},
)
async def import_config(file: Annotated[UploadFile, File()]):
    """Import configuration from JSON file"""
    content = await file.read()
    try:
        config_json = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="File must be UTF-8 encoded JSON") from None

    try:
        with invalid_input_as_422():
            config_manager.import_config(config_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="File is not valid JSON") from None
    except ConfigImportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return {"status": "success", "message": "Configuration imported successfully"}


@router.put("/api/config/observability")
async def update_observability_config(observability_config: dict):
    """Update observability configuration including log level"""
    config = config_manager.get_config()

    # Validate the merged section as one model, so a bad value is rejected here instead of
    # being saved and then reset the next time the config loads.
    updates = {
        key: observability_config[key]
        for key in ("log_level", "prometheus_enabled", "log_format")
        if key in observability_config
    }
    with invalid_input_as_422():
        config.observability = ObservabilityConfig.model_validate(
            {**config.observability.model_dump(), **updates}
        )

    if "log_level" in updates:
        level_name = config.observability.log_level

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

        logger.info("Log level changed to: %s", escape_for_log(level_name))

    config_manager.update_config(config)
    return {"status": "success", "message": "Observability configuration updated"}
