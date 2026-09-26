"""
Unit tests for the Uptime-Kuma integration endpoints in
``app/api/routes/uptime_kuma.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client - ``config_manager`` is isolated per test
(see ``conftest.py``), and ``FakeUptimeKumaClient`` stands in for the real
Uptime-Kuma client so no outbound HTTP request is ever attempted.
"""

import pytest
from fastapi import HTTPException

from app.api.routes.uptime_kuma import (
    create_uptime_kuma_mapping,
    delete_uptime_kuma_mapping,
    disable_uptime_kuma_integration,
    enable_uptime_kuma_integration,
    get_uptime_kuma_mappings,
    get_uptime_kuma_monitors,
)
from app.api.routes.uptime_kuma import (
    test_uptime_kuma_connection as api_test_uptime_kuma_connection,
)
from app.config.config_manager import config_manager
from app.tests.unit.conftest import FakeUptimeKumaClient, make_container


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    """Point the API module's shared state at the fake Docker client/engine."""
    monkeypatch.setattr("app.api.state.docker_client", docker_client)
    monkeypatch.setattr("app.api.state.monitoring_engine", engine)
    return docker_client, engine


@pytest.mark.asyncio
class TestUptimeKumaConnection:
    async def test_successful_connection_reports_monitor_count(self, monkeypatch):
        fake_client = FakeUptimeKumaClient(
            connect_result=True, monitors=[{"id": 1}, {"id": 2}]
        )
        monkeypatch.setattr(
            "app.uptime_kuma.uptime_kuma_client.UptimeKumaClient",
            lambda *a, **k: fake_client,
        )

        result = await api_test_uptime_kuma_connection(
            {"server_url": "http://kuma.example", "api_token": "token"}
        )

        assert result["success"] is True
        assert result["monitor_count"] == 2

    async def test_failed_connection_reports_failure_without_raising(self, monkeypatch):
        fake_client = FakeUptimeKumaClient(connect_result=False)
        monkeypatch.setattr(
            "app.uptime_kuma.uptime_kuma_client.UptimeKumaClient",
            lambda *a, **k: fake_client,
        )

        result = await api_test_uptime_kuma_connection(
            {"server_url": "http://kuma.example"}
        )

        assert result["success"] is False


@pytest.mark.asyncio
class TestUptimeKumaIntegration:
    async def test_enable_auto_maps_containers_by_matching_name(
        self, wired_api, monkeypatch
    ):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        fake_client = FakeUptimeKumaClient(
            monitors=[{"friendly_name": "web"}, {"friendly_name": "unrelated"}]
        )
        monkeypatch.setattr(
            "app.uptime_kuma.uptime_kuma_client.UptimeKumaClient",
            lambda *a, **k: fake_client,
        )

        result = await enable_uptime_kuma_integration(
            {"server_url": "http://kuma.example", "api_token": "token"}
        )

        assert result["success"] is True
        assert len(result["auto_mappings"]) == 1
        assert result["auto_mappings"][0]["monitor_friendly_name"] == "web"
        assert config_manager.get_config().uptime_kuma.enabled is True

    async def test_get_monitors_when_integration_disabled_returns_400(self):
        with pytest.raises(HTTPException) as exc_info:
            await get_uptime_kuma_monitors()

        assert exc_info.value.status_code == 400

    async def test_create_and_list_and_delete_mapping(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        created = await create_uptime_kuma_mapping(
            {"container_id": "a" * 64, "monitor_friendly_name": "web"}
        )
        assert created["success"] is True

        listed = await get_uptime_kuma_mappings()
        assert [m["container_id"] for m in listed["mappings"]] == ["web"]

        deleted = await delete_uptime_kuma_mapping("web")
        assert deleted["success"] is True
        assert (await get_uptime_kuma_mappings())["mappings"] == []

    async def test_disable_turns_off_integration_flag(self):
        config = config_manager.get_config()
        config.uptime_kuma.enabled = True
        config_manager.update_config(config)

        result = await disable_uptime_kuma_integration()

        assert result["success"] is True
        assert config_manager.get_config().uptime_kuma.enabled is False
