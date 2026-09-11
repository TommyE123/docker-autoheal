"""
Unit tests for :class:`DockerClientWrapper`.

The Docker SDK is mocked out entirely - these tests never talk to a Docker
daemon. They focus on the boundary behaviour the monitoring engine relies on:
inspection results and graceful handling of Docker API failures.
"""

import docker
import pytest
from unittest.mock import MagicMock, patch

from app.docker_client.docker_client_wrapper import DockerClientWrapper


@pytest.fixture
def sdk_client() -> MagicMock:
    """A mock Docker SDK client."""
    client = MagicMock()
    client.ping.return_value = True
    return client


@pytest.fixture
def wrapper(sdk_client) -> DockerClientWrapper:
    """A wrapper connected to the mock SDK client."""
    with patch("app.docker_client.docker_client_wrapper.docker.DockerClient", return_value=sdk_client):
        return DockerClientWrapper(base_url="unix://var/run/docker.sock")


def make_sdk_container(
    name: str = "web",
    container_id: str = "a" * 64,
    labels: dict | None = None,
    state: dict | None = None,
    restart_count: int = 0,
) -> MagicMock:
    """Build a mock Docker SDK container object."""
    container = MagicMock()
    container.name = name
    container.id = container_id
    container.status = "running"
    container.image.tags = ["example:latest"]
    container.image.id = "sha256:" + ("b" * 64)
    container.attrs = {
        "Config": {"Labels": labels if labels is not None else {}},
        "State": state if state is not None else {"Status": "running", "ExitCode": 0},
        "Image": "sha256:" + ("b" * 64),
        "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.2"}}},
        "Created": "2024-01-01T00:00:00Z",
        "HostConfig": {"RestartPolicy": {"Name": "no"}},
        "RestartCount": restart_count,
    }
    return container


class TestConnection:
    """Connection handling."""

    def test_connection_failure_is_raised(self):
        with patch(
            "app.docker_client.docker_client_wrapper.docker.DockerClient",
            side_effect=docker.errors.DockerException("no socket"),
        ):
            with pytest.raises(docker.errors.DockerException):
                DockerClientWrapper()

    def test_is_connected_is_false_when_ping_fails(self, wrapper, sdk_client):
        sdk_client.ping.side_effect = docker.errors.APIError("daemon gone")

        assert wrapper.is_connected() is False

    def test_is_connected_is_true_when_ping_succeeds(self, wrapper):
        assert wrapper.is_connected() is True

    def test_reconnect_reports_failure(self, wrapper):
        with patch(
            "app.docker_client.docker_client_wrapper.docker.DockerClient",
            side_effect=docker.errors.DockerException("still down"),
        ):
            assert wrapper.reconnect() is False

    def test_reconnect_reports_success(self, wrapper, sdk_client):
        with patch(
            "app.docker_client.docker_client_wrapper.docker.DockerClient",
            return_value=sdk_client,
        ):
            assert wrapper.reconnect() is True


class TestListingAndLookup:
    """Container listing and lookup."""

    def test_list_containers_passes_the_all_flag(self, wrapper, sdk_client):
        container = make_sdk_container()
        sdk_client.containers.list.return_value = [container]

        assert wrapper.list_containers(all_containers=True) == [container]
        sdk_client.containers.list.assert_called_once_with(all=True)

    def test_list_containers_returns_empty_list_on_failure(self, wrapper, sdk_client):
        sdk_client.containers.list.side_effect = docker.errors.APIError("daemon gone")
        sdk_client.ping.side_effect = docker.errors.APIError("daemon gone")

        with patch("app.docker_client.docker_client_wrapper.docker.DockerClient", return_value=sdk_client):
            assert wrapper.list_containers() == []

    def test_get_container_returns_none_when_not_found(self, wrapper, sdk_client):
        sdk_client.containers.get.side_effect = docker.errors.NotFound("no such container")

        assert wrapper.get_container("missing") is None

    def test_get_container_returns_none_on_api_error(self, wrapper, sdk_client):
        sdk_client.containers.get.side_effect = docker.errors.APIError("boom")

        assert wrapper.get_container("web") is None

    def test_list_containers_reconnects_when_the_connection_was_lost(self, wrapper, sdk_client):
        sdk_client.containers.list.side_effect = docker.errors.APIError("daemon gone")
        sdk_client.ping.side_effect = docker.errors.APIError("daemon gone")

        with patch("app.docker_client.docker_client_wrapper.docker.DockerClient", return_value=sdk_client):
            wrapper.list_containers()

        assert sdk_client.ping.call_count >= 2  # is_connected(), then reconnect()'s own _connect()


