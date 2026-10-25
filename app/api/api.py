"""
FastAPI application - REST API endpoints for Docker Auto-Heal Service

Route handlers live in ``app/api/routes/`` (split from this module in issue
#321), grouped by domain: health/status, containers, maintenance, config,
health checks, events, Uptime-Kuma integration, notifications, and UI/static
file serving. The ``docker_client``/``monitoring_engine`` globals and
``init_api()`` that used to live here now live in ``app/api/state.py`` (see
that module's docstring for why - avoiding a circular import with the route
modules). This module owns app construction and wiring each router in.
"""

import logging

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import require_api_key
from app.api.state import init_api  # noqa: F401  (re-exported for app/main.py)

logger = logging.getLogger(__name__)

# Initialize FastAPI app. FastAPI's built-in docs routes are disabled and re-registered
# below under /api/ so the app-level API-key dependency applies to them too (the
# built-in routes bypass dependencies).
app = FastAPI(
    title="Docker Auto-Heal Service",
    description="Automated container monitoring and healing service",
    version="2.4.0",  # x-release-please-version
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    dependencies=[Depends(require_api_key)],
)

DOCS_URL = "/api/docs"
REDOC_URL = "/api/redoc"
OPENAPI_URL = "/api/openapi.json"


@app.get(OPENAPI_URL, include_in_schema=False)
async def openapi_schema() -> dict:
    """OpenAPI schema (protected by the API key when one is configured)."""
    return app.openapi()


@app.get(DOCS_URL, include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui() -> HTMLResponse:
    """Swagger UI (protected by the API key when one is configured)."""
    return get_swagger_ui_html(openapi_url=OPENAPI_URL, title=f"{app.title} - Swagger UI")


@app.get(REDOC_URL, include_in_schema=False, response_class=HTMLResponse)
async def redoc_ui() -> HTMLResponse:
    """ReDoc (protected by the API key when one is configured)."""
    return get_redoc_html(openapi_url=OPENAPI_URL, title=f"{app.title} - ReDoc")


# No CORS middleware: the bundled UI is served by this same app (and the Vite
# dev server proxies /api and /health), so every legitimate browser request is
# same-origin. Granting cross-origin access would only let other websites drive
# this API from a user's browser.

# Mount static files for React build - MUST be done early
try:
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
    logger.debug("Static assets mounted")
except Exception as e:
    logger.warning("Assets directory not found: %s", e)

from app.api.routes import (  # noqa: E402
    config,
    containers,
    events,
    health,
    healthchecks,
    maintenance,
    notifications,
    ui,
    uptime_kuma,
)

# Registered in the same order the routes appeared in the pre-split module,
# so path matching precedence (notably `ui`'s catch-all, which must stay
# last) is unchanged.
for _router_module in (
    health,
    containers,
    maintenance,
    config,
    healthchecks,
    events,
    uptime_kuma,
    notifications,
    ui,
):
    app.include_router(_router_module.router)
