"""
Core monitoring engine for Docker Auto-Heal Service
Monitors containers and performs auto-healing actions
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Protocol

from app.config.config_manager import (
    AutoHealConfig,
    AutoHealEvent,
    HealthCheckConfig,
    config_manager,
)
from app.docker_client.docker_client_wrapper import recovery_identifier
from app.monitor.auto_discovery import AutoDiscovery
from app.monitor.health import HealthEvaluator
from app.monitor.selection import should_monitor
from app.notifications.notification_manager import notification_manager

if TYPE_CHECKING:
    from docker.models.containers import Container

    from app.monitor.uptime_kuma_monitor import UptimeKumaMonitor

logger = logging.getLogger(__name__)

# Consecutive healthy checks, on the same container run, before a quarantined container
# is released. The container must also have been up for this many monitoring intervals.
QUARANTINE_STABLE_CHECKS = 3


class DockerClient(Protocol):
    """
    The subset of ``DockerClientWrapper`` the monitoring engine calls.

    Defaults are ``...`` because the real defaults live on the wrapper.

    Declared at the injection boundary so test doubles can satisfy the engine
    without inheriting the real wrapper (whose constructor connects to Docker).
    """

    def is_connected(self) -> bool: ...

    def reconnect(self) -> bool: ...

    def list_containers(self, all_containers: bool = ...) -> list[Container]: ...

    def get_container(self, container_id: str) -> Container | None: ...

    def get_container_info(self, container: Container, refresh: bool = ...) -> dict[str, Any]: ...

    def restart_container(self, container: Container, timeout: int = ...) -> bool: ...

    def check_http_health(
        self,
        container: Container,
        endpoint: str,
        expected_status: int = ...,
        timeout: int = ...,
    ) -> bool: ...

    def check_tcp_health(self, container: Container, port: int, timeout: int = ...) -> bool: ...

    def check_exec_health(self, container: Container, command: list[str]) -> bool: ...

    def get_docker_native_health(self, container: Container) -> str | None: ...

    def get_events(self, decode: bool = ..., filters: Any = ..., since: Any = ...) -> Any: ...


class MonitoringEngine:
    """
    Core monitoring engine that checks container health and performs restarts
    """

    def __init__(self, docker_client: DockerClient) -> None:
        """
        Initialize monitoring engine
        Args:
            docker_client: Docker client wrapper instance
        """
        self.docker_client = docker_client
        self._running = False
        self._task: asyncio.Task | None = None
        self._event_task: asyncio.Task | None = None
        self._last_restart_times: dict[str, datetime] = {}
        self._backoff_delays: dict[str, int] = {}
        # Per recovery ID: the container (by Docker ID) and when its current unbroken run
        # of healthy evaluations began. A recreated container starts a new run.
        self._healthy_since: dict[str, tuple[str | None, datetime]] = {}
        self._next_allowed_restart: dict[str, datetime] = {}
        # The container (by Docker ID) whose failure started each pending wait. Replicas
        # sharing a recovery ID share the wait, so only its owner recovering may cancel
        # it. A recreated container has a new ID, so it never inherits a predecessor's wait.
        self._restart_wait_owner: dict[str, str | None] = {}
        # The cycle in which the owner last confirmed each pending wait by failing again.
        # A wait the owner did not confirm in the previous cycle (it was quarantined, in
        # maintenance, or Docker was unavailable) is stale: the failure was not observed
        # continuously, so the next failure starts a fresh wait instead of using it.
        self._restart_wait_seen: dict[str, int] = {}
        # Counts monitoring cycles. A quarantined container's healthy checks are consecutive
        # only if each happened in the cycle after the previous one, so a skipped or failed
        # check, or a failed cycle, breaks the streak without any explicit reset.
        self._check_cycle = 0
        # Per container (by Docker ID, since replicas can share a recovery ID): StartedAt,
        # consecutive healthy checks while quarantined, and the cycle of the latest one.
        # _check_containers checks one container at a time and the update has no await, so
        # no lock is needed. Concurrent checks of one container would need one.
        self._quarantine_streaks: dict[str, tuple[str, int, int]] = {}
        self._health_evaluator = HealthEvaluator(docker_client)
        self._auto_discovery = AutoDiscovery(docker_client, self._container_identifiers)

    @property
    def uptime_kuma_monitor(self) -> UptimeKumaMonitor | None:
        """
        The Uptime Kuma monitor, or None when Uptime Kuma is not set up.

        Attached by the service after construction. Health evaluation reads it.
        """
        return self._health_evaluator.uptime_kuma_monitor

    @uptime_kuma_monitor.setter
    def uptime_kuma_monitor(self, monitor: UptimeKumaMonitor | None) -> None:
        self._health_evaluator.uptime_kuma_monitor = monitor

    def get_stable_identifier(self, info: dict) -> str | None:
        """
        Get stable identifier for a container with priority fallback.

        Priority:
        1. monitoring.id label (explicit stable ID)
        2. com.docker.compose.service + project (compose service name)
        3. container name

        This handles:
        - Auto-generated names (uses compose service)
        - Name conflicts (uses compose project + service)
        - Explicit tracking (uses monitoring.id label)

        Args:
            info: Container information dict

        Returns:
            Stable identifier string, or None if the container info carries no name
            to fall back to

        Note:
            An empty ``monitoring.id`` label is returned as-is. Container
            discovery must not use this method for that reason; it uses
            ``AutoDiscovery``, which ignores an empty label.
        """
        labels = info.get("labels", {})

        # Priority 1: Explicit monitoring.id label
        if "monitoring.id" in labels:
            return labels["monitoring.id"]

        # Priority 2: Docker Compose service name
        compose_project = labels.get("com.docker.compose.project")
        compose_service = labels.get("com.docker.compose.service")
        if compose_project and compose_service:
            return f"{compose_project}_{compose_service}"

        # Priority 3: Container name (fallback)
        return info.get("name")

    def get_recovery_identifier(self, info: dict) -> str | None:
        """
        Get the key for a container's restart count, cooldown, backoff and quarantine.

        Every Compose container is keyed by its project, service and container
        number (see ``recovery_identifier``), so replicas of a scaled service recover
        independently, including ``#1`` for an unscaled service. Configuration (selection, health
        checks, Uptime Kuma mappings) stays keyed by ``get_stable_identifier``.

        Args:
            info: Container information dict

        Returns:
            Recovery identifier string, or None if there is no stable identifier
        """
        return recovery_identifier(self.get_stable_identifier(info), info.get("labels", {}))

    def _container_identifiers(self, info: dict) -> tuple[str, str, str] | None:
        """
        Full ID, name and recovery ID of a container, or None if any is missing.

        ``get_container_info`` returns an empty dict when inspection fails, so the
        identifiers cannot be assumed present.

        Args:
            info: Container information dict

        Returns:
            Tuple of (container_id, container_name, recovery_id), or None
        """
        container_id = info.get("full_id")
        container_name = info.get("name")
        recovery_id = self.get_recovery_identifier(info)
        if not container_id or not container_name or recovery_id is None:
            return None
        return container_id, container_name, recovery_id

    async def start(self) -> None:
        """Start the monitoring engine"""
        if self._running:
            logger.warning("Monitoring engine already running")
            return

        self._running = True

        # Taken before the scan so a container started while it runs is replayed, not missed
        events_since = int(time.time())

        # Proactively scan for existing containers with the configured monitoring label
        await self._scan_existing_containers()

        self._task = asyncio.create_task(self._monitor_loop())
        self._event_task = asyncio.create_task(self._event_listener_loop(events_since))
        logger.info("Monitoring engine started")
        monitor_config = config_manager.get_config().monitor
        logger.info(
            "Event listener started for auto-monitoring containers with %s=%s label",
            monitor_config.label_key,
            monitor_config.label_value,
        )

    async def stop(self) -> None:
        """Stop the monitoring engine"""
        if not self._running:
            return

        logger.info("Stopping monitoring engine...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # Expected during shutdown
            except Exception as e:
                logger.warning("Error stopping monitor loop: %s", e)

        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass  # Expected during shutdown
            except Exception as e:
                logger.warning("Error stopping event listener: %s", e)

        logger.info("Monitoring engine stopped")
        logger.info("Event listener stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop"""
        while self._running:
            try:
                config = config_manager.get_config()
                interval = config.monitor.interval_seconds

                # Perform monitoring check
                await self._check_containers()

                # Wait for next interval
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in monitoring loop: %s", e)
                await asyncio.sleep(5)  # Brief pause before retry

    async def _check_containers(self) -> None:
        """
        Check all containers and perform auto-healing if needed

        Containers are checked one at a time. ``_quarantine_streaks`` relies on that:
        running the checks concurrently would need a per-container lock around its
        read-modify-write.
        """
        self._check_cycle += 1
        # A streak not extended last cycle is over; this also forgets removed containers
        self._quarantine_streaks = {
            container_id: streak
            for container_id, streak in self._quarantine_streaks.items()
            if streak[2] >= self._check_cycle - 1
        }
        try:
            # Ensure Docker connection is active
            if not self.docker_client.is_connected():
                logger.warning("Docker connection lost, attempting reconnect...")
                if not self.docker_client.reconnect():
                    logger.error("Failed to reconnect to Docker")
                    return

            # Get ALL containers (including stopped) to detect failures
            containers = await asyncio.to_thread(
                self.docker_client.list_containers, all_containers=True
            )

            # A wait belongs to the container that started it; drop those that are gone.
            # list_containers returns [] when the Docker call fails, which says nothing
            # about whether the containers still exist.
            if containers:
                listed_ids = {container.id for container in containers}
                abandoned = [
                    recovery_id
                    for recovery_id, owner in self._restart_wait_owner.items()
                    if owner not in listed_ids
                ]
                for recovery_id in abandoned:
                    self._clear_restart_wait(recovery_id)
                self._clear_healthy_runs_not_in(listed_ids)

            for container in containers:
                try:
                    await self._check_single_container(container)
                except Exception as e:
                    logger.error("Error checking container %s: %s", container.name, e)

        except Exception as e:
            logger.exception("Error checking containers: %s", e)

    async def _check_single_container(self, container: Container) -> None:
        """
        Check a single container and perform auto-healing if needed
        Args:
            container: Container object to check
        """
        # Check if maintenance mode is enabled
        if config_manager.is_maintenance_mode():
            logger.debug("Maintenance mode is enabled, skipping container checks")
            return

        config = config_manager.get_config()

        # Get container info
        info = await asyncio.to_thread(self.docker_client.get_container_info, container)
        container_id = info.get("full_id")
        container_name = info.get("name")

        # Check if container should be monitored
        if not self.should_monitor_container(container, info):
            # No longer monitored: a wait it started would otherwise linger
            self._clear_restart_waits_owned_by(container_id)
            self._clear_healthy_runs_owned_by(container_id)
            return

        # Check if container is quarantined (by recovery ID, name, or ID for backwards compatibility)
        identifiers = self._container_identifiers(info)
        if identifiers is None:
            logger.warning(
                "Skipping container with incomplete identifiers: %s",
                container_name or container_id,
            )
            return
        container_id, container_name, recovery_id = identifiers
        quarantine_id = None
        if config_manager.is_quarantined(recovery_id):
            quarantine_id = recovery_id
        elif config_manager.is_quarantined(container_name):
            quarantine_id = container_name
        elif config_manager.is_quarantined(container_id):
            quarantine_id = container_id

        if quarantine_id:
            released = await self._check_quarantined_container(
                container, info, quarantine_id, recovery_id
            )
            if not released:
                logger.debug(
                    "Container %s (recovery_id: %s) is quarantined and not yet stable, skipping",
                    container_name,
                    recovery_id,
                )
            return

        # Check if container needs healing
        needs_restart, reason = await self._evaluate_container_health(container, info)

        if needs_restart:
            self._healthy_since.pop(recovery_id, None)
            await self._handle_container_restart(container, info, reason)
            return

        self._note_healthy_container(recovery_id, container_id, info, config)

    def _note_healthy_container(
        self, recovery_id: str, container_id: str | None, info: dict, config: AutoHealConfig
    ) -> None:
        """Update restart state for a container that was evaluated as healthy"""
        if self._restart_wait_owner.get(recovery_id) == container_id:
            # Recovered on its own: drop the restart it was waiting out its backoff for
            self._clear_restart_wait(recovery_id)
        self._reset_backoff_if_stable(recovery_id, container_id, info, config)

    def _reset_backoff_if_stable(
        self, recovery_id: str, container_id: str | None, info: dict, config: AutoHealConfig
    ) -> None:
        """
        Reset a container's restart backoff once it has stayed healthy for long enough

        A restarted container is briefly running and healthy even if it is crash-looping, so
        a healthy evaluation alone is not a recovery. The container must have been running
        and healthy, without a failed evaluation in between, for at least the delay it would
        wait before its next restart.

        Args:
            recovery_id: Recovery identifier the backoff is recorded under
            container_id: Docker ID of the container the healthy run belongs to
            info: Container information dict
            config: Current configuration
        """
        if info.get("state", {}).get("Status", "").lower() != "running":
            self._healthy_since.pop(recovery_id, None)
            return
        now = datetime.now(UTC)
        owner, healthy_since = self._healthy_since.get(recovery_id, (None, now))
        if owner != container_id:
            healthy_since = now
        self._healthy_since[recovery_id] = (container_id, healthy_since)
        delay = self._backoff_delays.get(recovery_id)
        if delay is None or (now - healthy_since).total_seconds() < delay:
            return
        self._backoff_delays[recovery_id] = config.restart.backoff.initial_seconds
        self._healthy_since.pop(recovery_id, None)

    async def _check_quarantined_container(
        self, container: Container, info: dict, quarantine_id: str, recovery_id: str
    ) -> bool:
        """
        Release a quarantined container once it has stayed healthy; True if released.

        A crash-looping container is running for part of every cycle, so a single
        healthy snapshot is not recovery (see ``_quarantine_recovery_confirmed``).

        Args:
            container: Container object
            info: Container information dict
            quarantine_id: The ID used in the quarantine list
            recovery_id: Recovery identifier for the container

        Returns:
            True if the container was removed from quarantine
        """
        container_id = info["full_id"]
        if info.get("state", {}).get("Status", "").lower() == "running":
            needs_restart, _ = await self._evaluate_container_health(container, info)
            if not needs_restart and self._quarantine_recovery_confirmed(container_id, info):
                await self._auto_unquarantine_container(
                    quarantine_id, recovery_id, info["name"], container_id
                )
                return True
        return False

    def _quarantine_recovery_confirmed(self, container_id: str, info: dict) -> bool:
        """
        Record one healthy check of a quarantined container; True once it is stable.

        Stable means ``QUARANTINE_STABLE_CHECKS`` consecutive healthy checks of the same
        run (same ``StartedAt``), each in the cycle after the previous one, and an uptime
        of that many monitoring intervals. Only a healthy check is recorded, so anything
        else (unhealthy, not running, skipped, failed, or a failed cycle) leaves a gap,
        and the sweep at the start of the next cycle ends the streak. The loop sleeps
        ``interval_seconds`` between checks, so real checks are at least that far apart
        and the uptime floor is a lower bound. Docker health ``starting`` is not healthy
        for this purpose in the health-based modes.

        Args:
            container_id: Full Docker container ID
            info: Container information dict, known to be running and not needing restart

        Returns:
            True if the container may be released from quarantine
        """
        config = config_manager.get_config()
        health = info.get("health")
        if (
            config.restart.mode in ("health", "both")
            and health
            and health.get("status") == "starting"
        ):
            return False

        started_at = info.get("started_at") or info.get("state", {}).get("StartedAt") or ""
        uptime = self._uptime_seconds(started_at)
        if uptime is None:
            # Without a usable StartedAt the run cannot be identified or timed, so the
            # container stays quarantined and nothing counts towards a streak
            return False

        previous = self._quarantine_streaks.get(container_id)
        count = previous[1] + 1 if previous and previous[0] == started_at else 1
        self._quarantine_streaks[container_id] = (started_at, count, self._check_cycle)

        required_uptime = QUARANTINE_STABLE_CHECKS * config.monitor.interval_seconds
        return count >= QUARANTINE_STABLE_CHECKS and uptime >= required_uptime

    @staticmethod
    def _uptime_seconds(started_at: str) -> float | None:
        """Seconds since a Docker ``StartedAt`` timestamp, or None if it is unusable"""
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if started.year <= 1:  # Docker's zero time: never started
            return None
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return (datetime.now(UTC) - started).total_seconds()

    def _clear_restart_waits_owned_by(self, container_id: str | None) -> None:
        """Forget every restart wait that the given container (by Docker ID) started"""
        owned = [
            recovery_id
            for recovery_id, owner in self._restart_wait_owner.items()
            if owner == container_id
        ]
        for recovery_id in owned:
            self._clear_restart_wait(recovery_id)

    def _clear_healthy_runs_owned_by(self, container_id: str | None) -> None:
        """Forget the healthy run the given container (by Docker ID) has built up"""
        owned = [
            recovery_id
            for recovery_id, (owner, _) in self._healthy_since.items()
            if owner == container_id
        ]
        for recovery_id in owned:
            del self._healthy_since[recovery_id]

    def _clear_healthy_runs_not_in(self, listed_ids: set[str | None]) -> None:
        """Forget the healthy runs of containers that Docker no longer lists"""
        gone = [
            recovery_id
            for recovery_id, (owner, _) in self._healthy_since.items()
            if owner not in listed_ids
        ]
        for recovery_id in gone:
            del self._healthy_since[recovery_id]

    def _clear_restart_wait(self, recovery_id: str) -> None:
        """Forget the restart wait recorded for a recovery ID, and who it belongs to"""
        self._next_allowed_restart.pop(recovery_id, None)
        self._restart_wait_owner.pop(recovery_id, None)
        self._restart_wait_seen.pop(recovery_id, None)

    def should_monitor_container(self, container: Container, info: dict) -> bool:
        """
        Determine if container should be monitored for auto-healing
        Args:
            container: Container object
            info: Container information dict
        Returns:
            True if container should be monitored, False otherwise
        """
        del container  # Selection depends on ``info`` only; kept for the callers' signature.
        return should_monitor(config_manager.get_config(), info, self.get_stable_identifier(info))

    async def _evaluate_container_health(
        self, container: Container, info: dict
    ) -> tuple[bool, str]:
        """
        Evaluate if container needs restart based on health checks
        Args:
            container: Container object
            info: Container information dict
        Returns:
            Tuple of (needs_restart: bool, reason: str)
        """
        return await self._health_evaluator.evaluate(
            container, info, self.get_stable_identifier(info)
        )

    async def _perform_custom_health_check(
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
        return await self._health_evaluator.perform_custom_health_check(container, health_check)

    async def _auto_unquarantine_container(
        self,
        quarantine_id: str,
        recovery_id: str,
        container_name: str,
        container_id: str,
    ) -> None:
        """
        Automatically remove a container from quarantine because it has auto-healed
        Args:
            quarantine_id: The ID used in the quarantine list
            recovery_id: Recovery identifier for the container
            container_name: Container name
            container_id: Container ID
        """
        try:
            # Remove from quarantine
            config_manager.unquarantine_container(quarantine_id)

            # Also clear the restart count so it starts fresh
            config_manager.clear_restart_history(recovery_id)
            self._quarantine_streaks.pop(container_id, None)

            # Reset backoff delays; a wait started by another replica sharing this
            # recovery ID is still valid
            if self._restart_wait_owner.get(recovery_id) == container_id:
                self._clear_restart_wait(recovery_id)
            if recovery_id in self._backoff_delays:
                config = config_manager.get_config()
                self._backoff_delays[recovery_id] = config.restart.backoff.initial_seconds

            # Log the event
            event = AutoHealEvent(
                timestamp=datetime.now(UTC),
                container_name=f"{container_name} ({recovery_id})",
                container_id=container_id,
                event_type="auto_unquarantine",
                restart_count=0,
                status="success",
                message="Container automatically removed from quarantine - auto-healed and now healthy",
            )
            config_manager.add_event(event)

            # Send notification
            await notification_manager.send_event_notification(event)

            logger.info(
                "Container %s (recovery_id: %s) automatically removed from quarantine - container auto-healed",
                container_name,
                recovery_id,
            )

        except Exception as e:
            logger.error("Error auto-unquarantining container %s: %s", container_name, e)

    async def _handle_container_restart(
        self, container: Container, info: dict, reason: str
    ) -> None:
        """
        Handle container restart with cooldown, backoff, and threshold logic
        Args:
            container: Container object
            info: Container information dict
            reason: Reason for restart
        """
        config = config_manager.get_config()
        container_id = info.get("full_id")
        container_name = info.get("name")

        # Get recovery identifier: the stable identifier (handles auto-generated names,
        # compose services, explicit IDs), made per replica for scaled Compose services
        identifiers = self._container_identifiers(info)
        if identifiers is None:
            logger.warning(
                "Not restarting container with incomplete identifiers: %s",
                container_name or container_id,
            )
            return
        container_id, container_name, recovery_id = identifiers

        # Use STABLE IDENTIFIER as primary (persists across container recreations)
        # This solves:
        # 1. Container ID bug (IDs change after image updates)
        # 2. Auto-generated names (uses compose service name)
        # 3. Name conflicts (uses compose project + service)

        logger.debug("Using recovery_id '%s' for container %s", recovery_id, container_name)

        # Check cooldown (using recovery_id)
        last_restart = self._last_restart_times.get(recovery_id)
        if last_restart:
            elapsed = (datetime.now(UTC) - last_restart).total_seconds()
            if elapsed < config.restart.cooldown_seconds:
                logger.debug(
                    "Container %s (recovery_id: %s) in cooldown period (%.1fs)",
                    container_name,
                    recovery_id,
                    elapsed,
                )
                return

        # Check restart threshold (using recovery_id for persistence)
        restart_count = config_manager.get_restart_count(
            recovery_id, config.restart.max_restarts_window_seconds
        )

        if restart_count >= config.restart.max_restarts:
            # Quarantine container (by recovery_id)
            config_manager.quarantine_container(recovery_id)

            event = AutoHealEvent(
                timestamp=datetime.now(UTC),
                container_name=f"{container_name} ({recovery_id})",
                container_id=container_id,  # Store current ID for reference
                event_type="quarantine",
                restart_count=restart_count,
                status="quarantined",
                message=f"Container quarantined: exceeded {config.restart.max_restarts} restarts "
                f"in {config.restart.max_restarts_window_seconds}s window",
            )
            config_manager.add_event(event)

            # Send notification for quarantine event
            await notification_manager.send_event_notification(event)

            logger.warning(
                "Container %s (recovery_id: %s) quarantined after %s restarts",
                container_name,
                recovery_id,
                restart_count,
            )

            # Send alert if configured
            if config.alerts.enabled and config.alerts.notify_on_quarantine:
                await self._send_alert(event)

            return

        # Apply backoff if enabled (using recovery_id)
        if config.restart.backoff.enabled and not self._restart_wait_elapsed(
            recovery_id, container_id, container_name, config
        ):
            return

        # The restart goes ahead now, so no wait is pending (backoff may also have been
        # disabled while one was)
        self._clear_restart_wait(recovery_id)

        # Perform restart
        logger.info(
            "Restarting container %s (recovery_id: %s, reason: %s)",
            container_name,
            recovery_id,
            reason,
        )
        success = await asyncio.to_thread(self.docker_client.restart_container, container)

        # Record restart (using recovery_id - persists across ID changes and handles all edge cases)
        config_manager.record_restart(recovery_id, config.restart.max_restarts_window_seconds)
        self._last_restart_times[recovery_id] = datetime.now(UTC)

        # Log event
        event = AutoHealEvent(
            timestamp=datetime.now(UTC),
            container_name=f"{container_name} ({recovery_id})",
            container_id=container_id,
            event_type="restart",
            restart_count=config_manager.get_total_restart_count(recovery_id),
            status="success" if success else "failure",
            message=f"Restart {'successful' if success else 'failed'}: {reason}",
        )
        config_manager.add_event(event)

        # Send notification for restart event
        await notification_manager.send_event_notification(event)

        if success:
            logger.info(
                "Successfully restarted container %s (recovery_id: %s)",
                container_name,
                recovery_id,
            )
        else:
            logger.error(
                "Failed to restart container %s (recovery_id: %s)",
                container_name,
                recovery_id,
            )

    def _restart_wait_elapsed(
        self,
        recovery_id: str,
        container_id: str | None,
        container_name: str | None,
        config: AutoHealConfig,
    ) -> bool:
        """
        Apply the restart backoff for a container that needs restarting

        The wait is recorded as a timestamp and checked on later cycles, never slept
        inline, so one container's backoff cannot stall the monitoring of the others.

        Args:
            recovery_id: Recovery identifier the wait is recorded under
            container_id: Docker ID of the container, recorded as the owner of a new wait
            container_name: Container name, for logging
            config: Current configuration

        Returns:
            True if the restart may go ahead now. False if a wait was just scheduled
            or the existing one has not run out yet.
        """
        now = datetime.now(UTC)
        next_allowed = self._next_allowed_restart.get(recovery_id)
        if next_allowed is not None:
            if self._restart_wait_seen.get(recovery_id, self._check_cycle) < self._check_cycle - 1:
                logger.debug(
                    "Restart wait for %s (recovery_id: %s) was not confirmed last cycle, "
                    "starting a new one",
                    container_name,
                    recovery_id,
                )
                self._clear_restart_wait(recovery_id)
                next_allowed = None
            elif self._restart_wait_owner.get(recovery_id) == container_id:
                self._restart_wait_seen[recovery_id] = self._check_cycle
        backoff_delay = min(
            self._backoff_delays.get(recovery_id, config.restart.backoff.initial_seconds),
            config.restart.backoff.max_seconds,
        )
        if next_allowed is None:
            logger.debug(
                "Applying backoff delay of %ss for %s (recovery_id: %s)",
                backoff_delay,
                container_name,
                recovery_id,
            )
            self._next_allowed_restart[recovery_id] = now + timedelta(seconds=backoff_delay)
            self._restart_wait_owner[recovery_id] = container_id
            self._restart_wait_seen[recovery_id] = self._check_cycle
            return False
        if now < next_allowed:
            logger.debug(
                "Container %s (recovery_id: %s) waiting out restart backoff (%.1fs left)",
                container_name,
                recovery_id,
                (next_allowed - now).total_seconds(),
            )
            return False

        # Update backoff for next time
        next_backoff = min(
            int(backoff_delay * config.restart.backoff.multiplier),
            config.restart.backoff.max_seconds,
        )
        self._backoff_delays[recovery_id] = next_backoff
        return True

    async def _send_alert(self, event: AutoHealEvent) -> None:
        """
        Send alert via webhook
        Args:
            event: Auto-heal event to send
        """
        config = config_manager.get_config()
        webhook_url = config.alerts.webhook

        if not webhook_url:
            return

        try:
            import requests

            payload = {
                "timestamp": event.timestamp.isoformat(),
                "container_id": event.container_id,
                "container_name": event.container_name,
                "event_type": event.event_type,
                "restart_count": event.restart_count,
                "status": event.status,
                "message": event.message,
            }

            response = await asyncio.to_thread(requests.post, webhook_url, json=payload, timeout=5)

            if response.status_code == HTTPStatus.OK:
                logger.info("Alert sent successfully for %s", event.container_name)
            else:
                logger.warning("Alert webhook returned status %s", response.status_code)

        except Exception as e:
            logger.error("Failed to send alert: %s", e)

    def get_status(self) -> dict:
        """Get monitoring engine status"""
        return {
            "running": self._running,
            "monitored_containers": len(self._last_restart_times),
            "quarantined_containers": len(config_manager.get_quarantined_containers()),
        }

    async def _event_listener_loop(self, since: int | None = None) -> None:
        """Listen for Docker container start events (see ``AutoDiscovery.listen``)"""
        await self._auto_discovery.listen(
            since,
            is_running=lambda: self._running,
            handle_event=self._process_container_start_event,
        )

    async def _scan_existing_containers(self) -> None:
        """Scan running containers for the monitoring label (see ``AutoDiscovery``)"""
        await self._auto_discovery.scan_existing_containers()

    async def _process_container_start_event(self, event: dict) -> None:
        """Handle one Docker container start event (see ``AutoDiscovery``)"""
        await self._auto_discovery.process_start_event(event)
