"""
Uptime-Kuma API client for fetching monitor statuses
Uses the /metrics endpoint with Basic Authentication
"""
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)


class UptimeKumaClient:
    """Client for interacting with Uptime-Kuma API using /metrics endpoint"""

    def __init__(self, server_url: str, password: str, username: str = ""):
        """Configure the metrics endpoint and its Basic authentication header."""
        self.server_url = server_url.rstrip('/')
        self.password = password
        self.username = username
        # Use Basic Auth with username (empty for API key) and password/API key
        # For API key: username="", password=api_key
        # For user auth: username=username, password=password
        # Keep BasicAuth's Latin-1 default for compatibility with existing credentials.
        self.auth_header = aiohttp.encode_basic_auth(
            username if username else '', password, encoding="latin1"
        )
        self.session: aiohttp.ClientSession | None = None

    async def connect(self) -> bool:
        """Test connection to Uptime-Kuma server"""
        try:
            logger.debug("Attempting to connect to %s/metrics", self.server_url)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.server_url}/metrics",
                    headers={"Authorization": self.auth_header},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    logger.debug("Response status: %s", response.status)
                    if response.status == 200:
                        text = await response.text()
                        # Check if we got valid metrics data
                        has_metrics = 'monitor_status' in text or 'app_version' in text
                        logger.debug("Has metrics data: %s", has_metrics)
                        return has_metrics
                    logger.warning("Unexpected response status: %s", response.status)
                    return False
        except Exception as e:
            logger.warning("Failed to connect to Uptime-Kuma: %s", e)
            return False

    async def get_all_monitors(self) -> list[dict] | None:
        """Fetch all monitors from /metrics endpoint.

        Returns None if the request fails, so callers can tell a failed fetch apart
        from a successful response that contains no monitors (an empty list).
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.server_url}/metrics",
                    headers={"Authorization": self.auth_header},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        logger.error("Failed to fetch metrics: HTTP %s", response.status)
                        return None

                    text = await response.text()
                    monitors = self._parse_monitors_from_metrics(text)
                    logger.debug("Parsed %s monitors from metrics", len(monitors))
                    return monitors
        except Exception as e:
            logger.error("Failed to fetch monitors: %s", e)
            return None

    def _parse_monitors_from_metrics(self, metrics_text: str) -> list[dict]:
        """Parse monitor data from Prometheus metrics format"""
        # Uptime-Kuma allows two monitors to share a friendly name. Keeping both
        # lets the auto-mapper see the ambiguity and refuse to guess; collapsing
        # them here would silently bind a container to whichever one came last.
        monitors = []

        # Parse monitor_status lines
        # Uptime-Kuma emits monitor_id (and any custom tags) before monitor_name, e.g.:
        # monitor_status{monitor_id="5",monitor_name="My Monitor",monitor_url="https://example.com",monitor_hostname="",monitor_port=""} 1
        # so monitor_name must be matched anywhere within the label set, not just as the first
        # label. The optional "preceded by { or ," group anchors monitor_name to a full label
        # key so a custom tag like custom_monitor_name isn't matched as a substring.
        status_pattern = r'monitor_status\{(?:[^}]*,)?monitor_name="([^"]+)"[^}]*\}\s+(\d+)'

        for match in re.finditer(status_pattern, metrics_text):
            monitor_name = match.group(1)
            status = int(match.group(2))

            # Generate a simple ID based on the name (since metrics don't provide IDs)
            monitor_id = abs(hash(monitor_name)) % (10 ** 8)

            monitors.append({
                'id': monitor_id,
                'friendly_name': monitor_name,
                'status': status  # 0=down, 1=up, 2=pending, 3=maintenance
            })

        return monitors

    async def get_monitor_status(self, monitor_id: int) -> int | None:
        """Get status of a specific monitor by ID"""
        # Since we use hashed IDs, we need to fetch all monitors and find the matching one
        monitors = await self.get_all_monitors() or []
        for monitor in monitors:
            if monitor['id'] == monitor_id:
                return monitor['status']
        return None

    async def get_monitor_status_by_name(self, monitor_name: str) -> int | None:
        """Get status of a specific monitor by friendly name"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.server_url}/metrics",
                    headers={"Authorization": self.auth_header},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        return None

                    text = await response.text()
                    # Look for this specific monitor's status. monitor_id (and any custom
                    # tags) can precede monitor_name in the label set, so don't anchor to it
                    # being the first label - but still require monitor_name to be a full
                    # label key (preceded by { or ,), not a substring of a custom tag name.
                    pattern = rf'monitor_status\{{(?:[^}}]*,)?monitor_name="{re.escape(monitor_name)}"[^}}]*\}}\s+(\d+)'
                    match = re.search(pattern, text)

                    if match:
                        return int(match.group(1))
                    return None
        except Exception as e:
            logger.error("Failed to get monitor status for '%s': %s", monitor_name, e)
            return None
