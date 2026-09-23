"""Tests for ConfigManager state transitions and persisted round trips."""

from datetime import datetime, timezone
from unittest.mock import patch

from app.config.config_manager import (
    AutoHealEvent,
    ConfigManager,
    HealthCheckConfig,
)


def _redirect_manager_paths(monkeypatch, data_dir):
    paths = {
        "DATA_DIR": data_dir,
        "CONFIG_FILE": data_dir / "config.json",
        "EVENTS_FILE": data_dir / "events.json",
        "RESTART_COUNTS_FILE": data_dir / "restart_counts.json",
        "QUARANTINE_FILE": data_dir / "quarantine.json",
        "MAINTENANCE_FILE": data_dir / "maintenance.json",
    }
    for attribute, path in paths.items():
        monkeypatch.setattr(ConfigManager, attribute, path)


def _make_event(container_id="web"):
    return AutoHealEvent(
        timestamp=datetime.now(timezone.utc),
        container_id=container_id,
        container_name=container_id,
        event_type="restart",
        restart_count=1,
        status="success",
        message="container restarted",
    )


def test_configuration_changes_survive_a_fresh_manager(isolated_config_manager, monkeypatch):
    config = isolated_config_manager.get_config()
    config.monitor.interval_seconds = 45
    isolated_config_manager.update_config(config)

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()

    assert reloaded.get_config().monitor.interval_seconds == 45


def test_restart_counts_persist_and_can_be_cleared(isolated_config_manager, monkeypatch):
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()
    assert reloaded.get_restart_count("web", window_seconds=60) == 2

    reloaded.clear_restart_history("web")

    assert reloaded.get_total_restart_count("web") == 0


def test_quarantine_state_persists_and_can_be_removed(isolated_config_manager, monkeypatch):
    isolated_config_manager.quarantine_container("web")

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()
    assert reloaded.is_quarantined("web")
    assert reloaded.get_quarantined_containers() == {"web"}

    reloaded.unquarantine_container("web")

    assert not reloaded.is_quarantined("web")
    assert reloaded.get_quarantined_containers() == set()


def test_maintenance_mode_persists_and_can_be_disabled(isolated_config_manager, monkeypatch):
    isolated_config_manager.enable_maintenance_mode()
    started_at = isolated_config_manager.get_maintenance_start_time()

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()
    assert reloaded.is_maintenance_mode()
    assert reloaded.get_maintenance_start_time() == started_at

    reloaded.disable_maintenance_mode()

    assert not reloaded.is_maintenance_mode()
    assert reloaded.get_maintenance_start_time() is None


def test_custom_health_checks_persist_and_can_be_removed(isolated_config_manager, monkeypatch):
    health_check = HealthCheckConfig(
        container_id="web",
        check_type="http",
        http_endpoint="/healthz",
    )
    isolated_config_manager.add_custom_health_check(health_check)

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()
    assert reloaded.get_custom_health_check("web") == health_check
    assert reloaded.get_all_custom_health_checks() == {"web": health_check}

    reloaded.remove_custom_health_check("web")

    assert reloaded.get_custom_health_check("web") is None
    assert reloaded.get_all_custom_health_checks() == {}


def test_event_log_respects_configured_maximum(isolated_config_manager, update_config):
    def set_max_entries(config):
        config.ui.max_log_entries = 2

    update_config(set_max_entries)
    isolated_config_manager.add_event(_make_event("first"))
    isolated_config_manager.add_event(_make_event("second"))
    isolated_config_manager.add_event(_make_event("third"))

    assert [event.container_id for event in isolated_config_manager.get_events()] == [
        "second",
        "third",
    ]


def test_event_log_persists_across_a_fresh_manager(isolated_config_manager, monkeypatch):
    isolated_config_manager.add_event(_make_event("first"))
    isolated_config_manager.add_event(_make_event("second"))

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()

    assert [event.container_id for event in reloaded.get_events()] == [
        "first",
        "second",
    ]

    reloaded.clear_events()

    assert reloaded.get_events() == []


def test_export_and_import_round_trip_includes_custom_health_checks_and_restart_counts(
    isolated_config_manager, monkeypatch
):
    config = isolated_config_manager.get_config()
    config.monitor.interval_seconds = 45
    isolated_config_manager.update_config(config)
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")
    health_check = HealthCheckConfig(
        container_id="web",
        check_type="tcp",
        tcp_port=8080,
    )
    isolated_config_manager.add_custom_health_check(health_check)
    exported = isolated_config_manager.export_config()

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    imported = ConfigManager()
    imported.import_config(exported)

    assert imported.get_config().monitor.interval_seconds == 45
    assert imported.get_custom_health_check("web") == health_check
    assert imported.get_total_restart_count("web") == 2


def test_config_write_failure_is_logged_and_does_not_escape(isolated_config_manager, caplog):
    with patch("pathlib.Path.open", side_effect=OSError("disk full")):
        isolated_config_manager.update_config(isolated_config_manager.get_config())

    assert "Failed to save config to disk: disk full" in caplog.text


def test_events_write_failure_is_logged_and_does_not_escape(isolated_config_manager, caplog):
    with patch("pathlib.Path.open", side_effect=OSError("disk full")):
        isolated_config_manager.add_event(_make_event("web"))

    assert "Failed to save events to disk: disk full" in caplog.text


def test_quarantine_write_failure_is_logged_and_does_not_escape(isolated_config_manager, caplog):
    with patch("pathlib.Path.open", side_effect=OSError("disk full")):
        isolated_config_manager.quarantine_container("web")

    assert "Failed to save quarantine list to disk: disk full" in caplog.text


def test_maintenance_mode_write_failure_is_logged_and_does_not_escape(
    isolated_config_manager, caplog
):
    with patch("pathlib.Path.open", side_effect=OSError("disk full")):
        isolated_config_manager.enable_maintenance_mode()

    assert "Failed to save maintenance mode to disk: disk full" in caplog.text


def test_corrupt_auxiliary_state_falls_back_to_safe_defaults(
    isolated_config_manager, monkeypatch, caplog
):
    isolated_config_manager.QUARANTINE_FILE.write_text("not json")
    isolated_config_manager.MAINTENANCE_FILE.write_text("not json")

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()

    assert reloaded.get_quarantined_containers() == set()
    assert not reloaded.is_maintenance_mode()
    assert reloaded.get_maintenance_start_time() is None
    assert "Failed to load quarantine list from disk" in caplog.text
    assert "Failed to load maintenance mode from disk" in caplog.text
