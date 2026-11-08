"""
Tests for the shared API error handling in ``app/api/errors.py``.

These drive the real ASGI app, because the behaviour under test (a generic 500, a 503 when
Docker is unavailable, a 422 for model validation) is produced by the app-level handlers
and the ``get_docker_client`` dependency, not by the route functions themselves.
"""

import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.errors import INTERNAL_ERROR_DETAIL, escape_for_log, get_docker_client
from app.config.config_manager import config_manager
from app.tests.unit.test_api_routing import _request

SECRET = "tk_internal_secret_value"


async def _call(method: str, path: str, payload: object = None):
    status, body, _headers = await _request(
        method,
        path,
        request_headers={"content-type": "application/json"},
        body=b"" if payload is None else json.dumps(payload).encode(),
        raise_app_exceptions=False,
    )
    return status, body.decode()


def _boom(*_args, **_kwargs):
    raise RuntimeError(SECRET)


class TestUnexpectedErrors:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/api/containers", "/api/status"])
    async def test_docker_failure_returns_generic_500(self, monkeypatch, path):
        docker_client = MagicMock()
        docker_client.list_containers.side_effect = RuntimeError(SECRET)
        monkeypatch.setattr("app.api.state.docker_client", docker_client)

        status, text = await _call("GET", path)

        assert status == 500
        assert json.loads(text) == {"detail": INTERNAL_ERROR_DETAIL}
        assert SECRET not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "path", "broken_method"),
        [
            ("GET", "/api/events", "get_events"),
            ("DELETE", "/api/events", "clear_events"),
            ("POST", "/api/maintenance/enable", "enable_maintenance_mode"),
            ("GET", "/api/config/export", "export_config"),
            ("GET", "/api/notifications/config", "get_config"),
        ],
    )
    async def test_internal_exception_text_is_not_returned(
        self, monkeypatch, method, path, broken_method
    ):
        monkeypatch.setattr(config_manager, broken_method, _boom)

        status, text = await _call(method, path)

        assert status == 500
        assert json.loads(text) == {"detail": INTERNAL_ERROR_DETAIL}
        assert SECRET not in text

    @pytest.mark.asyncio
    async def test_failure_is_logged_with_request_and_traceback(self, monkeypatch, caplog):
        monkeypatch.setattr(config_manager, "get_events", _boom)

        with caplog.at_level(logging.ERROR, logger="app.api.errors"):
            await _call("GET", "/api/events")

        record = next(r for r in caplog.records if r.name == "app.api.errors")
        assert record.getMessage() == "Unhandled error on GET /api/events"
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        assert record.exc_info[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_control_characters_in_the_path_are_escaped_in_the_logged_path(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr("app.api.state.docker_client", MagicMock(get_container=_boom))

        with caplog.at_level(logging.ERROR, logger="app.api.errors"):
            await _call("POST", "/api/containers/x\x1b[31mforged/restart")

        message = next(r for r in caplog.records if r.name == "app.api.errors").getMessage()
        assert "\x1b" not in message
        assert "x\\x1b[31mforged" in message


class TestEscapeForLog:
    @pytest.mark.parametrize(
        ("raw", "escaped"),
        [
            ("plain text", "plain text"),
            ("line1\nline2", "line1\\nline2"),
            ("a\r\nb", "a\\r\\nb"),
            ("\x1b[31mred", "\\x1b[31mred"),
            ("tab\there", "tab\\there"),
            ("Café ☕ 監視", "Café ☕ 監視"),
        ],
        ids=["plain", "newline", "crlf", "escape", "tab", "non-ascii-kept"],
    )
    def test_escapes_control_characters_and_keeps_printable_text(self, raw, escaped):
        assert escape_for_log(raw) == escaped


class TestDockerClientDependency:
    def test_returns_the_initialised_client(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr("app.api.state.docker_client", client)

        assert get_docker_client() is client

    def test_raises_503_when_not_initialised(self, monkeypatch):
        monkeypatch.setattr("app.api.state.docker_client", None)

        with pytest.raises(HTTPException) as exc_info:
            get_docker_client()

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Docker client not initialized"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        [
            ("GET", "/api/containers", None),
            ("GET", "/api/containers/web", None),
            ("POST", "/api/containers/select", {"container_ids": ["web"], "enabled": True}),
            ("POST", "/api/containers/web/restart", None),
            ("POST", "/api/containers/web/unquarantine", None),
            ("POST", "/api/healthchecks", {"container_id": "web", "check_type": "docker"}),
            ("GET", "/api/healthchecks/web", None),
            ("DELETE", "/api/healthchecks/web", None),
            (
                "POST",
                "/api/uptime-kuma/mappings",
                {"container_id": "web", "monitor_friendly_name": "Web"},
            ),
            (
                "POST",
                "/api/uptime-kuma/enable",
                {"server_url": "http://kuma.example", "api_token": "token"},
            ),
        ],
    )
    async def test_docker_routes_answer_503_when_docker_is_unavailable(
        self, monkeypatch, method, path, payload
    ):
        monkeypatch.setattr("app.api.state.docker_client", None)

        status, text = await _call(method, path, payload)

        assert status == 503
        assert json.loads(text) == {"detail": "Docker client not initialized"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        [
            ("POST", "/api/containers/select", {"container_ids": "not-a-list", "enabled": "x"}),
            ("POST", "/api/healthchecks", {"container_id": "web", "check_type": "carrier-pigeon"}),
            ("POST", "/api/uptime-kuma/mappings", {}),
            ("POST", "/api/uptime-kuma/enable", {}),
        ],
        ids=["select", "healthchecks", "mappings", "enable"],
    )
    async def test_docker_availability_is_checked_before_the_request_body(
        self, monkeypatch, method, path, payload
    ):
        """An invalid body gets 503, not 422 or 400, while Docker is unavailable."""
        monkeypatch.setattr("app.api.state.docker_client", None)

        status, text = await _call(method, path, payload)

        assert status == 503
        assert json.loads(text) == {"detail": "Docker client not initialized"}


class TestModelValidationErrors:
    @pytest.mark.asyncio
    async def test_http_exceptions_keep_their_status_and_detail(self, monkeypatch):
        monkeypatch.setattr(
            "app.api.state.docker_client", MagicMock(get_container=lambda _id: None)
        )

        status, text = await _call("GET", "/api/containers/missing")

        assert status == 404
        assert json.loads(text) == {"detail": "Container not found"}

    @pytest.mark.asyncio
    async def test_server_side_validation_failure_is_a_generic_500(self, monkeypatch, caplog):
        """A model built from server data failing validation is not the client's fault."""
        docker_client = MagicMock()
        docker_client.list_containers.return_value = [object()]
        docker_client.get_container_info.return_value = {"stable_id": "web", "name": None}
        monkeypatch.setattr("app.api.state.docker_client", docker_client)

        with caplog.at_level(logging.ERROR, logger="app.api.errors"):
            status, text = await _call("GET", "/api/containers")

        assert status == 500
        assert json.loads(text) == {"detail": INTERNAL_ERROR_DETAIL}
        assert any(
            r.exc_info and r.exc_info[0] is ValidationError
            for r in caplog.records
            if r.name == "app.api.errors"
        )

    @pytest.mark.asyncio
    async def test_invalid_config_import_is_422(self):
        status, body, _headers = await _request(
            "POST",
            "/api/config/import",
            request_headers={"content-type": "multipart/form-data; boundary=b"},
            body=(
                b'--b\r\nContent-Disposition: form-data; name="file"; filename="c.json"\r\n'
                b'Content-Type: application/json\r\n\r\n{"monitor": {"interval_seconds": "x"}}\r\n--b--\r\n'
            ),
            raise_app_exceptions=False,
        )

        assert status == 422
        assert "monitor.interval_seconds" in json.loads(body)["detail"]

    @pytest.mark.asyncio
    async def test_invalid_service_is_422_without_echoing_credentials(self, caplog):
        payload = {
            "name": "Ntfy",
            "type": "ntfy",
            "topic": "alerts",
            "access_token": {"value": SECRET},
        }

        with caplog.at_level(logging.DEBUG):
            status, text = await _call("POST", "/api/notifications/services", payload)

        detail = json.loads(text)["detail"]
        assert status == 422
        assert isinstance(detail, str)
        assert "access_token" in detail
        assert SECRET not in text
        assert SECRET not in caplog.text

    @pytest.mark.asyncio
    async def test_missing_required_field_is_422(self):
        status, text = await _call("POST", "/api/notifications/services", {"name": "No Type"})

        assert status == 422
        assert json.loads(text)["detail"] == "type: Field required"
