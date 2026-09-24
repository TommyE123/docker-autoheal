"""
Unit tests for the real static-file serving path in ``app/api/api.py``.

``get_static_file_path()``/``serve_static_file()`` are exercised by calling
them directly to obtain a real ``FileResponse``, then invoking that response
as an ASGI app with a minimal scope/receive/send. This runs Starlette's
actual file-reading and streaming code (the code path that would use
``aiofiles`` if it were installed) without needing an HTTP client such as
``httpx``/``TestClient`` as a test dependency.
"""

from typing import TYPE_CHECKING, Any

import pytest
from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles

from app.api import api as api_module
from app.api.api import get_static_file_path, serve_static_file

if TYPE_CHECKING:
    from pathlib import Path


async def _collect_response(app: Any, path: str = "/") -> tuple[int, dict[str, str], bytes]:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    messages = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)

    start = next(m for m in messages if m["type"] == "http.response.start")
    status = start["status"]
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, headers, body


@pytest.fixture
def static_dir(tmp_path, monkeypatch) -> "Path":
    monkeypatch.setattr(api_module, "STATIC_DIR", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_serve_static_file_serves_sw_js(static_dir):
    content = b"self.addEventListener('install', () => {});"
    (static_dir / "sw.js").write_bytes(content)

    response = await serve_static_file("sw.js", "application/javascript")
    status, headers, body = await _collect_response(response)

    assert status == 200
    assert headers["content-type"] == "application/javascript"
    assert body == content


@pytest.mark.asyncio
async def test_serve_static_file_serves_manifest_json(static_dir):
    content = b'{"name": "Docker Auto-Heal"}'
    (static_dir / "manifest.json").write_bytes(content)

    response = await serve_static_file("manifest.json", "application/manifest+json")
    status, headers, body = await _collect_response(response)

    assert status == 200
    assert headers["content-type"] == "application/manifest+json"
    assert body == content


@pytest.mark.asyncio
async def test_serve_static_file_serves_png(static_dir):
    content = b"\x89PNG\r\n\x1a\nnot-a-real-png-but-bytes"
    (static_dir / "icon.png").write_bytes(content)

    response = await serve_static_file("icon.png")
    status, headers, body = await _collect_response(response)

    assert status == 200
    assert headers["content-type"] == "image/png"
    assert body == content


@pytest.mark.asyncio
async def test_serve_static_file_missing_file_raises_404(static_dir):
    with pytest.raises(HTTPException) as exc_info:
        await serve_static_file("does-not-exist.js")

    assert exc_info.value.status_code == 404


def test_get_static_file_path_traversal_raises_400(static_dir):
    with pytest.raises(HTTPException) as exc_info:
        get_static_file_path("../secret.txt")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_assets_static_files_mount_serves_file(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    content = b"console.log('asset');"
    (assets_dir / "a.js").write_bytes(content)

    assets_app = StaticFiles(directory=str(assets_dir))
    status, _headers, body = await _collect_response(assets_app, path="/a.js")

    assert status == 200
    assert body == content
