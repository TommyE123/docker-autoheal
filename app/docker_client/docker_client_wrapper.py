"""
Docker client wrapper for container operations
Provides interface to Docker API for monitoring and management
"""

import logging
import socket
from typing import TYPE_CHECKING, Any

import docker
import docker.errors
import requests

if TYPE_CHECKING:
    from docker.models.containers import Container

logger = logging.getLogger(__name__)


def _require_container_id(container: Container) -> str:
    """Return the container's ID; the SDK types it optional but the daemon always sets it."""
    container_id = container.id
    if container_id is None:
        raise ValueError("container has no id")
    return container_id


def recovery_identifier[S](stable_id: S, labels: dict) -> S | str:
    """
    Key for one running container's recovery state, derived from its labels.

    Restart counts, cooldown, backoff and quarantine belong to a single container,
    so replicas of a scaled Compose service must not share them: every Compose
    container is keyed by its project, service and container number. The project
    and service are taken from their separate labels rather than from the stable
    ID, because ``project_service`` is ambiguous (project ``foo_bar`` with service
    ``baz`` and project ``foo`` with service ``bar_baz`` both give ``foo_bar_baz``).
    An explicit ``monitoring.id`` label is the user's chosen identity: it is never
    suffixed, and it is keyed under a ``monitoring.id:`` prefix so it can never equal
    a generated key. Compose project and service names cannot contain ``:`` or ``#``,
    so the delimiters of a generated key are unambiguous.

    Args:
        stable_id: The container's stable identifier
        labels: Container labels

    Returns:
        ``"monitoring.id:{stable_id}"`` for an explicit ``monitoring.id``,
        ``"compose:{project}:{service}#{N}"`` for Compose container number N,
        otherwise ``stable_id``
    """
    if "monitoring.id" in labels:
        return f"monitoring.id:{stable_id}"
    project = labels.get("com.docker.compose.project")
    service = labels.get("com.docker.compose.service")
    if not (project and service):
        return stable_id
    number = labels.get("com.docker.compose.container-number")
    if isinstance(number, str) and number.isdecimal():
        return f"compose:{project}:{service}#{int(number)}"
    return stable_id


