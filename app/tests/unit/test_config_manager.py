"""
Unit tests for ConfigManager: persistence error handling, custom health
checks, restart counts, and maintenance mode. Basic get/update/events
behaviour is already covered by test_events_persistence.py and the
restart/quarantine tests exercised through test_container_recreation.py.
"""

from datetime import datetime, timezone

import pytest

from app.config.config_manager import HealthCheckConfig


def test_load_config_falls_back_to_defaults_on_corrupt_file(isolated_config_manager):
    isolated_config_manager.CONFIG_FILE.write_text("not valid json")

    config = isolated_config_manager._load_config()

    assert config.monitor.interval_seconds == 30  # the documented default


def test_save_config_error_is_logged_not_raised(isolated_config_manager, monkeypatch):
    monkeypatch.setattr(
        "builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )

    isolated_config_manager._save_config()  # must not raise


def test_load_events_falls_back_to_empty_list_on_corrupt_file(isolated_config_manager):
    isolated_config_manager.EVENTS_FILE.write_text("not valid json")

    assert isolated_config_manager._load_events() == []


def test_load_quarantine_falls_back_to_empty_set_on_corrupt_file(isolated_config_manager):
    isolated_config_manager.QUARANTINE_FILE.write_text("not valid json")

    assert isolated_config_manager._load_quarantine() == set()


@pytest.mark.parametrize(
    "method_name",
    ["_save_events", "_save_quarantine", "_save_maintenance_mode"],
)
def test_save_methods_log_errors_instead_of_raising(isolated_config_manager, monkeypatch, method_name):
    monkeypatch.setattr(
        "builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )

    getattr(isolated_config_manager, method_name)()  # must not raise


def test_add_event_trims_the_log_to_max_entries(isolated_config_manager):
    config = isolated_config_manager.get_config()
    config.ui.max_log_entries = 3
    isolated_config_manager.update_config(config)

    for i in range(5):
        isolated_config_manager.add_event(
            _make_event(f"container-{i}")
        )

    events = isolated_config_manager.get_events()
    assert len(events) == 3
    assert [e.container_id for e in events] == ["container-2", "container-3", "container-4"]


def test_custom_health_check_round_trip(isolated_config_manager):
    check = HealthCheckConfig(container_id="web", check_type="http", http_endpoint="http://localhost/health")

    isolated_config_manager.add_custom_health_check(check)
    assert isolated_config_manager.get_custom_health_check("web") == check
    assert isolated_config_manager.get_all_custom_health_checks() == {"web": check}

    isolated_config_manager.remove_custom_health_check("web")
    assert isolated_config_manager.get_custom_health_check("web") is None


def test_restart_counts_are_tracked_per_container(isolated_config_manager):
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("db")

    assert isolated_config_manager.get_restart_count("web", window_seconds=600) == 2
    assert isolated_config_manager.get_total_restart_count("web") == 2
    assert isolated_config_manager.get_total_restart_count("db") == 1

    isolated_config_manager.clear_restart_history("web")
    assert isolated_config_manager.get_total_restart_count("web") == 0


def test_quarantine_round_trip(isolated_config_manager):
    isolated_config_manager.quarantine_container("web")
    assert isolated_config_manager.is_quarantined("web") is True
    assert isolated_config_manager.get_quarantined_containers() == {"web"}

    isolated_config_manager.unquarantine_container("web")
    assert isolated_config_manager.is_quarantined("web") is False


def test_maintenance_mode_round_trip(isolated_config_manager):
    assert isolated_config_manager.is_maintenance_mode() is False
    assert isolated_config_manager.get_maintenance_start_time() is None

    isolated_config_manager.enable_maintenance_mode()
    assert isolated_config_manager.is_maintenance_mode() is True
    assert isolated_config_manager.get_maintenance_start_time() is not None

    isolated_config_manager.disable_maintenance_mode()
    assert isolated_config_manager.is_maintenance_mode() is False
    assert isolated_config_manager.get_maintenance_start_time() is None


def test_maintenance_mode_persists_across_reload(isolated_config_manager):
    isolated_config_manager.enable_maintenance_mode()

    isolated_config_manager._load_maintenance_mode()

    assert isolated_config_manager.is_maintenance_mode() is True
    assert isolated_config_manager.get_maintenance_start_time() is not None


def test_update_partial_config_only_touches_known_fields(isolated_config_manager):
    from app.config.config_manager import MonitorConfig

    isolated_config_manager.update_partial_config(
        monitor=MonitorConfig(interval_seconds=99), unknown_field="ignored"
    )

    assert isolated_config_manager.get_config().monitor.interval_seconds == 99


def test_ensure_data_directory_falls_back_when_not_writable(isolated_config_manager, monkeypatch, tmp_path):
    from pathlib import Path

    real_mkdir = Path.mkdir

    def _mkdir_fails_once(self, *args, **kwargs):
        monkeypatch.setattr(Path, "mkdir", real_mkdir)
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", _mkdir_fails_once)
    monkeypatch.chdir(tmp_path)

    isolated_config_manager._ensure_data_directory()

    assert isolated_config_manager.DATA_DIR == Path("./data")
    assert isolated_config_manager.CONFIG_FILE == Path("./data/config.json")


def test_export_import_config_round_trip(isolated_config_manager):
    check = HealthCheckConfig(container_id="web", check_type="tcp", tcp_port=8080)
    isolated_config_manager.add_custom_health_check(check)

    exported = isolated_config_manager.export_config()
    isolated_config_manager.import_config(exported)

    assert isolated_config_manager.get_all_custom_health_checks() == {"web": check}


def _make_event(container_id: str):
    from app.config.config_manager import AutoHealEvent

    return AutoHealEvent(
        timestamp=datetime.now(timezone.utc),
        container_id=container_id,
        container_name=container_id,
        event_type="restart",
        restart_count=1,
        status="success",
        message="test event",
    )
