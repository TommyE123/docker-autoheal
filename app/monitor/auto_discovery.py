"""
Container auto-discovery for Docker Auto-Heal Service
Adds containers that carry the configured monitoring label to the monitored list, from a
scan of the running containers and from Docker container start events
"""

import asyncio
import logging
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.config.config_manager import AutoHealEvent, config_manager
from app.notifications.notification_manager import notification_manager

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.monitor.monitoring_engine import DockerClient

logger = logging.getLogger(__name__)

# Pause before reconnecting to the Docker event stream, after any kind of stream end.
EVENT_RECONNECT_DELAY_SECONDS = 10

# How long stop waits for the event reader thread to exit after closing its stream.
EVENT_THREAD_JOIN_TIMEOUT_SECONDS = 5


class _DockerEventReader:
    """
    Reads Docker's blocking event stream on a thread and publishes events to an asyncio queue.

    ``None`` is published when the thread exits, so the consumer never waits on a dead reader.
    """

    def __init__(
        self,
        docker_client: DockerClient,
        loop: asyncio.AbstractEventLoop,
        event_queue: asyncio.Queue[dict | None],
        since: int,
    ) -> None:
        self._docker_client = docker_client
        self._loop = loop
        self._queue = event_queue
        self._last_event_time = since
        self.stop = threading.Event()
        # The open stream, so a stop can close it and unblock the thread
        self.stream: Any = None

    def _publish(self, item: dict | None) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)
        except RuntimeError:
            # The event loop is closed, so there is nobody left to read
            self.stop.set()

    def run(self) -> None:
        """Thread function to read events from Docker (blocking)"""
        try:
            while not self.stop.is_set():
                try:
                    self._read_stream()
                except Exception as e:
                    # Closing the stream to stop makes its iterator fail; that is not an error
                    if not self.stop.is_set():
                        logger.exception("Error in event listener thread: %s", e)
                finally:
                    self.stream = None
                # Back off after every stream end, however it ended, without delaying a stop
                self.stop.wait(EVENT_RECONNECT_DELAY_SECONDS)
        finally:
            self._publish(None)

    def _read_stream(self) -> None:
        logger.debug("Starting Docker event listener thread...")
        events = self._docker_client.get_events(
            decode=True,
            filters={"type": "container", "event": "start"},
            since=self._last_event_time,
        )
        if not events:
            logger.warning(
                "Failed to get event stream, retrying in %s seconds...",
                EVENT_RECONNECT_DELAY_SECONDS,
            )
            return
        self.stream = events
        # stop is set before the consumer reads ``stream``, so either it closes this
        # stream or this check sees the stop
        if self.stop.is_set():
            return
        for event in events:
            if self.stop.is_set():
                return
            event_time = event.get("time")
            if isinstance(event_time, int):
                self._last_event_time = max(self._last_event_time, event_time)
            self._publish(event)
        if not self.stop.is_set():
            logger.warning(
                "Docker event stream ended, reconnecting in %s seconds...",
                EVENT_RECONNECT_DELAY_SECONDS,
            )


