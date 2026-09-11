"""
Smoke test for a running Auto-Heal service: health endpoint, API status,
the React UI, and (best-effort) the Prometheus metrics endpoint.

Requires a running Auto-Heal service reachable at http://localhost:3131.
"""

import pytest
import requests

AUTOHEAL_BASE_URL = "http://localhost:3131"

pytestmark = pytest.mark.integration


def test_health_endpoint(running_service):
    response = requests.get(f"{AUTOHEAL_BASE_URL}/health", timeout=5)
    assert response.status_code == 200
    data = response.json()
    assert "docker_connected" in data
    assert "monitoring_active" in data


def test_api_status_endpoint(running_service):
    response = requests.get(f"{AUTOHEAL_BASE_URL}/api/status", timeout=5)
    assert response.status_code == 200
    data = response.json()
    assert "total_containers" in data
    assert "monitored_containers" in data


def test_react_ui_is_served(running_service):
    response = requests.get(AUTOHEAL_BASE_URL, timeout=5)
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "root" in response.text


def test_prometheus_metrics_endpoint(running_service):
    config = requests.get(f"{AUTOHEAL_BASE_URL}/api/config", timeout=5).json()
    observability = config["observability"]
    if not observability["prometheus_enabled"]:
        pytest.skip("Prometheus metrics are disabled in the running service's config")

    metrics_port = observability["metrics_port"]
    response = requests.get(f"http://localhost:{metrics_port}/metrics", timeout=5)
    assert response.status_code == 200
