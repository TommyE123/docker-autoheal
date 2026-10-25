"""
Optional API-key authentication.

Authentication is opt-in. With neither ``AUTOHEAL_API_KEY`` nor
``AUTOHEAL_API_KEY_FILE`` set the API stays unauthenticated, exactly as before.
With a key configured, every ``/api`` path requires a matching ``X-API-Key`` header,
except the three API documentation paths (Swagger UI, ReDoc and the OpenAPI schema).
Those only exist when a key is configured (they are a developer tool, so without a key
they return 404), and they are not key-gated because a browser cannot send a custom
header when you open a page: Swagger UI's Authorize button takes the key, and the calls
made from it are then protected like any other. ``/health``, the UI shell and its static
assets stay public so the UI can load and prompt for a key.

A configuration that names a key but cannot supply one (unreadable or empty file,
empty variable) raises ``ApiKeyConfigError`` rather than silently running
unauthenticated.
"""

import logging
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

API_KEY_ENV = "AUTOHEAL_API_KEY"
API_KEY_FILE_ENV = "AUTOHEAL_API_KEY_FILE"
API_KEY_HEADER = "X-API-Key"
PROTECTED_PATH = "/api"

DOCS_URL = "/api/docs"
REDOC_URL = "/api/redoc"
OPENAPI_URL = "/api/openapi.json"
DOCS_PATHS = frozenset({DOCS_URL, REDOC_URL, OPENAPI_URL})

_api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


class _AuthState:
    """Set once at startup by ``configure_api_auth()``; ``key`` None means auth is disabled."""

    key: bytes | None = None


_state = _AuthState()


class ApiKeyConfigError(RuntimeError):
    """The API key configuration is present but unusable."""


def load_api_key() -> str | None:
    """
    Read the configured API key, or None when authentication is not configured.

    ``AUTOHEAL_API_KEY_FILE`` wins over ``AUTOHEAL_API_KEY`` (Docker secrets
    convention). Surrounding whitespace is stripped. Messages never include the key.
    """
    key_file = os.environ.get(API_KEY_FILE_ENV)
    if key_file is not None:
        try:
            key = Path(key_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as e:
            raise ApiKeyConfigError(
                f"{API_KEY_FILE_ENV} is set but the file could not be read: {type(e).__name__}"
            ) from e
        if not key:
            raise ApiKeyConfigError(f"{API_KEY_FILE_ENV} is set but the file is empty")
        return key

    key = os.environ.get(API_KEY_ENV)
    if key is None:
        return None
    key = key.strip()
    if not key:
        raise ApiKeyConfigError(f"{API_KEY_ENV} is set but empty")
    return key


def configure_api_auth() -> bool:
    """Load the key from the environment at startup. Returns True if auth is enabled."""
    key = load_api_key()
    _state.key = key.encode("utf-8") if key is not None else None
    if _state.key is None:
        logger.warning(
            "API authentication is disabled: set %s or %s to require an API key",
            API_KEY_ENV,
            API_KEY_FILE_ENV,
        )
    else:
        logger.info("API authentication is enabled (%s header required)", API_KEY_HEADER)
    return _state.key is not None


def _route_path(scope: Mapping[str, Any]) -> str:
    """
    The path as routing sees it: the ASGI ``path`` with ``root_path`` removed.

    ASGI's ``path`` includes ``root_path`` and routing strips it before matching, so the
    auth check must too, or a root_path prefix could hide an ``/api`` route from it. Only
    whole path segments are stripped, matching Starlette's own behaviour.
    """
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        rest = path[len(root_path) :]
        if rest == "" or rest.startswith("/"):
            return rest
    return path


def api_key_enabled() -> bool:
    """True when an API key is configured, which is also when the API docs are served."""
    return _state.key is not None


def _is_protected(path: str) -> bool:
    """
    ``/api`` itself and everything under it except the docs pages.

    Look-alikes such as ``/apix`` are not under ``/api``. The docs pages are left open so a
    browser can load them; whether they exist at all is decided by the docs routes.
    """
    if path in DOCS_PATHS:
        return False
    return path == PROTECTED_PATH or path.startswith(PROTECTED_PATH + "/")


def require_api_key(request: Request, provided: str | None = Security(_api_key_header)) -> None:
    """App-level dependency: enforce the API key on ``/api`` paths when configured."""
    if _state.key is None or not _is_protected(_route_path(request.scope)):
        return
    # Compare bytes so a non-ASCII header cannot raise TypeError in compare_digest.
    if provided is None or not secrets.compare_digest(provided.encode("utf-8"), _state.key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )
