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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.state import init_api  # noqa: F401  (re-exported for app/main.py)

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Docker Auto-Heal Service",
    description="Automated container monitoring and healing service",
    version="1.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for React build - MUST be done early
try:
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
    logger.debug("Static assets mounted")
except Exception as e:
    logger.warning(f"Assets directory not found: {e}")

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
