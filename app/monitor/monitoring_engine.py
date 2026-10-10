"""
Core monitoring engine for Docker Auto-Heal Service
Monitors containers and performs auto-healing actions
"""

import asyncio
import fnmatch
import logging
from datetime import UTC, datetime

from docker.models.containers import Container

from app.config.config_manager import (
    AutoHealConfig,
    AutoHealEvent,
    HealthCheckConfig,
    config_manager,
)
from app.docker_client.docker_client_wrapper import DockerClientWrapper, recovery_identifier
from app.notifications.notification_manager import notification_manager

logger = logging.getLogger(__name__)


class MonitoringEngine:
    """
    Core monitoring engine that checks container health and performs restarts
    """

    def __init__(self, docker_client: DockerClientWrapper):
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

    def get_stable_identifier(self, info: dict) -> str:
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
            Stable identifier string

        Note:
            An empty ``monitoring.id`` label is returned as-is. Container
            discovery must not use this method for that reason; it uses
            ``_auto_monitor_stable_id``, which ignores an empty label.
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

    def get_recovery_identifier(self, info: dict) -> str:
        """
        Get the key for a container's restart count, cooldown, backoff and quarantine.

        Every Compose container is keyed by its project, service and container
        number (see ``recovery_identifier``), so replicas of a scaled service recover
        independently, including ``#1`` for an unscaled service. Configuration (selection, health
        checks, Uptime Kuma mappings) stays keyed by ``get_stable_identifier``.

        Args:
            info: Container information dict

        Returns:
            Recovery identifier string
        """
        return recovery_identifier(self.get_stable_identifier(info), info.get("labels", {}))

    @staticmethod
    def _auto_monitor_stable_id(labels: dict, container_name: str) -> str:
        """
        Stable ID stored in the selected list when a container is auto-monitored.

        Unlike ``get_stable_identifier``, an empty ``monitoring.id`` label is
        ignored here, so it falls back to the Compose identity or the name rather
        than storing an empty key that every other empty-label container would match.

        Args:
            labels: Container labels
            container_name: Container name

        Returns:
            Stable identifier string
        """
        if labels.get("monitoring.id"):
            return labels["monitoring.id"]

        compose_project = labels.get("com.docker.compose.project")
        compose_service = labels.get("com.docker.compose.service")
        if compose_project and compose_service:
            return f"{compose_project}_{compose_service}"

        return container_name

    async def start(self) -> None:
        """Start the monitoring engine"""
        if self._running:
            logger.warning("Monitoring engine already running")
            return

        self._running = True

        # Proactively scan for existing containers with the configured monitoring label
        await self._scan_existing_containers()

        self._task = asyncio.create_task(self._monitor_loop())
        self._event_task = asyncio.create_task(self._event_listener_loop())
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
        """Check all containers and perform auto-healing if needed"""
        try:
            # Ensure Docker connection is active
            if not self.docker_client.is_connected():
                logger.warning("Docker connection lost, attempting reconnect...")
                if not self.docker_client.reconnect():
                    logger.error("Failed to reconnect to Docker")
                    return

            # Get ALL containers (including stopped) to detect failures
            containers = await asyncio.to_thread(self.docker_client.list_containers, all_containers=True)

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

        # Get stable identifier (handles auto-generated names, compose services, explicit IDs)
        stable_id = self.get_stable_identifier(info)

        # Check if container should be monitored
        if not self.should_monitor_container(container, info):
            return

        # Check if container is quarantined (by recovery ID, name, or ID for backwards compatibility)
        recovery_id = self.get_recovery_identifier(info)
        quarantine_id = None
        if config_manager.is_quarantined(recovery_id):
            quarantine_id = recovery_id
        elif config_manager.is_quarantined(container_name):
            quarantine_id = container_name
        elif config_manager.is_quarantined(container_id):
            quarantine_id = container_id

        if quarantine_id:
            # Container is quarantined - check if it has auto-healed using existing health evaluation
            # First check: container must be running
            state = info.get("state", {})
            status = state.get("Status", "").lower()

            if status == "running":
                # Reuse existing health evaluation - if needs_restart is False, container is healthy
                needs_restart, reason = await self._evaluate_container_health(container, info)
                if not needs_restart:
                    # Container is healthy, auto-remove from quarantine
                    await self._auto_unquarantine_container(
                        quarantine_id, recovery_id, container_name, container_id
                    )
                    return

            logger.debug(
                "Container %s (stable_id: %s) is quarantined and still unhealthy, skipping",
                container_name,
                stable_id,
            )
            return


        # Check if container needs healing
        needs_restart, reason = await self._evaluate_container_health(container, info)

        if needs_restart:
            await self._handle_container_restart(container, info, reason)

    def should_monitor_container(self, container: Container, info: dict) -> bool:
        """
        Determine if container should be monitored for auto-healing
        Args:
            container: Container object
            info: Container information dict
        Returns:
            True if container should be monitored, False otherwise
        """
        config = config_manager.get_config()
        container_id = info.get("full_id")
        short_id = info.get("id")  # Short ID (first 12 chars)
        container_name = info.get("name")
        labels = info.get("labels", {})

        # Get stable identifier (handles all edge cases)
        stable_id = self.get_stable_identifier(info)
        compose_service = labels.get("com.docker.compose.service")

        # Check explicit exclusion (check stable_id, compose service, name, and IDs)
        if (stable_id in config.containers.excluded or
            container_id in config.containers.excluded or
            short_id in config.containers.excluded or
            container_name in config.containers.excluded or
            (compose_service and compose_service in config.containers.excluded)):
            return False

        # Check explicit inclusion (check stable_id, compose service, name, and IDs)
        if (stable_id in config.containers.selected or
            container_id in config.containers.selected or
            short_id in config.containers.selected or
            container_name in config.containers.selected or
            (compose_service and compose_service in config.containers.selected)):
            logger.debug(
                "Container %s (stable_id: %s) explicitly selected for monitoring",
                container_name,
                stable_id,
            )
            return True

        # Check include_all flag
        if config.monitor.include_all:
            pass  # Continue to filter checks
        else:
            # Check label filter
            label_key = config.monitor.label_key
            label_value = config.monitor.label_value

            if label_key not in labels or labels[label_key] != label_value:
                return False

        # Check blacklist names
        for pattern in config.filters.blacklist_names:
            if fnmatch.fnmatch(container_name, pattern):
                return False

        # Check whitelist names (if specified, must match at least one)
        if config.filters.whitelist_names:
            matched = False
            for pattern in config.filters.whitelist_names:
                if fnmatch.fnmatch(container_name, pattern):
                    matched = True
                    break
            if not matched:
                return False

        # Check blacklist labels
        for label_filter in config.filters.blacklist_labels:
            for key, value in label_filter.items():
                if labels.get(key) == value:
                    return False

        # Check whitelist labels (if specified, must match at least one)
        if config.filters.whitelist_labels:
            matched = False
            for label_filter in config.filters.whitelist_labels:
                for key, value in label_filter.items():
                    if labels.get(key) == value:
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                return False

        return True

    async def _evaluate_container_health(self, container: Container, info: dict) -> tuple[bool, str]:
        """
        Evaluate if container needs restart based on health checks
        Args:
            container: Container object
            info: Container information dict
        Returns:
            Tuple of (needs_restart: bool, reason: str)
        """
        config = config_manager.get_config()
        restart_mode = config.restart.mode
        container_id = info.get("full_id")

        # Get stable identifier for all checks
        stable_id = self.get_stable_identifier(info)


        # Check exit status (for exited/stopped containers)
        state = info.get("state", {})
        status = state.get("Status", "").lower()

        if status == "starting":
            logger.debug(
                "Container %s is still starting, skipping health evaluation", info.get("name")
            )
            return False, "Container is starting"

        if status in ["exited", "stopped", "dead"]:
            exit_code = state.get("ExitCode", 0)

            # Check if we should restart based on mode
            if restart_mode in ["on-failure", "both"]:
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
                return True, f"Container stopped (exit 0)"

        # Check health status
        if restart_mode in ["health", "both"]:
            # Get stable identifier for health check lookup
            container_name = info.get("name")

            # Check custom health checks (by stable_id, name, then ID for backwards compatibility)
            custom_hc = config_manager.get_custom_health_check(stable_id)
            if not custom_hc:
                custom_hc = config_manager.get_custom_health_check(container_name)
            if not custom_hc:
                custom_hc = config_manager.get_custom_health_check(container_id)
            if custom_hc:
                health_ok = await self._perform_custom_health_check(container, custom_hc)
                if not health_ok:
                    return True, f"Custom health check failed ({custom_hc.check_type})"

            # Then check Docker native health
            health = info.get("health")
            if health:
                status = health.get("status")
                if status == "unhealthy":
                    return True, "Docker health check reports unhealthy"

        # Check Uptime-Kuma monitor status (if configured and enabled)
        if hasattr(self, 'uptime_kuma_monitor') and self.uptime_kuma_monitor:
            if await self.uptime_kuma_monitor.should_restart_from_uptime_kuma(stable_id):
                return True, "Uptime-Kuma monitor reports DOWN"

        return False, ""

    async def _perform_custom_health_check(self, container: Container,
                                          health_check: HealthCheckConfig) -> bool:
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
                return await asyncio.to_thread(
                    self.docker_client.check_http_health,
                    container,
                    health_check.http_endpoint,
                    health_check.http_expected_status,
                    health_check.timeout_seconds
                )
            if check_type == "tcp":
                return await asyncio.to_thread(
                    self.docker_client.check_tcp_health,
                    container,
                    health_check.tcp_port,
                    health_check.timeout_seconds
                )
            if check_type == "exec":
                return await asyncio.to_thread(
                    self.docker_client.check_exec_health,
                    container,
                    health_check.exec_command
                )
            if check_type == "docker":
                status = await asyncio.to_thread(
                    self.docker_client.get_docker_native_health,
                    container
                )
                return status == "healthy" if status else True  # Assume healthy if no check
            logger.warning("Unknown health check type: %s", check_type)
            return True
        except Exception as e:
            logger.error("Error performing health check: %s", e)
            return False

    async def _auto_unquarantine_container(self, quarantine_id: str, recovery_id: str,
                                            container_name: str, container_id: str) -> None:
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

            # Reset backoff delays
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
                message="Container automatically removed from quarantine - auto-healed and now healthy"
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

    async def _handle_container_restart(self, container: Container, info: dict, reason: str) -> None:
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
        recovery_id = self.get_recovery_identifier(info)
        labels = info.get("labels", {})

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
            recovery_id,
            config.restart.max_restarts_window_seconds
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
                       f"in {config.restart.max_restarts_window_seconds}s window"
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
        if config.restart.backoff.enabled:
            backoff_delay = self._backoff_delays.get(
                recovery_id, config.restart.backoff.initial_seconds
            )
            logger.debug(
                "Applying backoff delay of %ss for %s (recovery_id: %s)",
                backoff_delay,
                container_name,
                recovery_id,
            )
            await asyncio.sleep(backoff_delay)

            # Update backoff for next time
            next_backoff = int(backoff_delay * config.restart.backoff.multiplier)
            self._backoff_delays[recovery_id] = next_backoff

        # Perform restart
        logger.info(
            "Restarting container %s (recovery_id: %s, reason: %s)",
            container_name,
            recovery_id,
            reason,
        )
        success = await asyncio.to_thread(self.docker_client.restart_container, container)

        # Record restart (using recovery_id - persists across ID changes and handles all edge cases)
        config_manager.record_restart(recovery_id)
        self._last_restart_times[recovery_id] = datetime.now(UTC)

        # Log event
        event = AutoHealEvent(
            timestamp=datetime.now(UTC),
            container_name=f"{container_name} ({recovery_id})",
            container_id=container_id,
            event_type="restart",
            restart_count=restart_count + 1,
            status="success" if success else "failure",
            message=f"Restart {'successful' if success else 'failed'}: {reason}"
        )
        config_manager.add_event(event)

        # Send notification for restart event
        await notification_manager.send_event_notification(event)

        if success:
            logger.info(
                "Successfully restarted container %s (recovery_id: %s)", container_name, recovery_id
            )
            # Reset backoff on successful restart
            self._backoff_delays[recovery_id] = config.restart.backoff.initial_seconds
        else:
            logger.error(
                "Failed to restart container %s (recovery_id: %s)", container_name, recovery_id
            )

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
                "message": event.message
            }

            response = await asyncio.to_thread(
                requests.post,
                webhook_url,
                json=payload,
                timeout=5
            )

            if response.status_code == 200:
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
            "quarantined_containers": len(config_manager.get_quarantined_containers())
        }

    @staticmethod
    def _auto_monitor_container(
        config: AutoHealConfig,
        *,
        stable_id: str,
        container_id: str,
        container_name: str,
        startup: bool,
        label: str,
    ) -> AutoHealEvent | None:
        """
        Add a container carrying the autoheal label to the monitored list.

        Skips containers that are already selected or explicitly excluded.
        Mutates ``config`` and records an ``auto_monitor`` event when added. The
        caller sends the notification afterwards, so a failing notification
        cannot lose the selection.

        Args:
            config: Configuration to update (a working copy from ``get_config()``)
            stable_id: Stable identifier to store in the selected list
            container_id: Container ID used for the checks and recorded on the event
            container_name: Container name used for the checks and the event label
            label: Configured monitoring label as ``key=value``, used in log and event text
            startup: True when called from the startup scan, which saves ``config``
                once at the end and words its log and event for startup. Otherwise
                ``config`` is saved right after the selection, before the event is
                recorded.

        Returns:
            The recorded event if the container was added, None if it was skipped
        """
        # Check if already in selected list (by stable_id, name, or ID for backwards compatibility)
        if (stable_id in config.containers.selected or
            container_name in config.containers.selected or
            container_id in config.containers.selected):
            logger.debug(
                "Container %s (stable_id: %s) already in monitored list",
                container_name,
                stable_id,
            )
            return None

        # Check if in excluded list
        if (stable_id in config.containers.excluded or
            container_name in config.containers.excluded or
            container_id in config.containers.excluded):
            logger.info(
                "Container %s (stable_id: %s) has %s but is in excluded list, skipping",
                container_name,
                stable_id,
                label,
            )
            return None

        # Add to monitored list using STABLE ID
        config.containers.selected.append(stable_id)
        if not startup:
            config_manager.update_config(config)

        logger.info(
            "Auto-monitoring enabled for container '%s' (%s) with stable_id '%s' - detected %s label%s",
            container_name,
            container_id[:12],
            stable_id,
            label,
            " on startup" if startup else "",
        )

        event = AutoHealEvent(
            timestamp=datetime.now(UTC),
            container_name=f"{container_name} ({stable_id})",
            container_id=container_id,  # Store current ID for reference
            event_type="auto_monitor",
            restart_count=0,
            status="enabled",
            message=f"Automatically added to monitoring{' on startup' if startup else ''} due to {label} label (stable_id: {stable_id})"
        )
        config_manager.add_event(event)
        return event

    async def _scan_existing_containers(self) -> None:
        """
        Proactively scan all existing containers on startup and auto-add those with the configured
        monitoring label (autoheal=true by default)
        This ensures containers that are already running when the service starts are added to config.json
        """
        try:
            config = config_manager.get_config()
            label = f"{config.monitor.label_key}={config.monitor.label_value}"
            logger.info("Scanning existing containers for %s label...", label)

            # Ensure Docker connection is active
            if not self.docker_client.is_connected():
                logger.warning("Docker connection not available for initial scan")
                return

            # Get all running containers
            containers = await asyncio.to_thread(self.docker_client.list_containers, all_containers=False)

            added_count = 0

            for container in containers:
                try:
                    # Get container info including labels
                    info = await asyncio.to_thread(
                        self.docker_client.get_container_info,
                        container
                    )

                    if not info:
                        continue

                    labels = info.get("labels", {})

                    # Check if container has the configured monitoring label (autoheal=true by default)
                    if labels.get(config.monitor.label_key) != config.monitor.label_value:
                        continue

                    selected_before = len(config.containers.selected)
                    try:
                        event_obj = self._auto_monitor_container(
                            config,
                            stable_id=self._auto_monitor_stable_id(labels, info.get("name")),
                            container_id=info.get("full_id"),
                            container_name=info.get("name"),
                            startup=True,
                            label=label,
                        )
                    finally:
                        # Count the selection as soon as it is made, so it is still saved
                        # if recording the event fails afterwards.
                        if len(config.containers.selected) > selected_before:
                            added_count += 1
                    if event_obj:
                        await notification_manager.send_event_notification(event_obj)

                except Exception as e:
                    logger.exception("Error processing container during initial scan: %s", e)
                    continue

            # Save configuration if any containers were added
            if added_count > 0:
                config_manager.update_config(config)
                logger.info(
                    "Initial scan complete: %s container(s) auto-added to monitoring", added_count
                )
            else:
                logger.info("Initial scan complete: no new containers to add")

        except Exception as e:
            logger.exception("Error during initial container scan: %s", e)

    async def _event_listener_loop(self) -> None:
        """
        Listen for Docker events and auto-add containers with the configured monitoring label
        (autoheal=true by default)
        """
        import queue
        import threading

        # Queue for events from the blocking thread
        event_queue = queue.Queue()

        def event_thread():
            """Thread function to read events from Docker (blocking)"""
            while self._running:
                try:
                    logger.debug("Starting Docker event listener thread...")

                    # Get event stream (blocking generator)
                    events = self.docker_client.get_events(
                        decode=True,
                        filters={"type": "container", "event": "start"}
                    )

                    if not events:
                        logger.warning("Failed to get event stream, retrying in 10 seconds...")
                        import time
                        time.sleep(10)
                        continue

                    # Read events and put them in queue
                    for event in events:
                        if not self._running:
                            break
                        event_queue.put(event)

                except Exception as e:
                    logger.exception("Error in event listener thread: %s", e)
                    import time
                    time.sleep(10)

        # Start the event thread
        thread = threading.Thread(target=event_thread, daemon=True, name="docker-events")
        thread.start()
        logger.debug("Docker event listener thread started")

        # Process events from queue in async loop
        while self._running:
            try:
                # Check queue with timeout to allow loop to continue
                try:
                    event = event_queue.get(timeout=1.0)
                    await self._process_container_start_event(event)
                except queue.Empty:
                    # No events, continue loop
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                logger.debug("Event listener cancelled")
                break
            except Exception as e:
                logger.exception("Error processing event from queue: %s", e)
                await asyncio.sleep(1)

    async def _process_container_start_event(self, event: dict) -> None:
        """
        Process a container start event and add to monitoring if it has the configured monitoring
        label (autoheal=true by default)
        Args:
            event: Docker event dictionary
        """
        try:
            # Extract container information from event. The Docker Events API
            # carries the container ID under Actor.ID, not a top-level "id" -
            # that field was reading as always-None against a real daemon.
            actor = event.get("Actor", {})
            container_id = actor.get("ID")
            attributes = actor.get("Attributes", {})
            container_name = attributes.get("name", "unknown")

            if not container_id:
                return

            logger.debug(
                "Container start event detected: %s (%s)", container_name, container_id[:12]
            )

            # Get the container object
            container = await asyncio.to_thread(
                self.docker_client.get_container,
                container_id
            )

            if not container:
                logger.warning("Could not retrieve container %s after start event", container_name)
                return

            # Get container info including labels
            info = await asyncio.to_thread(
                self.docker_client.get_container_info,
                container
            )

            labels = info.get("labels", {})

            # Check if container has the configured monitoring label (autoheal=true by default)
            config = config_manager.get_config()
            if labels.get(config.monitor.label_key) == config.monitor.label_value:
                event_obj = self._auto_monitor_container(
                    config,
                    # The event's own ID and name label the container here, as before
                    stable_id=self._auto_monitor_stable_id(labels, container_name),
                    container_id=container_id,
                    container_name=container_name,
                    startup=False,
                    label=f"{config.monitor.label_key}={config.monitor.label_value}",
                )
                if event_obj:
                    await notification_manager.send_event_notification(event_obj)

        except Exception as e:
            logger.exception("Error processing container start event: %s", e)