class TestContainerInfo:
    """``get_container_info`` output, which the monitoring engine consumes."""

    def test_info_contains_the_fields_the_engine_relies_on(self, wrapper):
        container = make_sdk_container(labels={"autoheal": "true"})

        info = wrapper.get_container_info(container)

        assert info["full_id"] == "a" * 64
        assert info["id"] == "a" * 12
        assert info["name"] == "web"
        assert info["stable_id"] == "web"
        assert info["labels"] == {"autoheal": "true"}
        assert info["state"]["Status"] == "running"
        assert info["health"] is None
        container.reload.assert_called_once()

    def test_restart_count_is_read_from_the_top_level_field(self, wrapper):
        # RestartCount is a sibling of State in the Docker inspect payload, not
        # nested inside it - a real regression, caught by an integration test
        # against a real daemon rather than this fixture's own shape.
        container = make_sdk_container(restart_count=3)

        assert wrapper.get_container_info(container)["restart_count"] == 3

    def test_stable_id_prefers_the_monitoring_id_label(self, wrapper):
        container = make_sdk_container(
            labels={
                "monitoring.id": "my-service",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            }
        )

        assert wrapper.get_container_info(container)["stable_id"] == "my-service"

    def test_stable_id_falls_back_to_compose_service(self, wrapper):
        container = make_sdk_container(
            name="stack-web-1",
            labels={
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )

        assert wrapper.get_container_info(container)["stable_id"] == "stack_web"

    def test_health_status_is_extracted(self, wrapper):
        container = make_sdk_container(
            state={
                "Status": "running",
                "ExitCode": 0,
                "Health": {
                    "Status": "unhealthy",
                    "FailingStreak": 4,
                    "Log": [{"ExitCode": 1, "Output": "boom"}],
                },
            }
        )

        health = wrapper.get_container_info(container)["health"]

        assert health["status"] == "unhealthy"
        assert health["failing_streak"] == 4
        assert health["log"] == {"ExitCode": 1, "Output": "boom"}

    def test_disappeared_container_yields_an_empty_info_dict(self, wrapper):
        """This is what the monitoring engine sees when a container is removed."""
        container = make_sdk_container()
        container.reload.side_effect = docker.errors.NotFound("no such container")

        assert wrapper.get_container_info(container) == {}


class TestContainerActions:
    """Restart/stop/exec behaviour."""

    def test_restart_returns_true_on_success(self, wrapper):
        container = make_sdk_container()

        assert wrapper.restart_container(container) is True
        container.restart.assert_called_once_with(timeout=10)

    def test_restart_returns_false_when_the_container_is_gone(self, wrapper):
        container = make_sdk_container()
        container.restart.side_effect = docker.errors.NotFound("no such container")

        assert wrapper.restart_container(container) is False

    def test_stop_returns_true_on_success(self, wrapper):
        container = make_sdk_container()

        assert wrapper.stop_container(container) is True
        container.stop.assert_called_once_with(timeout=10)

    def test_stop_returns_false_on_api_error(self, wrapper):
        container = make_sdk_container()
        container.stop.side_effect = docker.errors.APIError("boom")

        assert wrapper.stop_container(container) is False

    def test_exec_health_check_passes_on_exit_code_zero(self, wrapper):
        container = make_sdk_container()
        container.exec_run.return_value = MagicMock(exit_code=0, output=b"ok")

        assert wrapper.check_exec_health(container, ["true"]) is True

    def test_exec_health_check_fails_on_non_zero_exit(self, wrapper):
        container = make_sdk_container()
        container.exec_run.return_value = MagicMock(exit_code=1, output=b"nope")

        assert wrapper.check_exec_health(container, ["false"]) is False

    def test_exec_health_check_fails_when_exec_raises(self, wrapper):
        container = make_sdk_container()
        container.exec_run.side_effect = docker.errors.APIError("boom")

        assert wrapper.check_exec_health(container, ["true"]) is False

    def test_native_health_is_returned(self, wrapper):
        container = make_sdk_container(
            state={"Status": "running", "ExitCode": 0, "Health": {"Status": "healthy"}}
        )

        assert wrapper.get_docker_native_health(container) == "healthy"

    def test_native_health_is_none_without_a_health_check(self, wrapper):
        container = make_sdk_container()

        assert wrapper.get_docker_native_health(container) is None

    def test_native_health_returns_none_when_inspection_fails(self, wrapper):
        container = make_sdk_container()
        container.reload.side_effect = docker.errors.APIError("boom")

        assert wrapper.get_docker_native_health(container) is None

    def test_close_closes_the_sdk_client(self, wrapper, sdk_client):
        wrapper.close()

        sdk_client.close.assert_called_once()


class TestHealthChecks:
    """HTTP and TCP health checks, which resolve the container's own IP first."""

    def test_http_check_passes_on_expected_status(self, wrapper):
        container = make_sdk_container()
        with patch("app.docker_client.docker_client_wrapper.requests.get") as get:
            get.return_value = MagicMock(status_code=200)

            assert wrapper.check_http_health(container, "http://localhost:8080/health") is True
            get.assert_called_once_with("http://172.17.0.2:8080/health", timeout=5)

    def test_http_check_fails_on_unexpected_status(self, wrapper):
        container = make_sdk_container()
        with patch("app.docker_client.docker_client_wrapper.requests.get") as get:
            get.return_value = MagicMock(status_code=500)

            assert wrapper.check_http_health(container, "http://localhost/health") is False

    def test_http_check_fails_when_the_request_raises(self, wrapper):
        container = make_sdk_container()
        with patch("app.docker_client.docker_client_wrapper.requests.get", side_effect=OSError("no route")):
            assert wrapper.check_http_health(container, "http://localhost/health") is False

    def test_http_check_fails_without_a_container_ip(self, wrapper):
        container = make_sdk_container()
        container.attrs["NetworkSettings"] = {"Networks": {}}

        assert wrapper.check_http_health(container, "http://localhost/health") is False

    def test_tcp_check_passes_when_the_port_accepts_connections(self, wrapper):
        container = make_sdk_container()
        with patch("app.docker_client.docker_client_wrapper.socket.socket") as socket_cls:
            socket_cls.return_value.connect_ex.return_value = 0

            assert wrapper.check_tcp_health(container, 8080) is True

    def test_tcp_check_fails_when_the_port_refuses_connections(self, wrapper):
        container = make_sdk_container()
        with patch("app.docker_client.docker_client_wrapper.socket.socket") as socket_cls:
            socket_cls.return_value.connect_ex.return_value = 111  # ECONNREFUSED

            assert wrapper.check_tcp_health(container, 8080) is False

    def test_tcp_check_fails_without_a_container_ip(self, wrapper):
        container = make_sdk_container()
        container.attrs["NetworkSettings"] = {"Networks": {}}

        assert wrapper.check_tcp_health(container, 8080) is False


class TestEvents:
    """Docker event stream."""

    def test_events_stream_is_returned(self, wrapper, sdk_client):
        sdk_client.events.return_value = iter([{"status": "start"}])

        stream = wrapper.get_events(decode=True, filters={"type": "container"})

        assert list(stream) == [{"status": "start"}]
        sdk_client.events.assert_called_once_with(decode=True, filters={"type": "container"})

    def test_events_returns_none_on_failure(self, wrapper, sdk_client):
        sdk_client.events.side_effect = docker.errors.APIError("boom")

        assert wrapper.get_events() is None
