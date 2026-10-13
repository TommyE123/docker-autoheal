"""
Regression tests for blocking Docker calls in ``async def`` API handlers.

Each test makes one Docker call block on a ``threading.Event`` and checks that
the event loop can still run other work meanwhile. If a handler called Docker
on the loop thread, the blocked call would wait for a release that only the
(blocked) loop could send, so the bounded wait expires and the test fails.
No test depends on timing to pass.
"""

import asyncio
import threading

import pytest
from fastapi import HTTPException

from app.api.models import ContainerSelectionRequest
from app.api.routes.containers import (
    get_container_details,
    list_containers,
    restart_container_manual,
    unquarantine_container,
    update_container_selection,
)
from app.api.routes.health import get_system_status, health_check
from app.api.routes.healthchecks import add_health_check, delete_health_check, get_health_check
from app.config.config_manager import HealthCheckConfig, config_manager
from app.tests.unit.conftest import FakeDockerClient, make_container

WAIT_SECONDS = 5


class BlockingDockerClient(FakeDockerClient):
    """Fake whose chosen method blocks until the test releases it."""

    def __init__(self, blocking_method: str) -> None:
        super().__init__()
        self.blocking_method = blocking_method
        self.entered = threading.Event()
        self.release = threading.Event()
        self.released_in_time: bool | None = None
        self.call_threads: list[int] = []

    def _maybe_block(self, name: str) -> None:
        if name != self.blocking_method:
            return
        self.call_threads.append(threading.get_ident())
        self.entered.set()
        self.released_in_time = self.release.wait(WAIT_SECONDS)

    def is_connected(self):
        self._maybe_block("is_connected")
        return super().is_connected()

    def list_containers(self, all_containers=False):
        self._maybe_block("list_containers")
        return super().list_containers(all_containers)

    def get_container(self, container_id):
        self._maybe_block("get_container")
        return super().get_container(container_id)

    def get_container_info(self, container, refresh=True):
        self._maybe_block("get_container_info")
        return super().get_container_info(container, refresh)

    def restart_container(self, container, timeout=10):
        self._maybe_block("restart_container")
        return super().restart_container(container, timeout)


def _wire(monkeypatch, engine, blocking_method: str) -> BlockingDockerClient:
    client = BlockingDockerClient(blocking_method)
    container, info = make_container(name="web")
    client.add_container(container, info)
    monkeypatch.setattr("app.api.state.docker_client", client)
    monkeypatch.setattr("app.api.state.monitoring_engine", engine)
    return client


async def _assert_loop_stays_responsive(client: BlockingDockerClient, call):
    """Run ``call()`` while Docker blocks; return its result once released."""
    task = asyncio.create_task(call())
    # Waiting off-loop for the Docker call to start also lets the task run.
    assert await asyncio.to_thread(client.entered.wait, WAIT_SECONDS)

    progressed = []

    async def unrelated_work():
        await asyncio.sleep(0)
        progressed.append(True)

    await asyncio.wait_for(unrelated_work(), WAIT_SECONDS)
    assert progressed == [True]
    assert not task.done()

    client.release.set()
    result = await asyncio.wait_for(task, WAIT_SECONDS)
    assert client.released_in_time is True
    assert threading.get_ident() not in client.call_threads
    return result


