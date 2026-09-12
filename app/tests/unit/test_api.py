"""
Unit tests for the REST API endpoints in ``app/api/api.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client: none of them depend on FastAPI's request
parsing in a way that would be missed by calling the coroutine directly, and
this avoids adding a test-only HTTP client dependency the repository does not
already have. ``config_manager`` is isolated per test (see ``conftest.py``),
and the fake Docker client/monitoring engine mean no real Docker daemon is
ever touched.
"""

import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from app.api.api import (
    ContainerSelectionRequest,
    add_health_check,
    add_notification_service,
    create_uptime_kuma_mapping,
    delete_health_check,
    delete_notification_service,
    delete_uptime_kuma_mapping,
    disable_maintenance_mode,
    disable_uptime_kuma_integration,
    enable_maintenance_mode,
    enable_uptime_kuma_integration,
    export_config,
    get_config,
    get_container_details,
    get_health_check,
    get_maintenance_status,
    get_notifications_config,
    get_system_status,
    get_uptime_kuma_mappings,
    get_uptime_kuma_monitors,
    health_check,
    list_containers,
    list_health_checks,
    restart_container_manual,
    unquarantine_container,
    update_container_selection,
    update_monitor_config,
    update_notification_service,
    update_notifications_config,
    update_restart_config,
)
from app.api.api import import_config as api_import_config
from app.api.api import test_notification_service as api_test_notification_service
from app.api.api import test_uptime_kuma_connection as api_test_uptime_kuma_connection
from app.api.api import update_config as api_update_config
from app.config.config_manager import (
    HealthCheckConfig,
    MonitorConfig,
    NotificationService,
    RestartConfig,
    UptimeKumaMapping,
    config_manager,
)
from app.tests.unit.conftest import make_container


@pytest.fixture
def wired_api(monkeypatch, docker_client, engine):
    """Point the API module's globals at the fake Docker client/engine."""
    monkeypatch.setattr("app.api.api.docker_client", docker_client)
    monkeypatch.setattr("app.api.api.monitoring_engine", engine)
    return docker_client, engine


@pytest.fixture
def uninitialized_api(monkeypatch):
    """Simulate the API being called before ``init_api`` has run."""
    monkeypatch.setattr("app.api.api.docker_client", None)
    monkeypatch.setattr("app.api.api.monitoring_engine", None)


@pytest.mark.asyncio
class TestHealthCheck:
    async def test_reports_disconnected_and_inactive_when_uninitialized(self, uninitialized_api):
        result = await health_check()

        assert result["docker_connected"] is False
        assert result["monitoring_active"] is False
        assert result["status"] == "healthy"

    async def test_reports_connected_and_active(self, wired_api):
        docker_client, engine = wired_api
        engine._running = True

        result = await health_check()

        assert result["docker_connected"] is True
        assert result["monitoring_active"] is True