class DockerClientWrapper:
    """Wrapper around Docker SDK client with retry logic"""

    def __init__(self, base_url: str = "unix://var/run/docker.sock") -> None:
        """
        Initialize Docker client
        Args:
            base_url: Docker daemon socket URL
        """
        self.base_url = base_url
        self._client: docker.DockerClient | None = None
        self._connect()

    def _connect(self) -> None:
        """Connect to Docker daemon with retry logic"""
        try:
            self._client = docker.DockerClient(base_url=self.base_url)
            # Test connection
            try:
                self._client.ping()
            except Exception:
                # Release the new client's sockets now rather than leaving it to
                # garbage collection. It stays assigned, as before: a closed
                # docker-py client recreates its pools on the next request.
                self._close_client(self._client)
                raise
            logger.info("Connected to Docker daemon at %s", self.base_url)
        except Exception as e:
            logger.error("Failed to connect to Docker daemon: %s", e)
            raise

    def _require_client(self) -> docker.DockerClient:
        """Return the SDK client, raising if it is not available.

        Called inside each method's existing ``try`` block so a missing client is
        logged and handled exactly like any other Docker failure.
        """
        if self._client is None:
            raise RuntimeError("Docker client not initialized")
        return self._client

    @staticmethod
    def _close_client(client: docker.DockerClient) -> None:
        """Close an SDK client best-effort: a close error is logged, never raised"""
        try:
            client.close()
        except Exception as e:
            logger.warning("Failed to close Docker client: %s", e)

    def reconnect(self) -> bool:
        """Reconnect to Docker daemon"""
        if self._client is not None:
            # Close the client being replaced so its sockets are released now.
            self._close_client(self._client)
        try:
            self._connect()
        except Exception as e:
            logger.error("Reconnection failed: %s", e)
            return False
        else:
            return True

    def is_connected(self) -> bool:
        """Check if connected to Docker daemon"""
        try:
            if self._client:
                self._client.ping()
                return True
        except Exception as e:
            logger.warning("Connection check failed: %s", e)
        return False

    def list_containers(self, all_containers: bool = False) -> list[Container]:
        """
        List containers
        Args:
            all_containers: If True, list all containers including stopped ones
        Returns:
            List of Container objects
        """
        try:
            return self._require_client().containers.list(all=all_containers)
        except Exception as e:
            logger.error("Failed to list containers: %s", e)
            if not self.is_connected():
                self.reconnect()
            return []

    def get_container(self, container_id: str) -> Container | None:
        """
        Get container by ID or name
        Args:
            container_id: Container ID or name
        Returns:
            Container object or None if not found
        """
        try:
            return self._require_client().containers.get(container_id)
        except docker.errors.NotFound:
            logger.warning("Container %s not found", container_id)
            return None
        except Exception as e:
            logger.error("Failed to get container %s: %s", container_id, e)
            return None

    def get_container_info(self, container: Container, refresh: bool = True) -> dict[str, Any]:
        """
        Get detailed container information
        Args:
            container: Container object
            refresh: If True, reload the container first. Pass False when the
                container was inspected moments ago (e.g. by ``list_containers``)
                to avoid a second round trip.
        Returns:
            Dictionary with container details
        """
        try:
            if refresh:
                container.reload()  # Refresh container state
            attrs = container.attrs

            # Extract relevant information
            labels = attrs.get("Config", {}).get("Labels", {})

            # Get stable identifier with same logic as monitoring_engine
            # Priority 1: Explicit monitoring.id label
            if "monitoring.id" in labels:
                stable_id = labels["monitoring.id"]
            else:
                # Priority 2: Docker Compose service name (project_service format)
                compose_project = labels.get("com.docker.compose.project")
                compose_service = labels.get("com.docker.compose.service")
                if compose_project and compose_service:
                    stable_id = f"{compose_project}_{compose_service}"
                else:
                    # Priority 3: Container name (fallback)
                    stable_id = container.name

            # Get image info for tracking
            image = container.image
            if image is None:
                raise ValueError("container has no image")
            image_name = image.tags[0] if image.tags else image.id
            image_id = attrs.get("Image", "")

            container_id = _require_container_id(container)

            # Get network info for uniqueness
            networks = list(attrs.get("NetworkSettings", {}).get("Networks", {}).keys())

            return {
                "id": container_id[:12],  # Short ID
                "full_id": container_id,
                "name": container.name,
                "stable_id": stable_id,  # NEW: Stable identifier for tracking
                # Per-replica key for restart counts and quarantine
                "recovery_id": recovery_identifier(stable_id, labels),
                "image": image_name,
                "image_id": image_id,  # NEW: For version tracking
                "status": container.status,
                "state": attrs.get("State", {}),
                "labels": labels,
                "networks": networks,  # NEW: For handling name conflicts
                "created": attrs.get("Created"),
                "started_at": attrs.get("State", {}).get("StartedAt"),
                "finished_at": attrs.get("State", {}).get("FinishedAt"),
                "exit_code": attrs.get("State", {}).get("ExitCode"),
                # RestartCount is a top-level inspect field, not nested under State.
                "restart_count": attrs.get("RestartCount", 0),
                "health": self._get_health_status(attrs),
                "restart_policy": attrs.get("HostConfig", {}).get("RestartPolicy", {}),
                "compose_project": labels.get("com.docker.compose.project"),  # NEW: Compose project
                "compose_service": labels.get("com.docker.compose.service"),  # NEW: Compose service
            }
        except Exception as e:
            logger.error("Failed to get container info for %s: %s", container.name, e)
            return {}

    def _get_health_status(self, attrs: dict) -> dict[str, Any] | None:
        """Extract health status from container attributes"""
        state = attrs.get("State", {})
        health = state.get("Health")

        if health:
            return {
                "status": health.get("Status"),  # healthy, unhealthy, starting
                "failing_streak": health.get("FailingStreak", 0),
                "log": health.get("Log", [])[-1] if health.get("Log") else None,
            }
        return None

    def restart_container(self, container: Container, timeout: int = 10) -> bool:
        """
        Restart a container
        Args:
            container: Container object
            timeout: Timeout in seconds
        Returns:
            True if restart successful, False otherwise
        """
        try:
            logger.info(
                "Restarting container %s (%s)",
                container.name,
                _require_container_id(container)[:12],
            )
            container.restart(timeout=timeout)
        except Exception as e:
            logger.error("Failed to restart container %s: %s", container.name, e)
            return False
        else:
            return True

    def stop_container(self, container: Container, timeout: int = 10) -> bool:
        """
        Stop a container
        Args:
            container: Container object
            timeout: Timeout in seconds
        Returns:
            True if stop successful, False otherwise
        """
        try:
            logger.info(
                "Stopping container %s (%s)", container.name, _require_container_id(container)[:12]
            )
            container.stop(timeout=timeout)
        except Exception as e:
            logger.error("Failed to stop container %s: %s", container.name, e)
            return False
        else:
            return True

    def execute_command(self, container: Container, command: list[str]) -> tuple[int, str]:
        """
        Execute command in container
        Args:
            container: Container object
            command: Command to execute as list
        Returns:
            Tuple of (exit_code, output)
        """
        try:
            exec_result = container.exec_run(command)
            # Without stream/socket/demux, the SDK returns an int exit code and bytes.
            exit_code = exec_result.exit_code
            output = exec_result.output
            if exit_code is None or not isinstance(output, bytes):
                raise TypeError("unexpected exec_run result")
            return exit_code, output.decode("utf-8")
        except Exception as e:
            logger.error("Failed to execute command in container %s: %s", container.name, e)
            return -1, str(e)

    def check_http_health(
        self,
        container: Container,
        endpoint: str,
        expected_status: int = 200,
        timeout: int = 5,
    ) -> bool:
        """
        Perform HTTP health check on container
        Args:
            container: Container object
            endpoint: HTTP endpoint to check (e.g., "http://localhost:3131/health")
            expected_status: Expected HTTP status code
            timeout: Request timeout
        Returns:
            True if health check passes, False otherwise
        """
        try:
            # Get container's network settings
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})

            # Try to get IP address from any network
            ip_address = None
            for network_info in networks.values():
                ip_address = network_info.get("IPAddress")
                if ip_address:
                    break

            if not ip_address:
                logger.warning("Cannot get IP address for container %s", container.name)
                return False

            # Replace localhost/127.0.0.1 with container IP
            endpoint = endpoint.replace("localhost", ip_address).replace("127.0.0.1", ip_address)

            response = requests.get(endpoint, timeout=timeout)
        except Exception as e:
            logger.warning("HTTP health check failed for %s: %s", container.name, e)
            return False
        else:
            return response.status_code == expected_status

    def get_events(
        self,
        decode: bool = True,
        filters: dict[str, Any] | None = None,
        since: Any = None,
    ) -> Any:
        """
        Get Docker events stream
        Args:
            decode: Whether to decode JSON events
            filters: Event filters (dict)
            since: Replay events from this time (Unix time or datetime) before streaming
        Returns:
            Generator of events
        """
        try:
            return self._require_client().events(decode=decode, filters=filters, since=since)
        except Exception as e:
            logger.error("Failed to get events stream: %s", e)
            return None

    def check_tcp_health(self, container: Container, port: int, timeout: int = 5) -> bool:
        """
        Perform TCP health check on container
        Args:
            container: Container object
            port: TCP port to check
            timeout: Connection timeout
        Returns:
            True if TCP connection successful, False otherwise
        """
        try:
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})

            ip_address = None
            for network_info in networks.values():
                ip_address = network_info.get("IPAddress")
                if ip_address:
                    break

            if not ip_address:
                logger.warning("Cannot get IP address for container %s", container.name)
                return False

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((ip_address, port))
        except Exception as e:
            logger.warning("TCP health check failed for %s: %s", container.name, e)
            return False
        else:
            return result == 0

    def check_exec_health(self, container: Container, command: list[str]) -> bool:
        """
        Perform exec-based health check on container
        Args:
            container: Container object
            command: Command to execute
        Returns:
            True if command exits with 0, False otherwise
        """
        exit_code, _ = self.execute_command(container, command)
        return exit_code == 0

    def get_docker_native_health(self, container: Container) -> str | None:
        """
        Get Docker's native health check status
        Args:
            container: Container object
        Returns:
            Health status string or None if no health check defined
        """
        try:
            container.reload()
            info = self.get_container_info(container)
            health = info.get("health")
            if health:
                return health.get("status")
        except Exception as e:
            logger.error("Failed to get native health for %s: %s", container.name, e)
            return None
        else:
            return None

    def close(self) -> None:
        """Close Docker client connection"""
        if self._client:
            self._client.close()
            logger.info("Docker client connection closed")
