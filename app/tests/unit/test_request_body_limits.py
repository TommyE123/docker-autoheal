"""
Request body size limits (issue #308), exercised through the real ASGI app.

The API is unauthenticated, so an unbounded body could exhaust memory. These tests
check the app-wide ``max_body_size`` (413), the larger override on config import,
and the import route's ``form_limits`` (400).
"""

import json

import pytest

from app.api.api import MAX_REQUEST_BODY_BYTES
from app.api.routes.config import MAX_IMPORT_BODY_BYTES
from app.config.config_manager import config_manager
from app.tests.unit.test_api_routing import _request

BOUNDARY = "autohealtestboundary"
MULTIPART = {"content-type": f"multipart/form-data; boundary={BOUNDARY}"}
JSON_HEADERS = {"content-type": "application/json"}


def _multipart(*parts: tuple[str, str, bytes | None]) -> bytes:
    """Build a multipart body from ``(field name, filename or "", content)`` parts."""
    body = b""
    for name, filename, content in parts:
        disposition = f'form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        body += f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n\r\n".encode()
        body += (content or b"") + b"\r\n"
    return body + f"--{BOUNDARY}--\r\n".encode()


@pytest.mark.asyncio
class TestJsonBodyLimit:
    async def test_oversized_json_body_is_rejected_with_413(self):
        body = json.dumps({"padding": "x" * MAX_REQUEST_BODY_BYTES}).encode()

        status, _, _ = await _request("PUT", "/api/config", JSON_HEADERS, body=body)

        assert status == 413

    async def test_normal_json_body_is_unaffected(self):
        body = config_manager.get_config().model_dump_json().encode()

        status, _, _ = await _request("PUT", "/api/config", JSON_HEADERS, body=body)

        assert status == 200


@pytest.mark.asyncio
class TestImportLimits:
    async def test_oversized_upload_is_rejected_with_413(self):
        body = _multipart(("file", "config.json", b" " * MAX_IMPORT_BODY_BYTES))

        status, _, _ = await _request("POST", "/api/config/import", MULTIPART, body=body)

        assert status == 413

    async def test_upload_above_the_app_limit_but_below_the_import_limit_is_read(self):
        """The import override is larger than the app-wide limit, so this reaches the
        handler and fails validation (422) rather than being cut off (413)."""
        body = _multipart(("file", "config.json", b" " * (MAX_REQUEST_BODY_BYTES + 1024)))

        status, _, _ = await _request("POST", "/api/config/import", MULTIPART, body=body)

        assert status == 422

    async def test_second_file_part_is_rejected_with_400(self):
        content = config_manager.export_config().encode()
        body = _multipart(("file", "a.json", content), ("file", "b.json", content))

        status, _, _ = await _request("POST", "/api/config/import", MULTIPART, body=body)

        assert status == 400

    async def test_extra_form_field_is_rejected_with_400(self):
        content = config_manager.export_config().encode()
        body = _multipart(("file", "a.json", content), ("note", "", b"hi"))

        status, _, _ = await _request("POST", "/api/config/import", MULTIPART, body=body)

        assert status == 400

    async def test_normal_upload_is_unaffected(self):
        body = _multipart(("file", "config.json", config_manager.export_config().encode()))

        status, _, _ = await _request("POST", "/api/config/import", MULTIPART, body=body)

        assert status == 200
