"""
Container health evaluation for Docker Auto-Heal Service
Decides from a container's state and health checks whether it needs a restart
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from app.config.config_manager import config_manager

if TYPE_CHECKING:
    from docker.models.containers import Container

    from app.config.config_manager import AutoHealConfig, HealthCheckConfig
    from app.monitor.monitoring_engine import DockerClient
    from app.monitor.uptime_kuma_monitor import UptimeKumaMonitor

logger = logging.getLogger(__name__)


class HealthEvaluator:
    """Evaluates whether a container needs a restart"""

    def __init__(
        self, docker_client: DockerClient, uptime_kuma_monitor: UptimeKumaMonitor | None = None
    ) -> None:
        """
        Initialize the evaluator
        Args:
            docker_client: Docker client wrapper instance
            uptime_kuma_monitor: Uptime Kuma monitor, or None when it is not set up
        """
        self.docker_client = docker_client
        self.uptime_kuma_monitor = uptime_kuma_monitor

    async def evaluate(
        self, container: Container, info: dict, stable_id: str | None
    ) -> tuple[bool, str]:
        """
        Evaluate if container needs restart based on health checks
        Args:
            container: Container object
            info: Container information dict
            stable_id: The container's stable identifier
        Returns:
            Tuple of (needs_restart: bool, reason: str)
        """
        config = config_manager.get_config()
        state = info.get("state", {})
        status = state.get("Status", "").lower()

        if status == "starting":
            logger.debug(
                "Container %s is still starting, skipping health evaluation",
                info.get("name"),
            )
            return False, "Container is starting"

        if status in ["exited", "stopped", "dead"]:
            stopped_result = self._stopped_container_result(config, info, state)
            if stopped_result is not None:
                return stopped_result

        if config.restart.mode in ["health", "both"]:
            failure = await self._health_check_failure(container, info, stable_id)
            if failure is not None:
                return True, failure

        # Check Uptime-Kuma monitor status (if configured and enabled)
        if (
            self.uptime_kuma_monitor
            and stable_id is not None
            and await self.uptime_kuma_monitor.should_restart_from_uptime_kuma(stable_id)
        ):
            return True, "Uptime-Kuma monitor reports DOWN"

        return False, ""

    @staticmethod
    def _stopped_container_result(
        config: AutoHealConfig, info: dict, state: dict
    ) -> tuple[bool, str] | None:
        """
        Restart decision for an exited container, or None when the restart mode ignores exits
        Args:
            config: Current configuration
            info: Container information dict
            state: The container's state from ``info``
        Returns:
            Tuple of (needs_restart: bool, reason: str), or None
        """
        if config.restart.mode not in ["on-failure", "both"]:
            return None

        exit_code = state.get("ExitCode", 0)
        # If exit code is 0 (clean stop) and we respect manual stops, don't restart
        if exit_code == 0 and config.restart.respect_manual_stop:
            logger.debug(
                "Container %s stopped cleanly (exit 0), respecting manual stop",
                info.get("name"),
            )
            return False, "Manual stop (exit 0)"

        # For non-zero exit codes or if we don't respect manual stops, restart
        if exit_code != 0:
            return True, f"Container exited with code {exit_code}"
        # exit_code = 0 but respect_manual_stop = False
        return True, "Container stopped (exit 0)"

    async def _health_check_failure(
        self, container: Container, info: dict, stable_id: str | None
    ) -> str | None:
        """
        The reason a custom or Docker native health check fails, or None when both pass
        Args:
            container: Container object
            info: Container information dict
            stable_id: The container's stable identifier
        Returns:
            Failure reason, or None
        """
        # Custom health checks are looked up by stable_id, name, then ID for backwards
        # compatibility
        custom_hc = None
        for key in (stable_id, info.get("name"), info.get("full_id")):
            if key is not None:
                custom_hc = config_manager.get_custom_health_check(key)
                if custom_hc:
                    break
        if custom_hc and not await self.perform_custom_health_check(container, custom_hc):
            return f"Custom health check failed ({custom_hc.check_type})"

        # Then check Docker native health
        health = info.get("health")
        if health and health.get("status") == "unhealthy":
            return "Docker health check reports unhealthy"
        return None

    async def perform_custom_health_check(
        self, container: Container, health_check: HealthCheckConfig
    ) -> bool:
        """
        Perform custom health check on container
        Args:
            container: Container object
            health_check: Health check configuration
        Returns:
            True if healthy, False otherwise
        """
        check_type = health_check.check_type

        try:
            if check_type == "http":
                # HealthCheckConfig does not require these for http checks; a missing
                # value fails here and is reported as unhealthy by the handler below.
                endpoint = health_check.http_endpoint
                expected_status = health_check.http_expected_status
                if endpoint is None or expected_status is None:
                    raise ValueError("missing http_endpoint or http_expected_status")
                return await asyncio.to_thread(
                    self.docker_client.check_http_health,
                    container,
                    endpoint,
                    expected_status,
                    health_check.timeout_seconds,
                )
            if check_type == "tcp":
                port = health_check.tcp_port
                if port is None:
                    raise ValueError("missing tcp_port")
                return await asyncio.to_thread(
                    self.docker_client.check_tcp_health,
                    container,
                    port,
                    health_check.timeout_seconds,
                )
            if check_type == "exec":
                command = health_check.exec_command
                if command is None:
                    raise ValueError("missing exec_command")
                return await asyncio.to_thread(
                    self.docker_client.check_exec_health,
                    container,
                    command,
                )
            if check_type == "docker":
                status = await asyncio.to_thread(
                    self.docker_client.get_docker_native_health, container
                )
                return status == "healthy" if status else True  # Assume healthy if no check
            logger.warning("Unknown health check type: %s", check_type)
        except Exception as e:
            logger.error("Error performing health check: %s", e)
            return False
        else:
            return True
