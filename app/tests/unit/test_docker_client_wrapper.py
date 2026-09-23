"""
Unit tests for :class:`DockerClientWrapper`.

The Docker SDK is mocked out entirely - these tests never talk to a Docker
daemon. They focus on the boundary behaviour the monitoring engine relies on:
inspection results and graceful handling of Docker API failures.
"""

import socket
from unittest.mock import MagicMock, patch

import docker
import pytest

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

    def test_restart_count_defaults_to_zero_when_absent(self, wrapper):
        container = make_sdk_container()
        del container.attrs["RestartCount"]

        assert wrapper.get_container_info(container)["restart_count"] == 0

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

    def test_exec_health_check_fails_on_malformed_exec_result(self, wrapper):
        # ``output`` is expected to be bytes (``.decode()`` is called on it);
        # a malformed exec result without a usable ``output`` attribute makes
        # ``execute_command`` raise, which ``check_exec_health`` must treat as
        # a failed check rather than propagating the exception.
        container = make_sdk_container()
        container.exec_run.return_value = MagicMock(exit_code=0, output=None)

        assert wrapper.check_exec_health(container, ["true"]) is False

    def test_native_health_returns_unexpected_status_value(self, wrapper):
        """Unrecognised health status strings are passed through as-is."""
        container = make_sdk_container(
            state={"Status": "running", "ExitCode": 0, "Health": {"Status": "weird_status"}}
        )

        assert wrapper.get_docker_native_health(container) == "weird_status"

    def test_native_health_is_none_when_health_key_missing_from_info(self, wrapper):
        container = make_sdk_container()
        # No "Health" entry under State at all (not merely an empty dict).
        assert "Health" not in container.attrs["State"]

        assert wrapper.get_docker_native_health(container) is None

    def test_native_health_is_none_when_container_disappears_during_inspection(self, wrapper):
        container = make_sdk_container()
        container.reload.side_effect = docker.errors.NotFound("no such container")

        assert wrapper.get_docker_native_health(container) is None


class TestTcpHealth:
    """``check_tcp_health`` - mocked sockets only, no real network access."""

    def test_tcp_health_check_succeeds(self, wrapper):
        container = make_sdk_container()
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0

        with patch(
            "app.docker_client.docker_client_wrapper.socket.socket",
            return_value=mock_sock,
        ) as mock_socket_cls:
            assert wrapper.check_tcp_health(container, port=8080) is True

        mock_socket_cls.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_sock.settimeout.assert_called_once_with(5)
        mock_sock.connect_ex.assert_called_once_with(("172.17.0.2", 8080))
        mock_sock.close.assert_called_once()

    def test_tcp_health_check_fails_when_connection_is_refused(self, wrapper):
        container = make_sdk_container()
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = ConnectionRefusedError("connection refused")

        with patch(
            "app.docker_client.docker_client_wrapper.socket.socket",
            return_value=mock_sock,
        ):
            assert wrapper.check_tcp_health(container, port=8080) is False

    def test_tcp_health_check_fails_on_non_zero_connect_result(self, wrapper):
        # connect_ex normally reports failure by returning a non-zero errno
        # rather than raising.
        container = make_sdk_container()
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 111  # ECONNREFUSED

        with patch(
            "app.docker_client.docker_client_wrapper.socket.socket",
            return_value=mock_sock,
        ):
            assert wrapper.check_tcp_health(container, port=8080) is False
        mock_sock.close.assert_called_once()

    def test_tcp_health_check_fails_on_timeout(self, wrapper):
        container = make_sdk_container()
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = socket.timeout("timed out")

        with patch(
            "app.docker_client.docker_client_wrapper.socket.socket",
            return_value=mock_sock,
        ):
            assert wrapper.check_tcp_health(container, port=8080) is False

    def test_tcp_health_check_fails_on_dns_resolution_failure(self, wrapper):
        container = make_sdk_container()
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = socket.gaierror("name resolution failed")

        with patch(
            "app.docker_client.docker_client_wrapper.socket.socket",
            return_value=mock_sock,
        ):
            assert wrapper.check_tcp_health(container, port=8080) is False

    def test_tcp_health_check_fails_on_invalid_port(self, wrapper):
        container = make_sdk_container()
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = OverflowError("port must be 0-65535")

        with patch(
            "app.docker_client.docker_client_wrapper.socket.socket",
            return_value=mock_sock,
        ):
            assert wrapper.check_tcp_health(container, port=99999) is False
        # Proves the caller-supplied invalid port reached connect_ex
        # unmodified, rather than being normalized or ignored.
        mock_sock.connect_ex.assert_called_once_with(("172.17.0.2", 99999))

    def test_tcp_health_check_fails_on_missing_port(self, wrapper):
        container = make_sdk_container()
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = TypeError("an integer is required")

        with patch(
            "app.docker_client.docker_client_wrapper.socket.socket",
            return_value=mock_sock,
        ):
            assert wrapper.check_tcp_health(container, port=None) is False
        mock_sock.connect_ex.assert_called_once_with(("172.17.0.2", None))

    def test_tcp_health_check_fails_when_container_has_no_ip_address(self, wrapper):
        container = make_sdk_container()
        container.attrs["NetworkSettings"] = {"Networks": {"bridge": {"IPAddress": ""}}}

        with patch("app.docker_client.docker_client_wrapper.socket.socket") as mock_socket_cls:
            assert wrapper.check_tcp_health(container, port=8080) is False

        mock_socket_cls.assert_not_called()

    def test_tcp_health_check_fails_when_container_disappears_during_inspection(self, wrapper):
        container = make_sdk_container()
        container.reload.side_effect = docker.errors.NotFound("no such container")

        with patch("app.docker_client.docker_client_wrapper.socket.socket") as mock_socket_cls:
            assert wrapper.check_tcp_health(container, port=8080) is False

        mock_socket_cls.assert_not_called()


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
