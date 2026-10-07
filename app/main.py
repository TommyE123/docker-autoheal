"""
Main entry point for Docker Auto-Heal Service
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn
from prometheus_client import Counter, Gauge, start_http_server

from app.api.api import app, init_api
from app.config.config_manager import config_manager
from app.docker_client.docker_client_wrapper import DockerClientWrapper
from app.monitor.monitoring_engine import MonitoringEngine
from app.monitor.uptime_kuma_monitor import UptimeKumaMonitor
from app.notifications.notification_manager import notification_manager

# Ensure /data/logs directory exists
LOG_DIR = Path("/data/logs")
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    # Fallback to ./data/logs if /data is not writable
    LOG_DIR = Path("./data/logs")
    LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "autoheal.log"

# Configure logging (will be updated with config)
logging.basicConfig(
    level=logging.INFO,  # Default, will be updated
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE))
    ]
)

logger = logging.getLogger(__name__)
logger.info("Logging to: %s", LOG_FILE)


class CancelledErrorFilter(logging.Filter):
    """Filter to suppress CancelledError from uvicorn.error logs during shutdown"""
    def filter(self, record):
        # Suppress CancelledError tracebacks from uvicorn (these are expected during shutdown)
        return not (record.name == "uvicorn.error" and "CancelledError" in record.getMessage())


def update_log_level(level_name: str):
    """Update logging level for all loggers"""
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    level = level_map.get(level_name.upper(), logging.INFO)

    # Set root logger level
    logging.getLogger().setLevel(level)

    # Disable uvicorn access logs completely (set to WARNING to suppress INFO logs)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)

    # Add filter to suppress CancelledError tracebacks
    logging.getLogger("uvicorn.error").addFilter(CancelledErrorFilter())

    logger.info("Log level set to: %s", level_name)

# Prometheus metrics
container_restarts = Counter('autoheal_container_restarts_total', 'Total container restarts', ['container_name'])
containers_monitored = Gauge('autoheal_containers_monitored', 'Number of containers being monitored')
containers_quarantined = Gauge('autoheal_containers_quarantined', 'Number of quarantined containers')
health_checks_total = Counter('autoheal_health_checks_total', 'Total health checks performed')
health_checks_failed = Counter('autoheal_health_checks_failed', 'Failed health checks', ['container_name'])


class AutoHealService:
    """Main service orchestrator"""

    def __init__(self):
        self.docker_client: DockerClientWrapper | None = None
        self.monitoring_engine: MonitoringEngine | None = None
        self.notification_manager = notification_manager
        self.uptime_kuma_monitor: UptimeKumaMonitor | None = None
        self.running = False

    async def start(self):
        """Start the auto-heal service"""
        try:
            logger.info("Starting Docker Auto-Heal Service v%s", app.version)

            # Load configuration
            config = config_manager.get_config()

            # Set log level from config
            update_log_level(config.observability.log_level)

            logger.info(
                "Configuration loaded: monitoring interval=%ss", config.monitor.interval_seconds
            )

            # Initialize Docker client
            logger.info("Connecting to Docker daemon...")
            self.docker_client = DockerClientWrapper()
            logger.info("Docker client connected successfully")

            # Initialize monitoring engine
            logger.info("Initializing monitoring engine...")
            self.monitoring_engine = MonitoringEngine(self.docker_client)

            # Initialize Uptime-Kuma monitor (independent service that provides status)
            logger.info("Initializing Uptime-Kuma monitor...")
            self.uptime_kuma_monitor = UptimeKumaMonitor()

            # Attach to monitoring engine for API access
            self.monitoring_engine.uptime_kuma_monitor = self.uptime_kuma_monitor

            # Initialize API
            init_api(self.docker_client, self.monitoring_engine)

            # Start Prometheus metrics server if enabled
            if config.observability.prometheus_enabled:
                logger.info(
                    "Starting Prometheus metrics server on port %s",
                    config.observability.metrics_port,
                )
                start_http_server(config.observability.metrics_port)

            # Start notification manager
            logger.info("Starting notification manager...")
            await self.notification_manager.start()
            if config.notifications.enabled:
                logger.info(
                    "Notifications enabled with %s service(s)", len(config.notifications.services)
                )

            # Start monitoring engine
            logger.info("Starting monitoring engine...")
            await self.monitoring_engine.start()

            # Start Uptime-Kuma monitor
            logger.info("Uptime-Kuma enabled status: %s", config.uptime_kuma.enabled)
            if config.uptime_kuma.enabled:
                logger.info("Starting Uptime-Kuma monitor...")
                try:
                    await self.uptime_kuma_monitor.start()
                except Exception as e:
                    logger.warning("Uptime-Kuma failed to start: %s", e)

            self.running = True
            logger.info("Docker Auto-Heal Service started successfully")
            ui_url = get_ui_url(config)
            public_port = get_public_port()
            if ui_url:
                logger.info("Web UI available at %s", ui_url)
                logger.info("API documentation available at %s/docs", ui_url)
            elif public_port:
                container_port = config.ui.listen_port
                logger.info(
                    "Web UI published on host port %s (container port %s)",
                    public_port,
                    container_port,
                )
                logger.info(
                    "API documentation published on host port %s at /docs (container port %s)",
                    public_port,
                    container_port,
                )
            else:
                listen = f"{config.ui.listen_address}:{config.ui.listen_port}"
                logger.info("Web UI listening on %s", listen)
                logger.info("API documentation listening on %s/docs", listen)

        except Exception as e:
            logger.exception("Failed to start service: %s", e)
            if self.notification_manager:
                await self.notification_manager.stop()
            raise

    async def stop(self):
        """Stop the auto-heal service"""
        logger.info("Stopping Docker Auto-Heal Service...")

        self.running = False

        # Stop components gracefully with error handling
        if self.uptime_kuma_monitor:
            try:
                await self.uptime_kuma_monitor.stop()
            except Exception as e:
                logger.warning("Error stopping Uptime-Kuma monitor: %s", e)

        if self.monitoring_engine:
            try:
                await self.monitoring_engine.stop()
            except Exception as e:
                logger.warning("Error stopping monitoring engine: %s", e)

        try:
            await self.notification_manager.stop()
        except Exception as e:
            logger.warning("Error stopping notification manager: %s", e, exc_info=True)

        if self.docker_client:
            try:
                self.docker_client.close()
            except Exception as e:
                logger.warning("Error closing Docker client: %s", e)

        logger.info("Docker Auto-Heal Service stopped")

    async def run(self):
        """Run the service (blocking)"""
        await self.start()

        # Keep running until stopped
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


# Global service instance
service: AutoHealService | None = None


def get_public_port() -> str | None:
    """Return the host port the UI is published on (``AUTOHEAL_PUBLIC_PORT``), if supplied."""
    return os.environ.get("AUTOHEAL_PUBLIC_PORT", "").strip() or None


def get_ui_url(config) -> str | None:
    """
    Build the user-facing URL for the startup messages, or None if no host was supplied.

    Display only: the server still binds to ``config.ui.listen_address`` and
    ``config.ui.listen_port``. A bind address such as 0.0.0.0 is not a URL a user can open,
    and the application cannot know which address other machines reach the host at, so a
    URL is only built when ``AUTOHEAL_PUBLIC_HOST`` is set. The port is the published one
    (``AUTOHEAL_PUBLIC_PORT``), falling back to the listen port when unset or empty.
    """
    host = os.environ.get("AUTOHEAL_PUBLIC_HOST", "").strip()
    if not host:
        return None
    return f"http://{host}:{get_public_port() or config.ui.listen_port}"


def signal_handler(signum, _frame):
    """Handle shutdown signals"""
    logger.info("Received signal %s, initiating shutdown...", signum)
    if service:
        asyncio.create_task(service.stop())


async def run_api_server():
    """Run FastAPI server"""
    config = config_manager.get_config()

    # Disable all uvicorn access logs completely
    uvicorn_config = uvicorn.Config(
        app,
        host=config.ui.listen_address,
        port=config.ui.listen_port,
        log_level="warning",  # Set to warning to suppress info logs
        access_log=False,  # Completely disable access logs
        log_config=None  # Use default logging config
    )

    server = uvicorn.Server(uvicorn_config)
    await server.serve()


async def main():
    """Main entry point"""
    global service

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create service instance
    service = AutoHealService()

    # Start service and API server concurrently
    try:
        await asyncio.gather(
            service.run(),
            run_api_server(),
            return_exceptions=True  # Don't propagate CancelledError
        )
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except asyncio.CancelledError:
        logger.info("Application cancelled, shutting down gracefully")
    except Exception as e:
        logger.exception("Service error: %s", e)
    finally:
        if service and service.running:
            await service.stop()


if __name__ == "__main__":
    # Run the service
    asyncio.run(main())