class AutoDiscovery:
    """Finds containers carrying the monitoring label and adds them to monitoring"""

    def __init__(
        self,
        docker_client: DockerClient,
        container_identifiers: Callable[[dict], tuple[str, str, str] | None],
    ) -> None:
        """
        Initialize auto-discovery
        Args:
            docker_client: Docker client wrapper instance
            container_identifiers: Returns (container_id, container_name, recovery_id) for a
                container info dict, or None if any is missing; the scan skips those
        """
        self._docker_client = docker_client
        self._container_identifiers = container_identifiers

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

    @staticmethod
    def _select_labelled_container(
        *,
        stable_id: str,
        container_id: str,
        container_name: str,
        label: str,
    ) -> bool:
        """
        Add a container carrying the autoheal label to the monitored list.

        Skips containers that are already selected or explicitly excluded. The check
        and the append run against the live configuration in one ``mutate()`` block,
        so a change made while the caller was awaiting Docker is neither overwritten
        nor ignored. The selection is saved before this returns.

        Args:
            stable_id: Stable identifier to store in the selected list
            container_id: Container ID used for the checks
            container_name: Container name used for the checks
            label: Configured monitoring label as ``key=value``, used in log text

        Returns:
            True if the container was added, False if it was skipped
        """
        with config_manager.mutate() as config:
            selected = config.containers.selected
            excluded = config.containers.excluded
            # Match by stable_id, name, or ID for backwards compatibility
            if stable_id in selected or container_name in selected or container_id in selected:
                logger.debug(
                    "Container %s (stable_id: %s) already in monitored list",
                    container_name,
                    stable_id,
                )
                return False

            if stable_id in excluded or container_name in excluded or container_id in excluded:
                logger.info(
                    "Container %s (stable_id: %s) has %s but is in excluded list, skipping",
                    container_name,
                    stable_id,
                    label,
                )
                return False

            # Add to monitored list using STABLE ID
            selected.append(stable_id)
        return True

    @staticmethod
    def _record_auto_monitor_event(
        *,
        stable_id: str,
        container_id: str,
        container_name: str,
        startup: bool,
        label: str,
    ) -> AutoHealEvent:
        """
        Log and record the ``auto_monitor`` event for a container that was just selected.

        Runs after ``_select_labelled_container`` has saved the selection, so a failure
        here cannot lose it. The caller sends the notification afterwards.

        Args:
            stable_id: Stable identifier the container was selected under
            container_id: Container ID recorded on the event
            container_name: Container name used for the event label
            startup: True when called from the startup scan, which words the log and
                event for startup
            label: Configured monitoring label as ``key=value``, used in log and event text

        Returns:
            The recorded event
        """
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
            message=f"Automatically added to monitoring{' on startup' if startup else ''} due to {label} label (stable_id: {stable_id})",
        )
        config_manager.add_event(event)
        return event

    async def listen(
        self,
        since: int | None,
        *,
        is_running: Callable[[], bool],
        handle_event: Callable[[dict], Awaitable[None]],
    ) -> None:
        """
        Listen for Docker events and auto-add containers with the configured monitoring label
        (autoheal=true by default)

        A reader thread owns the blocking Docker stream and hands events to this coroutine
        through an ``asyncio.Queue``, so the event loop never blocks. The thread reconnects
        after every stream end, resuming from the last event it saw so that containers
        started during the gap are not missed. Each run has its own stop signal, so a thread
        from one run can never be revived by the next run's ``_running`` flag.

        Args:
            since: Unix time to replay events from on the first connect. Defaults to now;
                ``start()`` passes a time taken before the startup scan.
            is_running: Whether the engine is running; the loop ends once it is false
            handle_event: Coroutine function that processes one start event
        """
        event_queue: asyncio.Queue[dict | None] = asyncio.Queue()
        reader = _DockerEventReader(
            self._docker_client,
            asyncio.get_running_loop(),
            event_queue,
            int(time.time()) if since is None else since,
        )
        thread = threading.Thread(target=reader.run, daemon=True, name="docker-events")
        thread.start()
        logger.debug("Docker event listener thread started")

        try:
            while is_running():
                event = await event_queue.get()
                if event is None:
                    logger.error("Docker event reader thread exited unexpectedly")
                    break
                try:
                    await handle_event(event)
                except Exception as e:
                    logger.exception("Error processing event from queue: %s", e)
        except asyncio.CancelledError:
            logger.debug("Event listener cancelled")
        finally:
            reader.stop.set()
            await self._stop_event_reader(thread, reader.stream)

    async def _stop_event_reader(self, thread: threading.Thread, stream: Any) -> None:
        """Close the blocked event stream and wait for the reader thread to exit."""
        if stream is not None:
            try:
                stream.close()
            except Exception as e:  # DockerException for ssh://, or the stream already gone
                logger.debug("Error closing Docker event stream: %s", e)
        await asyncio.to_thread(thread.join, EVENT_THREAD_JOIN_TIMEOUT_SECONDS)
        if thread.is_alive():
            logger.warning(
                "Docker event reader thread still running %s seconds after stop",
                EVENT_THREAD_JOIN_TIMEOUT_SECONDS,
            )

    async def scan_existing_containers(self) -> None:
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
            if not self._docker_client.is_connected():
                logger.warning("Docker connection not available for initial scan")
                return

            # Get all running containers
            containers = await asyncio.to_thread(
                self._docker_client.list_containers, all_containers=False
            )

            added_count = 0

            for container in containers:
                try:
                    # Get container info including labels
                    info = await asyncio.to_thread(
                        self._docker_client.get_container_info, container
                    )

                    identifiers = self._container_identifiers(info)
                    if identifiers is None:
                        continue
                    container_id, container_name, _recovery_id = identifiers

                    labels = info.get("labels", {})

                    # Check if container has the configured monitoring label (autoheal=true by default)
                    if labels.get(config.monitor.label_key) != config.monitor.label_value:
                        continue

                    stable_id = self._auto_monitor_stable_id(labels, container_name)
                    # Saved here, before the event is recorded, so a failure in the
                    # event or notification below cannot lose the selection.
                    if not self._select_labelled_container(
                        stable_id=stable_id,
                        container_id=container_id,
                        container_name=container_name,
                        label=label,
                    ):
                        continue
                    added_count += 1

                    event_obj = self._record_auto_monitor_event(
                        stable_id=stable_id,
                        container_id=container_id,
                        container_name=container_name,
                        startup=True,
                        label=label,
                    )
                    await notification_manager.send_event_notification(event_obj)

                except Exception as e:
                    logger.exception("Error processing container during initial scan: %s", e)
                    continue

            if added_count > 0:
                logger.info(
                    "Initial scan complete: %s container(s) auto-added to monitoring",
                    added_count,
                )
            else:
                logger.info("Initial scan complete: no new containers to add")

        except Exception as e:
            logger.exception("Error during initial container scan: %s", e)

    async def process_start_event(self, event: dict) -> None:
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
                "Container start event detected: %s (%s)",
                container_name,
                container_id[:12],
            )

            # Get the container object
            container = await asyncio.to_thread(self._docker_client.get_container, container_id)

            if not container:
                logger.warning("Could not retrieve container %s after start event", container_name)
                return

            # Get container info including labels
            info = await asyncio.to_thread(self._docker_client.get_container_info, container)

            labels = info.get("labels", {})

            # Check if container has the configured monitoring label (autoheal=true by default)
            config = config_manager.get_config()
            if labels.get(config.monitor.label_key) != config.monitor.label_value:
                return

            # The event's own ID and name label the container here, as before
            stable_id = self._auto_monitor_stable_id(labels, container_name)
            label = f"{config.monitor.label_key}={config.monitor.label_value}"
            # Saved here, before the event is recorded, so a failure in the event or
            # notification below cannot lose the selection.
            if not self._select_labelled_container(
                stable_id=stable_id,
                container_id=container_id,
                container_name=container_name,
                label=label,
            ):
                return

            event_obj = self._record_auto_monitor_event(
                stable_id=stable_id,
                container_id=container_id,
                container_name=container_name,
                startup=False,
                label=label,
            )
            await notification_manager.send_event_notification(event_obj)

        except Exception as e:
            logger.exception("Error processing container start event: %s", e)
