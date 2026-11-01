"""
Shared API error handling.

Route handlers let unexpected exceptions propagate instead of each repeating a
``try/except`` that logs and re-raises ``HTTPException(500, str(e))``. The
handlers registered here turn them into a response, so internal exception text
never reaches the client. ``get_docker_client`` is the shared dependency for
handlers that need Docker.
"""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api import state
from app.docker_client.docker_client_wrapper import DockerClientWrapper

logger = logging.getLogger(__name__)

INTERNAL_ERROR_DETAIL = "Internal server error, see logs"


def get_docker_client() -> DockerClientWrapper:
    """Return the Docker client, or raise 503 when it is not available.

    Read from ``app.api.state`` at call time, as the state module documents, so
    ``init_api()`` and test monkeypatching are both seen.
    """
    docker_client = state.docker_client
    if not docker_client:
        raise HTTPException(status_code=503, detail="Docker client not initialized")
    return docker_client


DockerClientDep = Annotated[DockerClientWrapper, Depends(get_docker_client)]


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Report a model validation failure raised inside a handler as 422.

    Field locations and messages only: pydantic errors echo the submitted input,
    which can contain tokens and webhook URLs. The detail is a single string,
    which is what the UI displays.
    """
    if not isinstance(exc, ValidationError):  # pragma: no cover - registered for this type only
        raise exc
    detail = "; ".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
        for err in exc.errors(include_input=False)
    )
    logger.warning(
        "Validation error on %s %s: %s", request.method, request.url.path, detail or "invalid"
    )
    return JSONResponse(status_code=422, content={"detail": detail or "Validation error"})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log an unexpected error with its traceback and return a generic 500."""
    logger.error(
        "Unhandled error on %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_DETAIL})


def register_exception_handlers(app: FastAPI) -> None:
    """Register the shared exception handlers on ``app``."""
    app.add_exception_handler(ValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