@pytest.mark.asyncio
class TestDockerCallsDoNotBlockEventLoop:
    async def test_manual_restart(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "restart_container")

        result = await _assert_loop_stays_responsive(
            client, lambda: restart_container_manual("web")
        )

        assert result["status"] == "success"
        assert client.restart_calls == ["web"]

    async def test_list_containers(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "list_containers")

        result = await _assert_loop_stays_responsive(client, list_containers)

        assert [c.name for c in result] == ["web"]

    async def test_list_containers_inspect(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "get_container_info")

        result = await _assert_loop_stays_responsive(client, list_containers)

        assert [c.name for c in result] == ["web"]

    async def test_system_status(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "list_containers")

        status = await _assert_loop_stays_responsive(client, get_system_status)

        assert status.total_containers == 1
        assert status.monitored_containers == 1

    async def test_health_endpoint_connectivity_check(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "is_connected")

        result = await _assert_loop_stays_responsive(client, health_check)

        assert result["docker_connected"] is True

    async def test_container_details(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "get_container_info")

        result = await _assert_loop_stays_responsive(client, lambda: get_container_details("web"))

        assert result["name"] == "web"

    async def test_container_selection(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "get_container")
        request = ContainerSelectionRequest(container_ids=["web"], enabled=True)

        result = await _assert_loop_stays_responsive(
            client, lambda: update_container_selection(request)
        )

        assert result["status"] == "success"

    async def test_unquarantine(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "get_container_info")
        monkeypatch.setattr("app.api.state.notification_manager", _NoopNotifier(), raising=False)

        result = await _assert_loop_stays_responsive(client, lambda: unquarantine_container("web"))

        assert result["status"] == "success"

    async def test_add_health_check(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "get_container")
        health_check_config = HealthCheckConfig(
            container_id="web", check_type="http", http_endpoint="http://localhost/health"
        )

        result = await _assert_loop_stays_responsive(
            client, lambda: add_health_check(health_check_config)
        )

        assert result["status"] == "success"

    async def test_get_health_check(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "get_container_info")

        with pytest.raises(HTTPException) as exc_info:
            await _assert_loop_stays_responsive(client, lambda: get_health_check("web"))

        assert exc_info.value.status_code == 404

    async def test_delete_health_check(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "get_container")

        result = await _assert_loop_stays_responsive(client, lambda: delete_health_check("web"))

        assert result["status"] == "success"


class _NoopNotifier:
    async def send_event_notification(self, event):
        return None


@pytest.mark.asyncio
class TestErrorsFromWorkerThreadsStillHandled:
    async def test_restart_failure_returns_500(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "none")
        client.restart_results["web"] = False

        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("web")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to restart container"

    async def test_restart_unknown_container_returns_404(self, monkeypatch, engine):
        _wire(monkeypatch, engine, "none")

        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("missing")

        assert exc_info.value.status_code == 404

    async def test_exception_in_worker_thread_returns_500_with_detail(self, monkeypatch, engine):
        client = _wire(monkeypatch, engine, "none")
        client.list_containers_error = RuntimeError("daemon unreachable")

        with pytest.raises(HTTPException) as exc_info:
            await list_containers()

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "daemon unreachable"


@pytest.mark.asyncio
class TestConcurrentSelectionRequests:
    async def test_overlapping_requests_do_not_overwrite_each_other(self, monkeypatch, engine):
        """A request paused in Docker must not later write back a stale config copy."""
        client = BlockingDockerClient("get_container")
        web, web_info = make_container(name="web", container_id="a" * 64)
        db, db_info = make_container(name="db", container_id="b" * 64)
        client.add_container(web, web_info)
        client.add_container(db, db_info)
        monkeypatch.setattr("app.api.state.docker_client", client)
        monkeypatch.setattr("app.api.state.monitoring_engine", engine)
        original_get_container = FakeDockerClient.get_container

        def block_only_web(container_id):
            if container_id == "web":
                return BlockingDockerClient.get_container(client, container_id)
            return original_get_container(client, container_id)

        monkeypatch.setattr(client, "get_container", block_only_web)

        first = asyncio.create_task(
            update_container_selection(
                ContainerSelectionRequest(container_ids=["web"], enabled=False)
            )
        )
        assert await asyncio.to_thread(client.entered.wait, WAIT_SECONDS)

        await update_container_selection(
            ContainerSelectionRequest(container_ids=["db"], enabled=False)
        )
        client.release.set()
        await asyncio.wait_for(first, WAIT_SECONDS)

        assert set(config_manager.get_config().containers.excluded) >= {"web", "db"}
