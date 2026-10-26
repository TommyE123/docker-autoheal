"""Tests for ConfigManager state transitions and persisted round trips."""

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config.config_manager import (
    AutoHealEvent,
    ConfigManager,
    HealthCheckConfig,
    MonitorConfig,
    NotificationService,
    UptimeKumaMapping,
    config_manager,
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
        timestamp=datetime.now(UTC),
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


@pytest.fixture
def clock(monkeypatch):
    """Controllable replacement for the time source used for restart timestamps."""
    now = [1_000_000.0]
    monkeypatch.setattr("app.config.config_manager.time.time", lambda: now[0])
    return now


def test_restart_inside_the_window_counts(isolated_config_manager, clock):
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")
    clock[0] += 59

    assert isolated_config_manager.get_restart_count("web", window_seconds=60) == 2


def test_restart_outside_the_window_does_not_count(isolated_config_manager, clock):
    isolated_config_manager.record_restart("web")
    clock[0] += 61

    assert isolated_config_manager.get_restart_count("web", window_seconds=60) == 0


def test_restart_exactly_window_seconds_old_has_expired(isolated_config_manager, clock):
    isolated_config_manager.record_restart("web")
    clock[0] += 60

    assert isolated_config_manager.get_restart_count("web", window_seconds=60) == 0


def test_window_counts_only_the_recent_restarts_among_old_ones(isolated_config_manager, clock):
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")
    clock[0] += 500
    isolated_config_manager.record_restart("web")
    clock[0] += 100

    assert isolated_config_manager.get_restart_count("web", window_seconds=200) == 1
    # The lifetime total used for display is unaffected by the window
    assert isolated_config_manager.get_total_restart_count("web") == 3


def test_record_restart_prunes_history_older_than_the_window(isolated_config_manager, clock):
    isolated_config_manager.record_restart("web", window_seconds=60)
    clock[0] += 100
    isolated_config_manager.record_restart("web", window_seconds=60)

    history = isolated_config_manager.get_config().containers.restart_history["web"]
    assert history == [clock[0]]
    assert isolated_config_manager.get_total_restart_count("web") == 2


def test_counts_without_history_never_count_towards_the_window(
    isolated_config_manager, monkeypatch
):
    """Counts saved before timestamps were tracked (no restart_history) are treated
    as expired, so upgrading cannot quarantine a container for old restarts."""
    data_dir = isolated_config_manager.DATA_DIR
    (data_dir / "config.json").write_text(
        json.dumps({"containers": {"restart_counts": {"web": 5}}})
    )

    _redirect_manager_paths(monkeypatch, data_dir)
    upgraded = ConfigManager()

    assert upgraded.get_restart_count("web", window_seconds=10_000_000) == 0
    assert upgraded.get_total_restart_count("web") == 5


def test_restart_history_persists_and_is_cleared_with_the_count(
    isolated_config_manager, monkeypatch
):
    isolated_config_manager.record_restart("web")

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()
    assert reloaded.get_restart_count("web", window_seconds=60) == 1

    reloaded.clear_restart_history("web")
    assert reloaded.get_restart_count("web", window_seconds=60) == 0
    assert "web" not in reloaded.get_config().containers.restart_history


def test_fresh_manager_reports_empty_state_for_every_tracked_area(
    isolated_config_manager, monkeypatch, tmp_path
):
    """A manager that has never persisted anything must report the documented
    empty/missing defaults for every stateful area this PR covers.

    Uses a genuinely fresh ConfigManager() pointed at an empty directory
    rather than the isolated_config_manager fixture's singleton directly:
    the fixture pre-empties that singleton's in-memory state itself, so
    asserting against it would pass even if a newly constructed
    ConfigManager loaded incorrect defaults.
    """
    _redirect_manager_paths(monkeypatch, tmp_path)
    fresh = ConfigManager()

    assert fresh.get_events() == []
    assert fresh.get_events(limit=10) == []
    assert fresh.get_restart_count("web", window_seconds=60) == 0
    assert fresh.get_total_restart_count("web") == 0
    assert not fresh.is_quarantined("web")
    assert fresh.get_quarantined_containers() == set()
    assert not fresh.is_maintenance_mode()
    assert fresh.get_maintenance_start_time() is None
    assert fresh.get_custom_health_check("web") is None
    assert fresh.get_all_custom_health_checks() == {}


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
    config.restart.max_restarts = 7
    config.filters.whitelist_names = ["web-*"]
    config.ui.max_log_entries = 200
    config.alerts.webhook = "https://example.com/hook"
    config.observability.log_level = "DEBUG"
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
    assert imported_config.restart.max_restarts == 7
    assert imported_config.filters.whitelist_names == ["web-*"]
    assert imported_config.ui.max_log_entries == 200
    assert imported_config.alerts.webhook == "https://example.com/hook"
    assert imported_config.observability.log_level == "DEBUG"
    assert imported_config.notifications.enabled is True
    assert imported_config.notifications.services[0].name == "discord-alerts"
    assert imported_config.uptime_kuma.server_url == "http://kuma:3001"
    assert imported_config.uptime_kuma_mappings[0].container_id == "web"
    assert imported.get_custom_health_check("web") == http_check
    assert imported.get_custom_health_check("db") == tcp_check
    assert imported.get_all_custom_health_checks() == {
        "web": http_check,
        "db": tcp_check,
    }
    assert imported.get_total_restart_count("web") == 2


def test_import_config_with_invalid_custom_health_check_leaves_state_unchanged(
    isolated_config_manager,
):
    """A valid main config paired with an invalid custom_health_checks entry
    (missing the required container_id) must leave both the live config and
    the custom health checks completely untouched, and nothing persisted to
    disk - mirroring the already-covered invalid-main-config case."""
    isolated_config_manager.get_config().monitor.interval_seconds = 30
    original_interval = isolated_config_manager.get_config().monitor.interval_seconds
    http_check = HealthCheckConfig(container_id="web", check_type="http", http_endpoint="/healthz")
    isolated_config_manager.add_custom_health_check(http_check)
    original_custom_checks = isolated_config_manager.get_all_custom_health_checks()

    valid_config_dict = isolated_config_manager.get_config().model_dump()
    valid_config_dict["monitor"]["interval_seconds"] = 999
    payload = json.dumps(
        {
            **valid_config_dict,
            "custom_health_checks": {"bad": {"check_type": "http"}},
        },
        default=str,
    )

    with pytest.raises(ValidationError):
        isolated_config_manager.import_config(payload)

    assert isolated_config_manager.get_config().monitor.interval_seconds == original_interval
    assert isolated_config_manager.get_all_custom_health_checks() == original_custom_checks
    saved = json.loads(isolated_config_manager.CONFIG_FILE.read_text())
    assert saved["monitor"]["interval_seconds"] == original_interval


def test_config_write_failure_is_logged_and_does_not_escape(isolated_config_manager, caplog):
    with patch("os.open", side_effect=OSError("disk full")):
        isolated_config_manager.update_config(isolated_config_manager.get_config())

    assert "Failed to save config to disk: disk full" in caplog.text


def test_events_write_failure_is_logged_and_does_not_escape(isolated_config_manager, caplog):
    with patch("os.open", side_effect=OSError("disk full")):
        isolated_config_manager.add_event(_make_event("web"))

    assert "Failed to save events to disk: disk full" in caplog.text


def test_quarantine_write_failure_is_logged_and_does_not_escape(isolated_config_manager, caplog):
    with patch("os.open", side_effect=OSError("disk full")):
        isolated_config_manager.quarantine_container("web")

    assert "Failed to save quarantine list to disk: disk full" in caplog.text


def test_maintenance_mode_write_failure_is_logged_and_does_not_escape(
    isolated_config_manager, caplog
):
    with patch("os.open", side_effect=OSError("disk full")):
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


def test_maintenance_mode_with_corrupt_start_time_falls_back_to_safe_defaults(
    isolated_config_manager, monkeypatch, caplog
):
    """Distinct from the syntactically-invalid-JSON case above: this content
    is valid JSON with enabled=True, but start_time is not a parseable ISO
    datetime, so datetime.fromisoformat() raises inside the same try/except.
    The whole load must fall back to the safe False/None defaults rather than
    leaving _maintenance_mode set to the partially-read enabled value."""
    isolated_config_manager.MAINTENANCE_FILE.write_text(
        json.dumps({"enabled": True, "start_time": "not-a-real-date"})
    )

    _redirect_manager_paths(monkeypatch, isolated_config_manager.DATA_DIR)
    reloaded = ConfigManager()

    assert not reloaded.is_maintenance_mode()
    assert reloaded.get_maintenance_start_time() is None
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


def test_update_partial_config_applies_valid_values_and_ignores_unknown_keys(
    isolated_config_manager,
):
    isolated_config_manager.update_partial_config(monitor={"interval_seconds": 42}, not_a_section=1)

    assert isolated_config_manager.get_config().monitor.interval_seconds == 42


def test_update_partial_config_keeps_omitted_fields_of_a_partial_section(
    isolated_config_manager,
):
    isolated_config_manager.update_partial_config(monitor={"label_key": "custom.label"})
    isolated_config_manager.update_partial_config(monitor={"interval_seconds": 42})

    monitor = isolated_config_manager.get_config().monitor
    assert monitor.interval_seconds == 42
    assert monitor.label_key == "custom.label"


def test_update_partial_config_keeps_omitted_fields_of_nested_sections(isolated_config_manager):
    isolated_config_manager.update_partial_config(restart={"backoff": {"initial_seconds": 20}})

    isolated_config_manager.update_partial_config(restart={"backoff": {"multiplier": 3.0}})

    backoff = isolated_config_manager.get_config().restart.backoff
    assert backoff.initial_seconds == 20
    assert backoff.multiplier == 3.0


def test_update_partial_config_replaces_a_section_given_a_model(isolated_config_manager):
    isolated_config_manager.update_partial_config(monitor={"label_key": "custom.label"})

    isolated_config_manager.update_partial_config(monitor=MonitorConfig(interval_seconds=7))

    monitor = isolated_config_manager.get_config().monitor
    assert monitor.interval_seconds == 7
    assert monitor.label_key == "autoheal"


def test_update_partial_config_rejects_invalid_values_without_changing_config(
    isolated_config_manager,
):
    before = isolated_config_manager.get_config().model_dump()

    with pytest.raises(ValidationError):
        isolated_config_manager.update_partial_config(monitor={"interval_seconds": "bad"})

    assert isolated_config_manager.get_config().model_dump() == before


def test_record_restart_prune_keeps_only_restarts_strictly_inside_the_window(
    isolated_config_manager, clock
):
    isolated_config_manager.record_restart("web", window_seconds=60)
    clock[0] += 60
    isolated_config_manager.record_restart("web", window_seconds=60)

    history = isolated_config_manager.get_config().containers.restart_history["web"]
    assert history == [clock[0]]


@pytest.mark.parametrize(
    ("counts", "history", "saves"),
    [
        ({}, {}, False),
        ({"web": 2}, {}, True),
        ({}, {"web": [1.0]}, True),
        ({"web": 2}, {"web": [1.0]}, True),
    ],
)
def test_clear_restart_history_saves_only_when_something_was_removed(
    isolated_config_manager, counts, history, saves
):
    isolated_config_manager._config.containers.restart_counts.update(counts)
    isolated_config_manager._config.containers.restart_history.update(history)

    with patch.object(isolated_config_manager, "_save_config") as save:
        isolated_config_manager.clear_restart_history("web")

    assert save.called is saves
    assert isolated_config_manager.get_total_restart_count("web") == 0
    assert isolated_config_manager.get_restart_count("web", window_seconds=60) == 0


def test_update_config_keeps_restarts_recorded_after_get_config(
    isolated_config_manager, monkeypatch
):
    """A config copy taken before a restart was recorded must not undo the restart
    when it is written back, in memory or on disk (#436)."""
    stale = isolated_config_manager.get_config()
    isolated_config_manager.record_restart("web")
    isolated_config_manager.record_restart("web")
    live = isolated_config_manager.get_config().containers
    stale.monitor.interval_seconds = 45

    isolated_config_manager.update_config(stale)

    for manager in (isolated_config_manager, _reloaded(monkeypatch, isolated_config_manager)):
        config = manager.get_config()
        assert config.monitor.interval_seconds == 45
        assert config.containers.restart_counts == {"web": 2}
        assert config.containers.restart_history == live.restart_history
        assert len(config.containers.restart_history["web"]) == 2


def test_update_config_does_not_restore_a_cleared_restart_history(
    isolated_config_manager, monkeypatch
):
    isolated_config_manager.record_restart("web")
    stale = isolated_config_manager.get_config()
    isolated_config_manager.clear_restart_history("web")

    isolated_config_manager.update_config(stale)

    for manager in (isolated_config_manager, _reloaded(monkeypatch, isolated_config_manager)):
        containers = manager.get_config().containers
        assert containers.restart_counts == {}
        assert containers.restart_history == {}


def test_update_config_does_not_alias_the_callers_config(isolated_config_manager):
    config = isolated_config_manager.get_config()
    isolated_config_manager.update_config(config)

    config.monitor.interval_seconds = 99

    assert isolated_config_manager.get_config().monitor.interval_seconds != 99


def test_import_config_replaces_restart_state(isolated_config_manager):
    isolated_config_manager.record_restart("web")
    payload = isolated_config_manager.get_config().model_dump()
    payload["containers"]["restart_counts"] = {"db": 3}
    payload["containers"]["restart_history"] = {"db": [1.0]}

    isolated_config_manager.import_config(json.dumps(payload))

    containers = isolated_config_manager.get_config().containers
    assert containers.restart_counts == {"db": 3}
    assert containers.restart_history == {"db": [1.0]}


def test_mutate_applies_and_saves_the_change(isolated_config_manager, monkeypatch):
    with isolated_config_manager.mutate() as config:
        config.monitor.interval_seconds = 12
        config.containers.selected.append("web")

    reloaded = _reloaded(monkeypatch, isolated_config_manager)
    for manager in (isolated_config_manager, reloaded):
        assert manager.get_config().monitor.interval_seconds == 12
        assert manager.get_config().containers.selected == ["web"]


def test_mutate_rolls_back_when_the_block_raises(isolated_config_manager):
    isolated_config_manager.update_config(isolated_config_manager.get_config())
    live = isolated_config_manager._config
    before = live.model_dump()
    saved_before = isolated_config_manager.CONFIG_FILE.read_bytes()

    def fail_after_changing(config):
        config.monitor.interval_seconds = 12
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"), isolated_config_manager.mutate() as config:
        fail_after_changing(config)

    assert isolated_config_manager._config is live
    assert isolated_config_manager.get_config().model_dump() == before
    assert isolated_config_manager.CONFIG_FILE.read_bytes() == saved_before


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")
def test_mutate_succeeds_after_update_config_stored_an_invalid_value(isolated_config_manager):
    stale = isolated_config_manager.get_config()
    stale.observability.prometheus_enabled = "maybe"
    isolated_config_manager.update_config(stale)

    with isolated_config_manager.mutate() as config:
        config.containers.selected.append("web")

    assert isolated_config_manager.get_config().containers.selected == ["web"]


def test_mutate_does_not_alias_the_yielded_config_to_the_live_one(isolated_config_manager):
    with isolated_config_manager.mutate() as config:
        config.containers.selected.append("web")

    config.containers.selected.append("leaked")

    assert isolated_config_manager.get_config().containers.selected == ["web"]


@pytest.mark.parametrize(("change", "saves"), [(False, False), (True, True)])
def test_mutate_saves_only_when_the_config_changed(isolated_config_manager, change, saves):
    with (
        patch.object(isolated_config_manager, "_save_config") as save,
        isolated_config_manager.mutate() as config,
    ):
        if change:
            config.monitor.interval_seconds = 12

    assert save.called is saves


def test_mutate_keeps_restart_state_recorded_before_and_during_the_block(
    isolated_config_manager, monkeypatch
):
    isolated_config_manager.record_restart("web")
    with isolated_config_manager.mutate() as config:
        isolated_config_manager.record_restart("db")
        config.monitor.interval_seconds = 12

    for manager in (isolated_config_manager, _reloaded(monkeypatch, isolated_config_manager)):
        containers = manager.get_config().containers
        assert containers.restart_counts == {"web": 1, "db": 1}
        assert set(containers.restart_history) == {"web", "db"}


def test_mutate_ignores_restart_state_edited_in_the_block(isolated_config_manager):
    isolated_config_manager.record_restart("web")
    live = isolated_config_manager.get_config().containers

    with isolated_config_manager.mutate() as config:
        config.containers.restart_counts = {"fake": 9}
        config.containers.restart_history = {"fake": [1.0]}

    containers = isolated_config_manager.get_config().containers
    assert containers.restart_counts == live.restart_counts == {"web": 1}
    assert containers.restart_history == live.restart_history


def _reloaded(monkeypatch, manager):
    """Return a fresh ConfigManager reading ``manager``'s data directory from disk."""
    _redirect_manager_paths(monkeypatch, manager.DATA_DIR)
    return ConfigManager()


def test_loaders_return_empty_state_when_their_files_are_missing():
    """With nothing on disk, events and quarantine are empty and maintenance stays off."""
    assert not config_manager.EVENTS_FILE.exists()
    assert not config_manager.QUARANTINE_FILE.exists()
    assert not config_manager.MAINTENANCE_FILE.exists()

    config_manager._load_maintenance_mode()

    assert config_manager._load_events() == []
    assert config_manager._load_quarantine() == set()
    assert config_manager._maintenance_mode is False
    assert config_manager._maintenance_start_time is None
