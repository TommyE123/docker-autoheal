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
from app.config.config_manager import (
    HealthCheckConfig,
    MonitorConfig,
    RestartConfig,
    config_manager,
)


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

    async def test_update_config_ignores_restart_state_in_the_body(self):
        """restart_counts and restart_history are runtime state: a PUT body built
        before a restart was recorded, or carrying made-up values, cannot change
        them, while the rest of the body is still applied."""
        body = config_manager.get_config()
        config_manager.record_restart("web")
        live = config_manager.get_config().containers
        body.monitor.interval_seconds = 77
        body.containers.restart_counts = {"web": 99, "fake": 5}
        body.containers.restart_history = {"web": [1.0], "fake": [2.0]}

        await api_update_config(body)

        updated = config_manager.get_config()
        assert updated.monitor.interval_seconds == 77
        assert updated.containers.restart_counts == live.restart_counts == {"web": 1}
        assert updated.containers.restart_history == live.restart_history
        assert list(updated.containers.restart_history) == ["web"]

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

    @pytest.mark.parametrize(
        ("endpoint", "payload"),
        [
            (api_update_config, None),
            (update_monitor_config, MonitorConfig(interval_seconds=15)),
            (update_restart_config, RestartConfig(mode="both", max_restarts=7)),
        ],
    )
    async def test_configuration_update_errors_propagate(self, monkeypatch, endpoint, payload):
        monkeypatch.setattr(
            config_manager,
            "update_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(RuntimeError, match="disk error"):
            await endpoint(payload) if payload is not None else await endpoint(
                config_manager.get_config()
            )


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

    async def test_update_observability_config_unrecognized_log_level_falls_back_to_info(
        self,
    ):
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

    @pytest.mark.parametrize(
        "body",
        [{"log_level": 5}, {"prometheus_enabled": "abc"}, {"log_format": ["json"]}],
        ids=["log-level-not-string", "prometheus-not-bool", "log-format-not-string"],
    )
    async def test_update_observability_config_with_invalid_body_returns_422(self, body):
        before = config_manager.get_config().observability.model_dump()

        with pytest.raises(HTTPException) as exc_info:
            await update_observability_config(body)

        assert exc_info.value.status_code == 422
        assert config_manager.get_config().observability.model_dump() == before

    async def test_log_level_change_log_line_cannot_be_forged(self, caplog):
        with caplog.at_level("INFO", logger="app.api.routes.config"):
            await update_observability_config({"log_level": "INFO\nFORGED log line"})

        message = next(
            r.getMessage() for r in caplog.records if "Log level changed" in r.getMessage()
        )
        assert "\n" not in message
        assert "INFO\\nFORGED log line" in message

    async def test_update_observability_config_unexpected_error_propagates(self, monkeypatch):
        monkeypatch.setattr(
            config_manager,
            "update_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(RuntimeError, match="disk error"):
            await update_observability_config({"log_level": "DEBUG"})


@pytest.mark.asyncio
class TestConfigExportImport:
    async def test_export_config_returns_current_config_as_downloadable_json(self):
        config = config_manager.get_config()
        config.monitor.interval_seconds = 77
        config_manager.update_config(config)

        response = await export_config()

        assert response.status_code == 200
        assert "attachment; filename=autoheal-config-" in response.headers["content-disposition"]
        body = json.loads(bytes(response.body))
        assert body["monitor"]["interval_seconds"] == 77

    async def test_export_config_failure_propagates(self, monkeypatch):
        monkeypatch.setattr(
            config_manager,
            "export_config",
            MagicMock(side_effect=RuntimeError("disk error")),
        )

        with pytest.raises(RuntimeError, match="disk error"):
            await export_config()

    async def test_import_config_applies_uploaded_configuration(self):
        new_config = config_manager.get_config()
        new_config.monitor.interval_seconds = 123
        payload = new_config.model_dump_json()
        upload = UploadFile(file=BytesIO(payload.encode("utf-8")), filename="config.json")

        result = await api_import_config(upload)

        assert result["status"] == "success"
        assert config_manager.get_config().monitor.interval_seconds == 123

    @pytest.mark.parametrize(
        ("payload", "detail"),
        [
            ([], "Configuration must be a JSON object"),
            ("just a string", "Configuration must be a JSON object"),
            (
                {"custom_health_checks": []},
                "custom_health_checks must be an object whose values are health check objects",
            ),
            (
                {"custom_health_checks": {"web": "not-an-object"}},
                "custom_health_checks must be an object whose values are health check objects",
            ),
        ],
        ids=["root-array", "root-string", "custom-checks-array", "custom-check-not-object"],
    )
    async def test_import_config_with_wrong_structure_returns_422(self, payload, detail):
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )
        before = config_manager.get_config()
        checks_before = config_manager.get_all_custom_health_checks()
        upload = UploadFile(file=BytesIO(json.dumps(payload).encode()), filename="config.json")

        with pytest.raises(HTTPException) as exc_info:
            await api_import_config(upload)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == detail
        assert config_manager.get_config() == before
        assert config_manager.get_all_custom_health_checks() == checks_before

    async def test_import_config_422_does_not_echo_a_submitted_check_type(self):
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
        )
        checks_before = config_manager.get_all_custom_health_checks()
        payload = {
            "custom_health_checks": {
                "web": {"container_id": "web", "check_type": "SECRET-VALUE-123"}
            }
        }
        upload = UploadFile(file=BytesIO(json.dumps(payload).encode()), filename="config.json")

        with pytest.raises(HTTPException) as exc_info:
            await api_import_config(upload)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == (
            "Value error, Unknown check_type; expected one of: http, tcp, exec, docker"
        )
        assert "SECRET-VALUE-123" not in exc_info.value.detail
        assert config_manager.get_all_custom_health_checks() == checks_before

    @pytest.mark.parametrize(
        ("content", "detail"),
        [
            (b"not valid json", "File is not valid JSON"),
            (b"\xff\xfe not utf-8", "File must be UTF-8 encoded JSON"),
        ],
        ids=["not-json", "not-utf8"],
    )
    async def test_import_config_unreadable_file_returns_422(self, content, detail):
        upload = UploadFile(file=BytesIO(content), filename="config.json")

        with pytest.raises(HTTPException) as exc_info:
            await api_import_config(upload)

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == detail
