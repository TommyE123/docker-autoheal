"""
Prometheus metrics for Docker Autoheal

Registered in the default registry when this module is first imported. ``app.main`` serves
them with ``start_http_server`` when Prometheus is enabled; the monitor updates them.
"""

from prometheus_client import Counter, Gauge

from app.config.config_manager import config_manager

container_restarts = Counter(
    "autoheal_container_restarts_total", "Total container restarts", ["container_name"]
)
containers_monitored = Gauge(
    "autoheal_containers_monitored", "Number of containers being monitored"
)
containers_quarantined = Gauge(
    "autoheal_containers_quarantined", "Number of quarantined containers"
)
health_checks_total = Counter("autoheal_health_checks_total", "Total health checks performed")
health_checks_failed = Counter(
    "autoheal_health_checks_failed", "Failed health checks", ["container_name"]
)

# Read at scrape time; get_quarantined_containers copies the set under the manager's lock
containers_quarantined.set_function(lambda: len(config_manager.get_quarantined_containers()))


def record_health_check(container_name: str, *, failed: bool) -> None:
    """
    Count one health check that ran, and its failure
    Args:
        container_name: Name of the checked container, used as the failure label
        failed: True when the check reported the container unhealthy
    """
    health_checks_total.inc()
    if failed:
        health_checks_failed.labels(container_name=container_name).inc()
