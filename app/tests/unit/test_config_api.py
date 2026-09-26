"""
Unit tests for the configuration endpoints in ``app/api/routes/config.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client - ``config_manager`` is isolated per test
(see ``conftest.py``).
"""

import json
import logging
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from app.api.routes.config import (
    export_config,
    get_config,
    update_monitor_config,
    update_observability_config,
    update_restart_config,
)
from app.api.routes.config import import_config as api_import_config
from app.api.routes.config import update_config as api_update_config
from app.config.config_manager import MonitorConfig, RestartConfig, config_manager


@pytest.mark.asyncio
class TestConfigurationEndpoints:
    async def test_get_config_returns_current_config(self):
        config = config_manager.get_config()
        config.monitor.interval_seconds = 42
        config_manager.update_config(config)

        result = await get_config()

        assert result.monitor.interval_seconds == 42

    async def test_update_config_persists_full_config(self):
        new_config = config_manager.get_config()
        new_config.monitor.interval_seconds = 99

        result = await api_update_config(new_config)

        assert result["status"] == "success"
        assert config_manager.get_config().monitor.interval_seconds == 99

    async def test_update_monitor_config_only_changes_monitor_section(self):
        original_restart_mode = config_manager.get_config().restart.mode

        await update_monitor_config(MonitorConfig(interval_seconds=15))

        updated = config_manager.get_config()
        assert updated.monitor.interval_seconds == 15
        assert updated.restart.mode == original_restart_mode

    async def test_update_restart_config_only_changes_restart_section(self):
        original_interval = config_manager.get_config().monitor.interval_seconds

        await update_restart_config(RestartConfig(mode="both", max_restarts=7))

        updated = config_manager.get_config()
        assert updated.restart.mode == "both"
        assert updated.restart.max_restarts == 7
        assert updated.monitor.interval_seconds == original_interval


@pytest.mark.asyncio
class TestObservabilityConfig:
    @pytest.fixture(autouse=True)
    def restore_logger_levels(self):
        # The endpoint mutates the root, uvicorn, uvicorn.access, and
        # uvicorn.error logger levels as a side effect; restore them so these
        # tests don't leak state into the rest of the suite.
        logger_names = (None, "uvicorn", "uvicorn.access", "uvicorn.error")
        original_levels = {name: logging.getLogger(name).level for name in logger_names}
        try:
            yield
        finally:
            for name, level in original_levels.items():
                logging.getLogger(name).setLevel(level)

    async def test_update_observability_config_updates_log_level(self):
        result = await update_observability_config({"log_level": "DEBUG"})

        assert result["status"] == "success"
        assert config_manager.get_config().observability.log_level == "DEBUG"
        assert logging.getLogger().level == logging.DEBUG

    async def test_update_observability_config_unrecognized_log_level_falls_back_to_info(self):
        logging.getLogger().setLevel(logging.DEBUG)

        result = await update_observability_config({"log_level": "NOT_A_LEVEL"})

        assert result["status"] == "success"
        assert config_manager.get_config().observability.log_level == "NOT_A_LEVEL"
        assert logging.getLogger().level == logging.INFO

    async def test_update_observability_config_updates_prometheus_enabled_only(self):
        original_log_level = config_manager.get_config().observability.log_level

        await update_observability_config({"prometheus_enabled": False})

        updated = config_manager.get_config().observability
        assert updated.prometheus_enabled is False
        assert updated.log_level == original_log_level

    async def test_update_observability_config_updates_log_format_only(self):
        original_prometheus_enabled = config_manager.get_config().observability.prometheus_enabled

        await update_observability_config({"log_format": "text"})

        updated = config_manager.get_config().observability
        assert updated.log_format == "text"
        assert updated.prometheus_enabled == original_prometheus_enabled

    async def test_update_observability_config_only_changes_observability_section(self):
        original_restart_mode = config_manager.get_config().restart.mode

        await update_observability_config({"log_level": "WARNING"})

        assert config_manager.get_config().restart.mode == original_restart_mode

    async def test_update_observability_config_unexpected_error_returns_500(self, monkeypatch):
        monkeypatch.setattr(
            config_manager,
            "update_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_observability_config({"log_level": "DEBUG"})

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestConfigExportImport:
    async def test_export_config_returns_current_config_as_downloadable_json(self):
        config = config_manager.get_config()
        config.monitor.interval_seconds = 77
        config_manager.update_config(config)

        response = await export_config()

        assert response.status_code == 200
        assert (
            "attachment; filename=autoheal-config-"
            in response.headers["content-disposition"]
        )
        body = json.loads(bytes(response.body))
        assert body["monitor"]["interval_seconds"] == 77

    async def test_export_config_failure_returns_500(self, monkeypatch):
        monkeypatch.setattr(
            config_manager,
            "export_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await export_config()

        assert exc_info.value.status_code == 500

    async def test_import_config_applies_uploaded_configuration(self):
        new_config = config_manager.get_config()
        new_config.monitor.interval_seconds = 123
        payload = new_config.model_dump_json()
        upload = UploadFile(
            file=BytesIO(payload.encode("utf-8")), filename="config.json"
        )

        result = await api_import_config(upload)

        assert result["status"] == "success"
        assert config_manager.get_config().monitor.interval_seconds == 123

    async def test_import_config_invalid_json_returns_500(self):
        upload = UploadFile(file=BytesIO(b"not valid json"), filename="config.json")

        with pytest.raises(HTTPException) as exc_info:
            await api_import_config(upload)

        assert exc_info.value.status_code == 500
