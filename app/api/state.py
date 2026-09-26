"""
Shared mutable API state.

``docker_client``/``monitoring_engine`` are set once by ``init_api()`` (called
from ``app/main.py`` during startup) and ``notification_manager`` is the
process-wide singleton; every route module in ``app/api/routes/`` reads these
three via ``app.api.state`` at call time (``state.docker_client``, not a
one-time ``from app.api.state import docker_client``), so both a later
``init_api()`` call and a test's ``monkeypatch.setattr("app.api.state.X", ...)``
are seen by every route.

Split out of ``app/api/api.py`` (issue #321) into its own module - with no
dependency on ``app.api.api`` or any route module - specifically so route
modules can import this shared state without creating a circular import with
``api.py`` (which imports the route modules to register them).
"""

import logging
from typing import Optional

from app.docker_client.docker_client_wrapper import DockerClientWrapper
from app.monitor.monitoring_engine import MonitoringEngine
from app.notifications.notification_manager import notification_manager  # noqa: F401

logger = logging.getLogger("app.api.api")

docker_client: Optional[DockerClientWrapper] = None
monitoring_engine: Optional[MonitoringEngine] = None


def init_api(docker_client_instance: DockerClientWrapper, monitoring_engine_instance: MonitoringEngine):
    """Initialize API with Docker client and monitoring engine"""
    global docker_client, monitoring_engine
    docker_client = docker_client_instance
    monitoring_engine = monitoring_engine_instance
