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
from app.utils.log_level import apply_log_level

logger = logging.getLogger(__name__)

router = APIRouter()

# Config import allows a little more than the app-wide 1 MiB body limit, for large exports.
MAX_IMPORT_BODY_BYTES = 2 * 1024 * 1024


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


@router.put(
    "/api/config/restart",
    # The body is a dict (see below), so point the documented schema back at the model.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/RestartConfig"}}
            },
        }
    },
    responses={422: {"description": "Not a valid restart configuration"}},
)
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


@router.get(
    "/api/config/export",
    responses={403: {"description": "Export is disabled (ui.allow_export_json is false)"}},
)
async def export_config():
    """Export configuration as JSON"""
    if not config_manager.get_config().ui.allow_export_json:
        raise HTTPException(status_code=403, detail="Configuration export is disabled")
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
    max_body_size=MAX_IMPORT_BODY_BYTES,
    # The import takes exactly one file and no other form fields.
    form_limits={"max_files": 1, "max_fields": 0},
    responses={
        400: {"description": "More than one file, or any other form field, was uploaded"},
        403: {"description": "Import is disabled (ui.allow_import_json is false)"},
        413: {"description": "Upload is larger than 2 MiB"},
        422: {"description": "File is not UTF-8 JSON or is not a valid configuration"},
    },
)
async def import_config(file: Annotated[UploadFile, File()]):
    """Import configuration from JSON file"""
    if not config_manager.get_config().ui.allow_import_json:
        raise HTTPException(status_code=403, detail="Configuration import is disabled")
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
        apply_log_level(level_name)

        logger.info("Log level changed to: %s", escape_for_log(level_name))

    config_manager.update_config(config)
    return {"status": "success", "message": "Observability configuration updated"}
