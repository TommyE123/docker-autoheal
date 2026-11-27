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
from fastapi import FastAPI

import app.main as main_module

# Captured at module import time, before the autouse `recorded_sleeps`
# fixture in conftest.py monkeypatches `asyncio.sleep` per test. That fixture
# collapses every sleep to a zero-duration yield, which would also hit
# Uvicorn's own `Server.main_loop()` tick delay and defeat the point of this
# smoke test genuinely exercising Uvicorn. Restored for the real-server
# portion of the test below.
_real_asyncio_sleep = asyncio.sleep

_POLL_INTERVAL_SECONDS = 0.01
_STARTUP_TIMEOUT_SECONDS = 5
_SHUTDOWN_TIMEOUT_SECONDS = 5


class _RecordingServer(uvicorn.Server):
    """A real ``uvicorn.Server`` that records its own instance on construction.

    Swapped in for ``app.main.uvicorn.Server`` so the test can grab a handle
    to the live server (to poll readiness and request shutdown) without
    replacing Uvicorn itself with a mock.
    """

    instances: ClassVar[list[_RecordingServer]] = []

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


async def _wait_for_server():
    """Wait for ``run_api_server()`` to build and start its server; return it and its URL."""
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
    return server, f"http://127.0.0.1:{port}"


async def _shut_down(server_task):
    """Ask the recorded server to exit, escalating to force exit and then cancellation."""
    if _RecordingServer.instances:
        _RecordingServer.instances[0].should_exit = True
    # asyncio.shield() keeps server_task running if this wait
    # times out, instead of cancelling it and skipping Uvicorn's
    # own socket-closing shutdown sequence.
    with suppress(TimeoutError):
        await asyncio.wait_for(asyncio.shield(server_task), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
    if not server_task.done() and _RecordingServer.instances:
        _RecordingServer.instances[0].force_exit = True
        with suppress(TimeoutError):
            await asyncio.wait_for(
                asyncio.shield(server_task),
                timeout=_SHUTDOWN_TIMEOUT_SECONDS,
            )
    if not server_task.done():
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            pass
        except TimeoutError:
            raise AssertionError(
                "server_task did not finish even after cancellation -- a socket may have leaked"
            ) from None


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
            patch("app.api.state.docker_client", None),
            patch("app.api.state.monitoring_engine", None),
            patch("asyncio.sleep", _real_asyncio_sleep),
        ):
            server_task = asyncio.create_task(main_module.run_api_server())
            try:
                server, base_url = await _wait_for_server()

                health_response = await asyncio.to_thread(
                    requests.get, f"{base_url}/health", timeout=5
                )
                status_response = await asyncio.to_thread(
                    requests.get, f"{base_url}/api/status", timeout=5
                )
            finally:
                await _shut_down(server_task)

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


def _get_status(url: str) -> int | Exception:
    """GET ``url``; return the status code, or the error if no response arrived."""
    try:
        return requests.get(url, timeout=10).status_code
    except requests.RequestException as error:
        return error


class TestRunApiServerGracefulShutdownBound:
    """In-flight requests get ``UVICORN_GRACEFUL_SHUTDOWN_SECONDS``, then are cancelled."""

    @pytest.mark.asyncio
    async def test_slow_request_is_cancelled_while_fast_one_completes(
        self, update_config, monkeypatch, caplog
    ):
        update_config(lambda config: setattr(config.ui, "listen_address", "127.0.0.1"))
        update_config(lambda config: setattr(config.ui, "listen_port", 0))
        monkeypatch.setattr(main_module, "UVICORN_GRACEFUL_SHUTDOWN_SECONDS", 0.3)
        _RecordingServer.instances.clear()

        fast_entered = asyncio.Event()
        fast_release = asyncio.Event()
        slow_entered = asyncio.Event()
        slow_cancelled = asyncio.Event()
        api = FastAPI()

        @api.get("/fast")
        async def fast():
            fast_entered.set()
            await fast_release.wait()
            return {"done": True}

        @api.get("/slow")
        async def slow():
            slow_entered.set()
            try:
                await asyncio.Event().wait()  # never finishes on its own
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise

        with (
            patch("app.main.app", api),
            patch("app.main.uvicorn.Server", _RecordingServer),
            patch("asyncio.sleep", _real_asyncio_sleep),
        ):
            server_task = asyncio.create_task(main_module.run_api_server())
            try:
                server, base_url = await _wait_for_server()
                fast_response = asyncio.create_task(
                    asyncio.to_thread(_get_status, f"{base_url}/fast")
                )
                slow_response = asyncio.create_task(
                    asyncio.to_thread(_get_status, f"{base_url}/slow")
                )
                await asyncio.wait_for(fast_entered.wait(), timeout=_STARTUP_TIMEOUT_SECONDS)
                await asyncio.wait_for(slow_entered.wait(), timeout=_STARTUP_TIMEOUT_SECONDS)

                server.should_exit = True
                await _wait_until(
                    lambda: not server.servers[0].is_serving(),
                    _SHUTDOWN_TIMEOUT_SECONDS,
                    "uvicorn did not begin shutting down",
                )
                # Shutdown has begun: an in-flight request may still finish normally
                fast_release.set()

                await asyncio.wait_for(
                    asyncio.shield(server_task), timeout=_SHUTDOWN_TIMEOUT_SECONDS
                )
            finally:
                await _shut_down(server_task)

            fast_status = await asyncio.wait_for(fast_response, timeout=_SHUTDOWN_TIMEOUT_SECONDS)
            slow_status = await asyncio.wait_for(slow_response, timeout=_SHUTDOWN_TIMEOUT_SECONDS)

        assert server_task.exception() is None  # serve() returned on its own
        assert fast_status == 200
        assert slow_cancelled.is_set()
        assert slow_status != 200
        assert any(
            record.name == "uvicorn.error"
            and record.getMessage().startswith("Cancel 1 running task(s)")
            for record in caplog.records
        )
