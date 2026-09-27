"""
Unit tests for the real static-file serving path in ``app/api/routes/ui.py``.

``get_static_file_path()``/``serve_static_file()`` are exercised by calling
them directly to obtain a real ``FileResponse``, then invoking that response
as an ASGI app with a minimal scope/receive/send. This runs Starlette's
actual file-reading and streaming code without needing an HTTP client such
as ``httpx``/``TestClient`` as a test dependency.
"""

from typing import TYPE_CHECKING, Any

import pytest
from fastapi import HTTPException

from app.api.routes import ui as api_module
from app.api.routes.ui import get_static_file_path, serve_static_file

if TYPE_CHECKING:
    from pathlib import Path


async def _collect_response(app: Any) -> tuple[int, dict[str, str], bytes]:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
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
async def test_serve_static_file_unexpected_error_becomes_500(static_dir, monkeypatch):
    def explode(_filename):
        raise OSError("filesystem went away")

    monkeypatch.setattr(api_module, "get_static_file_path", explode)

    with pytest.raises(HTTPException) as exc_info:
        await serve_static_file("sw.js")

    assert exc_info.value.status_code == 500
    assert "filesystem went away" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# PWA root endpoints
#
# Each of these is a thin wrapper whose whole job is the filename and media
# type it pins - the pair a browser needs exactly right to install the PWA.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "args", "filename", "media_type"),
    [
        (api_module.serve_manifest, (), "manifest.json", "application/manifest+json"),
        (api_module.serve_service_worker, (), "sw.js", "application/javascript"),
        (api_module.serve_register_sw, (), "registerSW.js", "application/javascript"),
        (api_module.serve_favicon, (), "favicon.svg", "image/svg+xml"),
        (api_module.serve_screenshot_narrow, (), "screenshot-narrow.png", "image/png"),
        (api_module.serve_screenshot_wide, (), "screenshot-wide.png", "image/png"),
        (api_module.serve_workbox, ("abc123",), "workbox-abc123.js", "application/javascript"),
        (api_module.serve_pwa_icon, ("192x192",), "pwa-192x192.png", "image/png"),
        (
            api_module.serve_maskable_icon,
            ("512x512",),
            "maskable-icon-512x512.png",
            "image/png",
        ),
    ],
)
async def test_pwa_root_endpoint_serves_expected_file(
    static_dir, endpoint, args, filename, media_type
):
    content = f"contents of {filename}".encode()
    (static_dir / filename).write_bytes(content)

    response = await endpoint(*args)
    status, headers, body = await _collect_response(response)

    assert status == 200
    assert headers["content-type"] == media_type
    assert body == content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint", [api_module.serve_pwa_icon, api_module.serve_maskable_icon]
)
@pytest.mark.parametrize("size", ["../../etc/passwd", "192x192/../..", "abc"])
async def test_icon_endpoints_reject_non_numeric_sizes(static_dir, endpoint, size):
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(size)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# React app shell
# ---------------------------------------------------------------------------


def test_serve_react_app_returns_built_index_html(tmp_path, monkeypatch):
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text(
        "<!doctype html><title>built app</title>", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    response = api_module.serve_react_app()

    assert response.status_code == 200
    assert b"built app" in response.body


def test_serve_react_app_falls_back_when_frontend_is_not_built(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no static/index.html here

    response = api_module.serve_react_app()

    assert response.status_code == 200
    assert b"React UI not found" in response.body
    assert b"npm run build" in response.body
