"""Tests for ConfigManager state transitions and persisted round trips."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from app.config.config_manager import (
    AutoHealEvent,
    ConfigManager,
    HealthCheckConfig,
    NotificationService,
    UptimeKumaMapping,
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


def test_restart_count_ignores_window_seconds_and_never_expires(isolated_config_manager):
    """get_restart_count() accepts a window_seconds argument for API
    compatibility, but the underlying counter (config.containers.restart_counts)
    has no timestamp component, so it is never actually filtered by window or
    by elapsed time: record_restart()/clear_restart_history() are the only
    ways a count changes."""
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")

    # A window far too small to contain three real restarts still returns the
    # full total, because no time-based filtering is actually applied.
    assert isolated_config_manager.get_restart_count("web", window_seconds=1) == 3
    # A huge window returns the same total, confirming window_seconds has no effect.
    assert isolated_config_manager.get_restart_count("web", window_seconds=10_000_000) == 3


def test_cleanup_restart_counts_is_a_no_op_that_preserves_all_entries(isolated_config_manager):
    """cleanup_restart_counts() is documented in its own code comment as
    disabled ('DISABLED to preserve manual entries'), so restart counts for
    containers absent from active_container_ids must survive the call
    unchanged, not be pruned as the method name might suggest."""
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("gone")

    isolated_config_manager.cleanup_restart_counts(active_container_ids=["web"])

    assert isolated_config_manager.get_total_restart_count("web") == 1
    assert isolated_config_manager.get_total_restart_count("gone") == 1


def test_fresh_manager_reports_empty_state_for_every_tracked_area(isolated_config_manager):
    """A manager that has never persisted anything must report the documented
    empty/missing defaults for every stateful area this PR covers."""
    assert isolated_config_manager.get_events() == []
    assert isolated_config_manager.get_events(limit=10) == []
    assert isolated_config_manager.get_restart_count("web", window_seconds=60) == 0
    assert isolated_config_manager.get_total_restart_count("web") == 0
    assert not isolated_config_manager.is_quarantined("web")
    assert isolated_config_manager.get_quarantined_containers() == set()
    assert not isolated_config_manager.is_maintenance_mode()
    assert isolated_config_manager.get_maintenance_start_time() is None
    assert isolated_config_manager.get_custom_health_check("web") is None
    assert isolated_config_manager.get_all_custom_health_checks() == {}


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


def test_export_and_import_round_trip_reproduces_full_config_state(
    isolated_config_manager, monkeypatch, tmp_path
):
    """export_config() dumps the whole AutoHealConfig (every top-level
    section) plus custom_health_checks; this exercises a representative
    slice of every section it actually owns, not just one or two fields.
    Quarantine, maintenance mode and the event log are intentionally left
    unasserted here: export_config() does not include them (they live in
    their own files), so asserting their survival would invent behavior the
    implementation doesn't have."""
    config = isolated_config_manager.get_config()
    config.monitor.interval_seconds = 45
    config.containers.selected = ["web"]
    config.containers.excluded = ["db"]
    config.filters.whitelist_names = ["web-*"]
    config.ui.max_log_entries = 200
    config.alerts.webhook = "https://example.com/hook"
    config.notifications.enabled = True
    config.notifications.services = [
        NotificationService(name="discord-alerts", type="discord", enabled=True)
    ]
    config.uptime_kuma.enabled = True
    config.uptime_kuma.server_url = "http://kuma:3001"
    config.uptime_kuma_mappings = [
        UptimeKumaMapping(container_id="web", monitor_friendly_name="Web Monitor")
    ]
    isolated_config_manager.update_config(config)
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")
    http_check = HealthCheckConfig(
        container_id="web",
        check_type="http",
        http_endpoint="/healthz",
    )
    tcp_check = HealthCheckConfig(
        container_id="db",
        check_type="tcp",
        tcp_port=8080,
    )
    isolated_config_manager.add_custom_health_check(http_check)
    isolated_config_manager.add_custom_health_check(tcp_check)
    exported = isolated_config_manager.export_config()

    # A separate, empty data directory ensures the assertions below can only
    # pass if import_config() actually restored this state, not because
    # ConfigManager() loaded it from disk on init.
    _redirect_manager_paths(monkeypatch, tmp_path)
    imported = ConfigManager()
    imported.import_config(exported)

    imported_config = imported.get_config()
    assert imported_config.monitor.interval_seconds == 45
    assert imported_config.containers.selected == ["web"]
    assert imported_config.containers.excluded == ["db"]
    assert imported_config.filters.whitelist_names == ["web-*"]
    assert imported_config.ui.max_log_entries == 200
    assert imported_config.alerts.webhook == "https://example.com/hook"
    assert imported_config.notifications.enabled is True
    assert imported_config.notifications.services[0].name == "discord-alerts"
    assert imported_config.uptime_kuma.server_url == "http://kuma:3001"
    assert imported_config.uptime_kuma_mappings[0].container_id == "web"
    assert imported.get_custom_health_check("web") == http_check
    assert imported.get_custom_health_check("db") == tcp_check
    assert imported.get_all_custom_health_checks() == {"web": http_check, "db": tcp_check}
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


def test_quarantine_file_with_non_iterable_json_falls_back_to_empty_set(
    isolated_config_manager, monkeypatch, caplog
):
    """Distinct from the syntactically-invalid-JSON case above: this content
    parses as valid JSON but is not a list/iterable of container ids, so
    set(data) itself raises inside the same try/except and the manager falls
    back to the documented empty-set default."""
    isolated_config_manager.QUARANTINE_FILE.write_text(json.dumps(42))

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()

    assert reloaded.get_quarantined_containers() == set()
    assert "Failed to load quarantine list from disk" in caplog.text
