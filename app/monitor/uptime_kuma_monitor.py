"""
Uptime-Kuma monitoring service that provides container health status from Uptime Kuma
This module only handles Uptime Kuma-specific operations (SOLID principles):
- Uptime Kuma API communication
- Monitor status retrieval
- Mapping configuration
- Providing health status to monitoring engine

Core functionality (restarts, quarantine, events, etc.) is delegated to MonitoringEngine
"""
import asyncio
import logging
from collections import Counter

from app.config.config_manager import config_manager
from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient

logger = logging.getLogger(__name__)


class UptimeKumaMonitor:
    """
    Uptime-Kuma integration service
    Provides container health status from Uptime Kuma monitors
    Does NOT perform core actions - only reports status to MonitoringEngine
    """

    def __init__(self):
        """Initialize Uptime-Kuma monitor"""
        self.client: UptimeKumaClient | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._monitor_cache: dict[str, dict] = {}  # Cache monitor IDs by friendly name
        self._container_status_cache: dict[str, int] = {}  # Cache of stable_id -> status
        # (stable_id, monitor name) mappings already warned about as ambiguous
        self._ambiguous_mappings: set[tuple[str, str]] = set()

    async def start(self):
        """Start Uptime-Kuma monitoring"""
        try:
            config = config_manager.get_config()

            if not config.uptime_kuma.enabled:
                logger.info("Uptime-Kuma integration is disabled - configure it via UI to enable")
                return

            if not config.uptime_kuma.server_url or not config.uptime_kuma.api_token:
                logger.info("Uptime-Kuma integration not configured yet - visit http://localhost:3131/config to set up")
                return

            self.client = UptimeKumaClient(
                config.uptime_kuma.server_url,
                config.uptime_kuma.api_token,  # password (API key or user password)
                config.uptime_kuma.username    # username (optional, empty for API key)
            )

            # Test connection
            logger.info("Testing connection to Uptime-Kuma at %s...", config.uptime_kuma.server_url)
            if not await self.client.connect():
                logger.warning("Cannot connect to Uptime-Kuma at %s", config.uptime_kuma.server_url)
                logger.info("Uptime-Kuma monitoring will remain disabled until connection is successful")
                return

            logger.info("Uptime-Kuma connection successful")

            # Build monitor cache
            await self._refresh_monitor_cache()

            # Start monitoring loop
            self._running = True
            self._task = asyncio.create_task(self._monitoring_loop())
        except Exception as e:
            logger.warning("Failed to start Uptime-Kuma monitor: %s", e)
            logger.info("Uptime-Kuma integration is optional - the service will continue without it")

    async def stop(self):
        """Stop Uptime-Kuma monitoring"""
        logger.info("Stopping Uptime-Kuma monitor...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # Expected during shutdown
            except Exception as e:
                logger.warning("Error stopping Uptime-Kuma task: %s", e)

        logger.info("Uptime-Kuma monitoring stopped")

    async def _refresh_monitor_cache(self):
        """Refresh cache of monitor IDs by friendly name"""
        if not self.client:
            return

        monitors = await self.client.get_all_monitors()
        self._monitor_cache = {m['friendly_name']: m for m in monitors}
        logger.info("Cached %s Uptime-Kuma monitors", len(self._monitor_cache))

    async def _monitoring_loop(self):
        """Main monitoring loop - check Uptime-Kuma statuses and cache them in sync with container checks"""
        config = config_manager.get_config()
        interval = config.monitor.interval_seconds
        offset = int(interval * 0.2)  # Refresh 20% before container check

        # Calculate the next container check time
        next_check = asyncio.get_event_loop().time() + interval

        while self._running:
            try:
                # Sleep until (next_check - offset)
                now = asyncio.get_event_loop().time()
                sleep_time = max(0, (next_check - offset) - now)
                await asyncio.sleep(sleep_time)

                await self._update_status_cache()

                # Schedule next check
                next_check += interval
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in Uptime-Kuma monitoring loop: %s", e)
                # On error, resync to next interval
                next_check = asyncio.get_event_loop().time() + interval

    async def _update_status_cache(self):
        """Update cache of container health statuses from Uptime-Kuma monitors"""
        config = config_manager.get_config()

        if not config.uptime_kuma_mappings:
            return

        try:
            # Fetch /metrics once per refresh and reuse it for every mapped container,
            # instead of re-fetching the full endpoint once per mapping (see #94)
            monitors = await self.client.get_all_monitors()
        except Exception as e:
            logger.error("Error fetching Uptime-Kuma monitor statuses: %s", e)
            return

        # Uptime-Kuma allows several monitors to share a friendly name, and mappings
        # identify a monitor only by that name. A name reported more than once is
        # ambiguous: picking either monitor's status could restart a container based
        # on a monitor that is not its own, so such a name yields no status at all.
        status_by_name = {m['friendly_name']: m['status'] for m in monitors}
        monitor_count_by_name = Counter(m["friendly_name"] for m in monitors)
        ambiguous_mappings: set[tuple[str, str]] = set()

        for mapping in config.uptime_kuma_mappings:
            mapping_key = (mapping.container_id, mapping.monitor_friendly_name)
            monitor_count = monitor_count_by_name[mapping.monitor_friendly_name]
            if monitor_count > 1:
                ambiguous_mappings.add(mapping_key)
                # The status is refreshed once per mapped container check, so warn
                # once per mapping until the name is unique again, not on every refresh.
                if mapping_key not in self._ambiguous_mappings:
                    logger.warning(
                        "Uptime-Kuma monitor name '%s' mapped to %s matches %d monitors - "
                        "ignoring its status because the monitor is ambiguous",
                        mapping.monitor_friendly_name,
                        mapping.container_id,
                        monitor_count,
                    )
                # Drop any status cached while the name was unique, so it cannot
                # keep driving a restart decision.
                self._container_status_cache.pop(mapping.container_id, None)
                continue

            status = status_by_name.get(mapping.monitor_friendly_name)

            if status is None:
                logger.debug(
                    "Monitor '%s' not found or could not fetch status",
                    mapping.monitor_friendly_name,
                )
                continue

            # Cache the status (0=down, 1=up, 2=pending, 3=maintenance)
            # mapping.container_id now stores stable_id
            self._container_status_cache[mapping.container_id] = status

            logger.debug(
                "Cached status for %s: %s (monitor: %s)",
                mapping.container_id,
                status,
                mapping.monitor_friendly_name,
            )

        self._ambiguous_mappings = ambiguous_mappings

    def get_container_status(self, stable_id: str) -> int | None:
        return self._container_status_cache.get(stable_id)

    def is_container_mapped(self, stable_id: str) -> bool:
        config = config_manager.get_config()
        if not config.uptime_kuma_mappings:
            return False

        return any(mapping.container_id == stable_id for mapping in config.uptime_kuma_mappings)

    async def should_restart_from_uptime_kuma(self, stable_id: str) -> bool:
        config = config_manager.get_config()

        # Check if auto-restart on down is enabled
        if not config.uptime_kuma.auto_restart_on_down:
            return False

        # Check if container is mapped
        if not self.is_container_mapped(stable_id):
            return False

        # Update cache (async)
        await self._update_status_cache()

        # Check monitor status
        status = self.get_container_status(stable_id)

        # Status 0 = down
        return status == 0

