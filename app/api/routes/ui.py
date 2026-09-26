"""UI serving: the React app shell, PWA static files, and the React Router catch-all."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.api import state

router = APIRouter()

# ==================== UI Endpoint ====================


def serve_react_app():
    """Helper function to serve React index.html"""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Docker Auto-Heal Service</h1>"
                   "<p>React UI not found. Please build the frontend first:</p>"
                   "<pre>cd frontend && npm install && npm run build</pre>"
                   "<p>API documentation is available at <a href='/docs'>/docs</a></p>"
        )


@router.get("/", response_class=HTMLResponse)
async def serve_ui_root():
    """Serve the React UI at root"""
    return serve_react_app()


# ==================== PWA Static File Serving ====================

# Configuration for static files
STATIC_DIR = Path("static")
MEDIA_TYPE_MAP = {
    ".json": "application/manifest+json",
    ".js": "application/javascript",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp"
}

# PWA-critical files that must be served at root level
PWA_ROOT_FILES = {
    "manifest.json": "application/manifest+json",
    "sw.js": "application/javascript",
    "registerSW.js": "application/javascript",
    "favicon.svg": "image/svg+xml",
    "screenshot-narrow.png": "image/png",
    "screenshot-wide.png": "image/png"
}


def get_media_type(filename: str) -> str:
    """Get media type based on file extension"""
    ext = Path(filename).suffix.lower()
    return MEDIA_TYPE_MAP.get(ext, "application/octet-stream")


def get_static_file_path(filename: str) -> Path:
    """Get the full path to a static file and validate it exists"""
    file_path = STATIC_DIR / filename

    # Security check: ensure the resolved path is within STATIC_DIR
    try:
        resolved_path = file_path.resolve()
        resolved_static = STATIC_DIR.resolve()

        # Check if the file is within the static directory
        if resolved_static not in resolved_path.parents and resolved_path.parent != resolved_static:
            raise HTTPException(status_code=400, detail="Invalid file path")
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return file_path


async def serve_static_file(filename: str, media_type: Optional[str] = None) -> FileResponse:
    """Generic handler for serving static files with validation"""
    try:
        file_path = get_static_file_path(filename)

        # Auto-detect media type if not provided
        if media_type is None:
            media_type = get_media_type(filename)

        state.logger.debug(f"Serving static file: {filename} ({media_type})")
        return FileResponse(file_path, media_type=media_type)

    except HTTPException:
        raise
    except Exception as e:
        state.logger.error(f"Error serving static file {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Error serving file: {e!s}")


# Serve PWA files at root level (required for PWA installation)
@router.get("/manifest.json")
async def serve_manifest():
    """Serve PWA manifest at root"""
    state.logger.info("PWA manifest route hit!")
    return await serve_static_file("manifest.json", "application/manifest+json")


@router.get("/sw.js")
async def serve_service_worker():
    """Serve service worker at root"""
    return await serve_static_file("sw.js", "application/javascript")


@router.get("/registerSW.js")
async def serve_register_sw():
    """Serve service worker registration script"""
    return await serve_static_file("registerSW.js", "application/javascript")


@router.get("/workbox-{filename:path}.js")
async def serve_workbox(filename: str):
    """Serve workbox files dynamically"""
    return await serve_static_file(f"workbox-{filename}.js", "application/javascript")


@router.get("/pwa-{size}.png")
async def serve_pwa_icon(size: str):
    """Serve PWA icons at root (e.g., pwa-64x64.png, pwa-192x192.png)"""
    # Validate size format to prevent path traversal
    if not size.replace("x", "").replace("-", "").isdigit():
        raise HTTPException(status_code=400, detail="Invalid icon size format")
    return await serve_static_file(f"pwa-{size}.png", "image/png")


@router.get("/maskable-icon-{size}.png")
async def serve_maskable_icon(size: str):
    """Serve maskable PWA icons at root"""
    # Validate size format
    if not size.replace("x", "").replace("-", "").isdigit():
        raise HTTPException(status_code=400, detail="Invalid icon size format")
    return await serve_static_file(f"maskable-icon-{size}.png", "image/png")


@router.get("/screenshot-narrow.png")
async def serve_screenshot_narrow():
    """Serve narrow screenshot for PWA"""
    return await serve_static_file("screenshot-narrow.png", "image/png")


@router.get("/screenshot-wide.png")
async def serve_screenshot_wide():
    """Serve wide screenshot for PWA"""
    return await serve_static_file("screenshot-wide.png", "image/png")


@router.get("/favicon.svg")
async def serve_favicon():
    """Serve favicon at root"""
    return await serve_static_file("favicon.svg", "image/svg+xml")


# ==================== React Router Catch-All ====================

# Patterns to exclude from React Router catch-all
EXCLUDED_PATH_PREFIXES = {
    "api/",
    "docs",
    "redoc",
    "openapi.json",
    "assets/",
    "static/"
}

EXCLUDED_FILE_PATTERNS = {
    "manifest.json",
    "sw.js",
    "registerSW.js",
    "favicon.svg",
    "favicon.ico"
}

EXCLUDED_PATH_PATTERNS = {
    "workbox-",
    "pwa-",
    "maskable-icon-",
    "screenshot-"
}

STATIC_FILE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",  # Images
    ".js", ".mjs", ".cjs",  # JavaScript
    ".json", ".webmanifest",  # JSON/Manifest
    ".css", ".scss", ".sass",  # Styles
    ".woff", ".woff2", ".ttf", ".eot",  # Fonts
    ".ico",  # Icons
    ".map"  # Source maps
}


def should_serve_react_app(path: str) -> bool:
    """
    Determine if a path should serve the React app or return 404.
    Returns True if the path should serve React, False if it should 404.
    """
    # Check if path starts with excluded prefixes
    if any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
        return False

    # Check if path matches excluded file patterns
    if path in EXCLUDED_FILE_PATTERNS:
        return False

    # Check if path contains excluded patterns
    if any(pattern in path for pattern in EXCLUDED_PATH_PATTERNS):
        return False

    # Check if path has a static file extension
    path_lower = path.lower()
    if any(path_lower.endswith(ext) for ext in STATIC_FILE_EXTENSIONS):
        return False

    # If none of the exclusions match, serve React app
    return True


# Catch-all route for React Router - must be at the end
# This serves index.html for all non-API routes, allowing React Router to handle client-side routing
@router.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_ui_catchall(full_path: str):
    """
    Serve the React UI for all non-API routes (React Router support).
    This allows client-side routing to work properly.
    """
    if should_serve_react_app(full_path):
        state.logger.debug(f"Serving React app for path: {full_path}")
        return serve_react_app()
    state.logger.debug(f"Returning 404 for excluded path: {full_path}")
    raise HTTPException(status_code=404, detail="Not Found")
