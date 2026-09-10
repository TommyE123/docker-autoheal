"""
Smoke test for a running Auto-Heal service: health endpoint, API status,
the React UI, and (best-effort) the Prometheus metrics endpoint.

Converted from the root-level `test_service.py` manual script, which printed
status emoji for each check and called `sys.exit` based on a hand-rolled pass
count instead of asserting.

Requires a running Auto-Heal service reachable at http://localhost:3131.
The metrics check is skipped (not failed) if Prometheus is disabled.
"""

import requests

AUTOHEAL_BASE_URL = "http://localhost:3131"
METRICS_URL = "http://localhost:9090/metrics"


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
    try:
        response = requests.get(METRICS_URL, timeout=5)
    except requests.exceptions.ConnectionError:
        import pytest

        pytest.skip("Prometheus metrics endpoint not reachable (may be disabled)")
    assert response.status_code == 200