@pytest.mark.asyncio
class TestSystemStatus:
    async def test_counts_monitored_and_quarantined_containers(self, wired_api):
        docker_client, engine = wired_api
        monitored, monitored_info = make_container(name="web", status="running")
        docker_client.add_container(monitored, monitored_info)
        unmonitored, unmonitored_info = make_container(
            name="scratch", container_id="c" * 64, labels={}
        )
        docker_client.add_container(unmonitored, unmonitored_info)
        config_manager.quarantine_container("scratch")

        status = await get_system_status()

        assert status.total_containers == 2
        assert status.monitored_containers == 1
        assert status.quarantined_containers == 1
        assert status.docker_connected is True

    async def test_docker_failure_returns_500(self, wired_api):
        docker_client, _engine = wired_api
        docker_client.list_containers_error = RuntimeError("daemon unreachable")

        with pytest.raises(HTTPException) as exc_info:
            await get_system_status()

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestListContainers:
    async def test_returns_container_info_with_default_fields(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        result = await list_containers()

        assert len(result) == 1
        assert result[0].name == "web"
        assert result[0].monitored is True
        assert result[0].quarantined is False
        # Uptime-Kuma integration is disabled by default.
        assert result[0].uptime_kuma_status == 5

    async def test_reports_uptime_kuma_status_when_mapped(self, wired_api):
        docker_client, engine = wired_api
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.uptime_kuma.enabled = True
        config.uptime_kuma_mappings = [
            UptimeKumaMapping(container_id="web", monitor_friendly_name="Web Monitor")
        ]
        config_manager.update_config(config)
        engine.uptime_kuma_monitor = MagicMock()
        engine.uptime_kuma_monitor.is_container_mapped.return_value = True
        engine.uptime_kuma_monitor.get_container_status.return_value = 1  # up

        result = await list_containers()

        assert result[0].uptime_kuma_status == 1
        assert result[0].uptime_kuma_monitor_name == "Web Monitor"

    async def test_reports_unknown_status_when_uptime_kuma_monitor_not_initialized(self, wired_api):
        docker_client, engine = wired_api
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.uptime_kuma.enabled = True
        config_manager.update_config(config)
        # engine has no `uptime_kuma_monitor` attribute, mirroring a service
        # that hasn't finished initializing the integration yet.
        assert not hasattr(engine, "uptime_kuma_monitor")

        result = await list_containers()

        assert result[0].uptime_kuma_status == 4
        assert result[0].uptime_kuma_monitor_name is None

    async def test_skips_containers_docker_could_not_inspect(self, wired_api):
        docker_client, _engine = wired_api
        # Registered with the client but with no info recorded, mirroring a
        # container that disappeared between listing and inspection.
        container, _info = make_container(name="vanished")
        docker_client._containers.append(container)

        result = await list_containers()

        assert result == []

    async def test_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await list_containers()

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestGetContainerDetails:
    async def test_returns_details_for_known_container(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        details = await get_container_details("a" * 64)

        assert details["name"] == "web"
        assert details["monitored"] is True
        assert details["quarantined"] is False
        assert details["total_restart_count"] == 0

    async def test_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_container_details("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_container_details("anything")

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestUpdateContainerSelection:
    async def test_enabling_adds_stable_id_and_clears_exclusion(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.containers.excluded = ["web"]
        config_manager.update_config(config)

        await update_container_selection(
            ContainerSelectionRequest(container_ids=["a" * 64], enabled=True)
        )

        updated = config_manager.get_config()
        assert "web" in updated.containers.selected
        assert "web" not in updated.containers.excluded

    async def test_disabling_adds_to_excluded_and_clears_selection(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config = config_manager.get_config()
        config.containers.selected = ["web"]
        config_manager.update_config(config)

        await update_container_selection(
            ContainerSelectionRequest(container_ids=["a" * 64], enabled=False)
        )

        updated = config_manager.get_config()
        assert "web" in updated.containers.excluded
        assert "web" not in updated.containers.selected

    async def test_unresolvable_container_falls_back_to_raw_identifier(self, wired_api):
        # No container registered with this id, so docker_client.get_container()
        # returns None and the endpoint must fall back to storing the raw id.
        await update_container_selection(
            ContainerSelectionRequest(container_ids=["ghost-container"], enabled=True)
        )

        updated = config_manager.get_config()
        assert "ghost-container" in updated.containers.selected


@pytest.mark.asyncio
class TestRestartContainerManual:
    async def test_successful_restart(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        result = await restart_container_manual("a" * 64)

        assert result["status"] == "success"
        assert docker_client.restart_calls == ["web"]

    async def test_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_docker_restart_failure_returns_500(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("a" * 64)

        assert exc_info.value.status_code == 500

    async def test_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await restart_container_manual("anything")

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestUnquarantineContainer:
    async def test_clears_quarantine_and_restart_history(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        config_manager.record_restart("web")

        result = await unquarantine_container("a" * 64)

        assert result["status"] == "success"
        assert config_manager.is_quarantined("web") is False
        assert config_manager.get_total_restart_count("web") == 0
        events = config_manager.get_events()
        assert events[-1].event_type == "unquarantine"

    async def test_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await unquarantine_container("does-not-exist")

        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
class TestMaintenanceMode:
    async def test_enable_reports_start_time(self):
        result = await enable_maintenance_mode()

        assert result["maintenance_mode"] is True
        assert result["maintenance_start_time"] is not None
        assert config_manager.is_maintenance_mode() is True

    async def test_disable_clears_maintenance_mode(self):
        config_manager.enable_maintenance_mode()

        result = await disable_maintenance_mode()

        assert result["maintenance_mode"] is False
        assert config_manager.is_maintenance_mode() is False

    async def test_status_reflects_current_state(self):
        assert (await get_maintenance_status())["maintenance_mode"] is False

        config_manager.enable_maintenance_mode()

        status = await get_maintenance_status()
        assert status["maintenance_mode"] is True
        assert status["maintenance_start_time"] is not None


@pytest.mark.asyncio
class TestConfigurationEndpoints:
    async def test_get_config_returns_current_config(self):
        config = config_manager.get_config()
        config.monitor.interval_seconds = 42
        config_manager.update_config(config)

        result = await get_config()

        assert result.monitor.interval_seconds == 42

    async def test_update_config_persists_full_config(self):
        new_config = config_manager.get_config()
        new_config.monitor.interval_seconds = 99

        result = await api_update_config(new_config)

        assert result["status"] == "success"
        assert config_manager.get_config().monitor.interval_seconds == 99

    async def test_update_monitor_config_only_changes_monitor_section(self):
        original_restart_mode = config_manager.get_config().restart.mode

        await update_monitor_config(MonitorConfig(interval_seconds=15))

        updated = config_manager.get_config()
        assert updated.monitor.interval_seconds == 15
        assert updated.restart.mode == original_restart_mode

    async def test_update_restart_config_only_changes_restart_section(self):
        original_interval = config_manager.get_config().monitor.interval_seconds

        await update_restart_config(RestartConfig(mode="both", max_restarts=7))

        updated = config_manager.get_config()
        assert updated.restart.mode == "both"
        assert updated.restart.max_restarts == 7
        assert updated.monitor.interval_seconds == original_interval


class _FakeUptimeKumaClient:
    """Stand-in for ``UptimeKumaClient`` with no real HTTP/WebSocket access."""

    def __init__(self, connect_result: bool = True, monitors=None):
        self._connect_result = connect_result
        self._monitors = monitors if monitors is not None else []

    async def connect(self) -> bool:
        return self._connect_result

    async def get_all_monitors(self):
        return self._monitors


@pytest.mark.asyncio
class TestUptimeKumaConnection:
    async def test_successful_connection_reports_monitor_count(self, monkeypatch):
        fake_client = _FakeUptimeKumaClient(connect_result=True, monitors=[{"id": 1}, {"id": 2}])
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
        fake_client = _FakeUptimeKumaClient(connect_result=False)
        monkeypatch.setattr(
            "app.uptime_kuma.uptime_kuma_client.UptimeKumaClient",
            lambda *a, **k: fake_client,
        )

        result = await api_test_uptime_kuma_connection({"server_url": "http://kuma.example"})

        assert result["success"] is False


@pytest.mark.asyncio
class TestUptimeKumaIntegration:
    async def test_enable_auto_maps_containers_by_matching_name(self, wired_api, monkeypatch):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        fake_client = _FakeUptimeKumaClient(
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


@pytest.mark.asyncio
class TestHealthCheckManagement:
    async def test_add_health_check_resolves_full_container_id(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        result = await add_health_check(
            HealthCheckConfig(container_id="web", check_type="http", http_endpoint="http://localhost/health")
        )

        assert result["status"] == "success"
        stored = config_manager.get_custom_health_check("a" * 64)
        assert stored is not None
        assert stored.container_id == "a" * 64
        assert stored.check_type == "http"

    async def test_add_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(
                HealthCheckConfig(container_id="does-not-exist", check_type="tcp", tcp_port=8080)
            )

        assert exc_info.value.status_code == 404

    async def test_add_health_check_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await add_health_check(HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080))

        assert exc_info.value.status_code == 500

    async def test_get_health_check_returns_stored_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await get_health_check("web")

        assert result.container_id == "a" * 64
        assert result.check_type == "tcp"

    async def test_get_health_check_missing_check_returns_404(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)

        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        assert exc_info.value.status_code == 404

    async def test_get_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_get_health_check_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await get_health_check("web")

        assert exc_info.value.status_code == 500

    async def test_delete_health_check_removes_stored_check(self, wired_api):
        docker_client, _engine = wired_api
        container, info = make_container(name="web", container_id="a" * 64)
        docker_client.add_container(container, info)
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )

        result = await delete_health_check("web")

        assert result["status"] == "success"
        assert config_manager.get_custom_health_check("a" * 64) is None

    async def test_delete_health_check_unknown_container_returns_404(self, wired_api):
        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("does-not-exist")

        assert exc_info.value.status_code == 404

    async def test_delete_health_check_uninitialized_docker_client_returns_500(self, uninitialized_api):
        with pytest.raises(HTTPException) as exc_info:
            await delete_health_check("web")

        assert exc_info.value.status_code == 500

    async def test_list_health_checks_returns_all_registered_checks(self):
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="a" * 64, check_type="tcp", tcp_port=8080)
        )
        config_manager.add_custom_health_check(
            HealthCheckConfig(container_id="b" * 64, check_type="http", http_endpoint="http://localhost/")
        )

        result = await list_health_checks()

        assert set(result.keys()) == {"a" * 64, "b" * 64}

    async def test_list_health_checks_empty_by_default(self):
        assert await list_health_checks() == {}


@pytest.mark.asyncio
class TestNotificationsConfig:
    async def test_get_notifications_config_returns_defaults(self):
        result = await get_notifications_config()

        assert result["enabled"] is False
        assert result["services"] == []
        assert "restart" in result["event_filters"]

    async def test_get_notifications_config_reflects_current_state(self):
        config = config_manager.get_config()
        config.notifications.enabled = True
        config.notifications.services = [
            NotificationService(name="Slack", type="slack", url="https://example.invalid/slack")
        ]
        config_manager.update_config(config)

        result = await get_notifications_config()

        assert result["enabled"] is True
        assert result["services"][0]["name"] == "Slack"

    async def test_update_notifications_config_updates_enabled_and_filters(self):
        result = await update_notifications_config({"enabled": True, "event_filters": ["restart"]})

        assert result["status"] == "success"
        updated = config_manager.get_config()
        assert updated.notifications.enabled is True
        assert updated.notifications.event_filters == ["restart"]

    async def test_update_notifications_config_replaces_services(self):
        result = await update_notifications_config(
            {"services": [{"name": "Webhook", "type": "webhook", "url": "https://example.invalid/hook"}]}
        )

        assert result["config"]["services"][0]["name"] == "Webhook"
        assert config_manager.get_config().notifications.services[0].name == "Webhook"

    async def test_update_notifications_config_invalid_service_returns_500(self):
        # Missing the required "type" field, so NotificationService(**data) raises.
        with pytest.raises(HTTPException) as exc_info:
            await update_notifications_config({"services": [{"name": "Missing Type"}]})

        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
class TestNotificationServiceCrud:
    async def test_add_notification_service_success(self):
        result = await add_notification_service(
            {"name": "Webhook", "type": "webhook", "url": "https://example.invalid/hook"}
        )

        assert result["status"] == "success"
        assert result["service"]["name"] == "Webhook"
        assert config_manager.get_config().notifications.services[0].name == "Webhook"

    async def test_add_notification_service_duplicate_name_returns_400(self):
        await add_notification_service(
            {"name": "Webhook", "type": "webhook", "url": "https://example.invalid/hook"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_notification_service(
                {"name": "Webhook", "type": "slack", "url": "https://example.invalid/other"}
            )

        assert exc_info.value.status_code == 400
        assert len(config_manager.get_config().notifications.services) == 1

    async def test_add_notification_service_invalid_payload_returns_500(self):
        with pytest.raises(HTTPException) as exc_info:
            await add_notification_service({"name": "Missing Type"})

        assert exc_info.value.status_code == 500

    async def test_update_notification_service_preserves_name_when_omitted(self):
        await add_notification_service(
            {"name": "Webhook", "type": "webhook", "url": "https://example.invalid/hook"}
        )

        result = await update_notification_service(
            "Webhook", {"type": "webhook", "url": "https://example.invalid/updated"}
        )

        assert result["status"] == "success"
        assert result["service"]["name"] == "Webhook"
        assert result["service"]["url"] == "https://example.invalid/updated"
        stored = config_manager.get_config().notifications.services[0]
        assert stored.url == "https://example.invalid/updated"

    async def test_update_notification_service_unknown_name_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            await update_notification_service("does-not-exist", {"type": "webhook"})

        assert exc_info.value.status_code == 404

    async def test_delete_notification_service_success(self):
        await add_notification_service(
            {"name": "Webhook", "type": "webhook", "url": "https://example.invalid/hook"}
        )

        result = await delete_notification_service("Webhook")

        assert result["status"] == "success"
        assert config_manager.get_config().notifications.services == []

    async def test_delete_notification_service_unknown_name_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            await delete_notification_service("does-not-exist")

        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
class TestNotificationServiceTest:
    """Delegation only; delivery itself is covered by NotificationManager's own tests."""

    async def test_success_delegates_to_notification_manager(self, monkeypatch):
        fake_test_notification = AsyncMock(
            return_value={"success": True, "message": "Test notification sent successfully"}
        )
        monkeypatch.setattr("app.api.api.notification_manager.test_notification", fake_test_notification)

        result = await api_test_notification_service("Webhook")

        assert result == {"status": "success", "message": "Test notification sent successfully"}
        fake_test_notification.assert_awaited_once_with("Webhook")

    async def test_failure_result_raises_400_with_manager_message(self, monkeypatch):
        fake_test_notification = AsyncMock(
            return_value={"success": False, "message": "Service 'Webhook' not found"}
        )
        monkeypatch.setattr("app.api.api.notification_manager.test_notification", fake_test_notification)

        with pytest.raises(HTTPException) as exc_info:
            await api_test_notification_service("Webhook")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Service 'Webhook' not found"


@pytest.mark.asyncio
class TestConfigExportImport:
    async def test_export_config_returns_current_config_as_downloadable_json(self):
        config = config_manager.get_config()
        config.monitor.interval_seconds = 77
        config_manager.update_config(config)

        response = await export_config()

        assert response.status_code == 200
        assert "attachment; filename=autoheal-config-" in response.headers["content-disposition"]
        body = json.loads(bytes(response.body))
        assert body["monitor"]["interval_seconds"] == 77

    async def test_export_config_failure_returns_500(self, monkeypatch):
        monkeypatch.setattr(
            config_manager, "export_config", MagicMock(side_effect=RuntimeError("disk error"))
        )

        with pytest.raises(HTTPException) as exc_info:
            await export_config()

        assert exc_info.value.status_code == 500

    async def test_import_config_applies_uploaded_configuration(self):
        new_config = config_manager.get_config()
        new_config.monitor.interval_seconds = 123
        payload = new_config.model_dump_json()
        upload = UploadFile(file=BytesIO(payload.encode("utf-8")), filename="config.json")

        result = await api_import_config(upload)

        assert result["status"] == "success"
        assert config_manager.get_config().monitor.interval_seconds == 123

    async def test_import_config_invalid_json_returns_500(self):
        upload = UploadFile(file=BytesIO(b"not valid json"), filename="config.json")

        with pytest.raises(HTTPException) as exc_info:
            await api_import_config(upload)

        assert exc_info.value.status_code == 500
