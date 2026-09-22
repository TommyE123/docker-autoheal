"""
Integration smoke test for the real production Uvicorn/FastAPI server path.

``test_main_lifecycle.py::TestRunApiServer`` verifies the exact
``uvicorn.Config``/``uvicorn.Server`` call contract with Uvicorn fully
mocked. That coverage cannot detect a real socket-binding failure, a
real ASGI/HTTP serving problem, or a shutdown that hangs. This module
complements it: it runs ``app.main.run_api_server()`` with a genuine
``uvicorn.Server`` bound to an ephemeral localhost port, hits it with a
real HTTP client, and verifies a clean shutdown.

Only ``app.main.uvicorn.Server`` is swapped out, and only to get a
handle to the running server instance for polling readiness and
triggering shutdown -- it is a real ``uvicorn.Server`` subclass, not a
mock, so Uvicorn genuinely binds a socket and serves requests.
"""

import asyncio
from contextlib import suppress
from typing import ClassVar
from unittest.mock import patch

import pytest
import requests
import uvicorn

import app.main as main_module

_POLL_INTERVAL_SECONDS = 0.01
_STARTUP_TIMEOUT_SECONDS = 5
_SHUTDOWN_TIMEOUT_SECONDS = 5


class _RecordingServer(uvicorn.Server):
    """A real ``uvicorn.Server`` that records its own instance on construction.

    Swapped in for ``app.main.uvicorn.Server`` so the test can grab a handle
    to the live server (to poll readiness and request shutdown) without
    replacing Uvicorn itself with a mock.
    """

    instances: ClassVar[list["_RecordingServer"]] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _RecordingServer.instances.append(self)


async def _wait_until(predicate, timeout_seconds, failure_message):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(failure_message)
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


class TestRunApiServerRealUvicornSmoke:
    """Starts the real production ``run_api_server()`` path end to end."""

    @pytest.mark.asyncio
    async def test_serves_health_and_status_over_real_http(self, update_config):
        # Port 0 asks the OS to assign a free ephemeral port at bind time, so
        # there is no gap between picking a port and Uvicorn binding it (unlike
        # discovering a free port up front and handing the number back to
        # Uvicorn, which another process could steal in between).
        # AutoHealConfig doesn't validate on plain attribute assignment or on
        # config_manager.update_config()'s model_copy(), so this bypasses the
        # ge=1 field constraint meant for persisted/user-facing config.
        update_config(lambda config: setattr(config.ui, "listen_address", "127.0.0.1"))
        update_config(lambda config: setattr(config.ui, "listen_port", 0))

        _RecordingServer.instances.clear()

        with (
            patch("app.main.uvicorn.Server", _RecordingServer),
            patch("app.api.api.docker_client", None),
            patch("app.api.api.monitoring_engine", None),
        ):
            server_task = asyncio.create_task(main_module.run_api_server())
            try:
                await _wait_until(
                    lambda: bool(_RecordingServer.instances),
                    _STARTUP_TIMEOUT_SECONDS,
                    "uvicorn.Server was never constructed by run_api_server()",
                )
                server = _RecordingServer.instances[0]

                await _wait_until(
                    lambda: server.started and bool(server.servers),
                    _STARTUP_TIMEOUT_SECONDS,
                    "uvicorn server did not start listening in time",
                )
                port = server.servers[0].sockets[0].getsockname()[1]
                base_url = f"http://127.0.0.1:{port}"

                health_response = await asyncio.to_thread(
                    requests.get, f"{base_url}/health", timeout=5
                )
                status_response = await asyncio.to_thread(
                    requests.get, f"{base_url}/api/status", timeout=5
                )
            finally:
                if _RecordingServer.instances:
                    _RecordingServer.instances[0].should_exit = True
                with suppress(TimeoutError):
                    await asyncio.wait_for(server_task, timeout=_SHUTDOWN_TIMEOUT_SECONDS)
                if not server_task.done():
                    server_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await server_task

            assert health_response.status_code == 200
            health_json = health_response.json()
            assert health_json["status"] == "healthy"
            assert health_json["docker_connected"] is False
            assert health_json["monitoring_active"] is False

            assert status_response.status_code == 200
            status_json = status_response.json()
            assert status_json["docker_connected"] is False
            assert status_json["monitoring_active"] is False
            assert status_json["total_containers"] == 0

            # Clean shutdown: the server task exited and released its sockets.
            assert server_task.done()
            assert server.should_exit is True
