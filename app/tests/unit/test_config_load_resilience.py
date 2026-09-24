"""
Unit tests for ConfigManager._load_config()'s section-level failure handling.

Before this fix, any failure anywhere in AutoHealConfig(**data) - a single bad
field, section, or an unrecognized value - was caught by a blanket
except Exception and silently replaced the *entire* configuration with factory
defaults. This mirrors the per-record recovery _load_events() already does
for the events log (see test_events_persistence.py) but at the level of
AutoHealConfig's top-level sections: monitor, containers, restart, filters,
ui, alerts, observability, uptime_kuma, uptime_kuma_mappings, notifications.
"""

import json
from unittest.mock import patch

from app.config.config_manager import AutoHealConfig, ConfigManager


def _valid_config_dict() -> dict:
    """A full, valid config.json payload with every section customized away
    from its default, so a test can prove a section survived unchanged."""
    return {
        "monitor": {
            "interval_seconds": 45,
            "label_key": "custom-label",
            "label_value": "yes",
            "include_all": True,
        },
        "containers": {
            "selected": ["web"],
            "excluded": ["db"],
            "restart_counts": {"web": 2},
        },
        "restart": {
            "mode": "health",
            "cooldown_seconds": 90,
            "max_restarts": 5,
            "max_restarts_window_seconds": 900,
            "backoff": {"enabled": False, "initial_seconds": 20, "multiplier": 3.0},
            "respect_manual_stop": False,
        },
        "filters": {
            "whitelist_names": ["web-*"],
            "blacklist_names": ["db-*"],
            "whitelist_labels": [{"tier": "frontend"}],
            "blacklist_labels": [{"tier": "backend"}],
        },
        "ui": {
            "enable": True,
            "listen_address": "127.0.0.1",
            "listen_port": 4141,
            "allow_export_json": False,
            "allow_import_json": False,
            "max_log_entries": 200,
        },
        "alerts": {
            "enabled": True,
            "webhook": "https://example.com/hook",
            "notify_on_quarantine": False,
        },
        "observability": {
            "prometheus_enabled": False,
            "metrics_port": 9191,
            "log_format": "text",
            "log_level": "DEBUG",
        },
        "uptime_kuma": {
            "enabled": True,
            "server_url": "http://kuma:3001",
            "username": "admin",
            "api_token": "token",
            "auto_restart_on_down": False,
        },
        "uptime_kuma_mappings": [
            {
                "container_id": "web",
                "monitor_friendly_name": "Web Monitor",
                "auto_mapped": True,
            }
        ],
        "notifications": {
            "enabled": True,
            "services": [
                {"name": "discord-alerts", "type": "discord", "enabled": True}
            ],
            "event_filters": ["restart"],
        },
    }


def _write_config(manager, payload) -> None:
    manager.CONFIG_FILE.write_text(json.dumps(payload))


def test_fully_valid_config_loads_unchanged(isolated_config_manager):
    payload = _valid_config_dict()
    _write_config(isolated_config_manager, payload)

    config = isolated_config_manager._load_config()

    assert config.monitor.interval_seconds == 45
    assert config.containers.selected == ["web"]
    assert config.restart.mode == "health"
    assert config.restart.cooldown_seconds == 90
    assert config.filters.whitelist_names == ["web-*"]
    assert config.ui.listen_port == 4141
    assert config.alerts.webhook == "https://example.com/hook"
    assert config.observability.log_level == "DEBUG"
    assert config.uptime_kuma.server_url == "http://kuma:3001"
    assert len(config.uptime_kuma_mappings) == 1
    assert config.uptime_kuma_mappings[0].container_id == "web"
    assert config.notifications.services[0].name == "discord-alerts"


def test_single_invalid_section_only_resets_that_section(isolated_config_manager, caplog):
    payload = _valid_config_dict()
    # cooldown_seconds must be an int; this makes the whole 'restart' section fail.
    payload["restart"]["cooldown_seconds"] = "not-a-number"
    _write_config(isolated_config_manager, payload)

    config = isolated_config_manager._load_config()

    # The broken section falls back to its own defaults.
    default_restart = AutoHealConfig().restart
    assert config.restart == default_restart

    # Every other section is kept exactly as loaded from disk.
    assert config.monitor.interval_seconds == 45
    assert config.containers.selected == ["web"]
    assert config.filters.whitelist_names == ["web-*"]
    assert config.ui.listen_port == 4141
    assert config.alerts.webhook == "https://example.com/hook"
    assert config.observability.log_level == "DEBUG"
    assert config.uptime_kuma.server_url == "http://kuma:3001"
    assert len(config.uptime_kuma_mappings) == 1
    assert config.notifications.services[0].name == "discord-alerts"

    assert "Resetting config section 'restart' to defaults" in caplog.text


def test_multiple_invalid_sections_are_each_reset_independently(isolated_config_manager, caplog):
    payload = _valid_config_dict()
    payload["restart"]["cooldown_seconds"] = "not-a-number"
    payload["ui"]["listen_port"] = "not-a-port"
    payload["uptime_kuma_mappings"] = "not-a-list-of-mappings"
    _write_config(isolated_config_manager, payload)

    config = isolated_config_manager._load_config()

    defaults = AutoHealConfig()
    assert config.restart == defaults.restart
    assert config.ui == defaults.ui
    assert config.uptime_kuma_mappings == defaults.uptime_kuma_mappings

    # Sections that were valid remain untouched.
    assert config.monitor.interval_seconds == 45
    assert config.containers.selected == ["web"]
    assert config.filters.whitelist_names == ["web-*"]
    assert config.alerts.webhook == "https://example.com/hook"
    assert config.observability.log_level == "DEBUG"
    assert config.uptime_kuma.server_url == "http://kuma:3001"
    assert config.notifications.services[0].name == "discord-alerts"

    assert "Resetting config section 'restart' to defaults" in caplog.text
    assert "Resetting config section 'ui' to defaults" in caplog.text
    assert "Resetting config section 'uptime_kuma_mappings' to defaults" in caplog.text


def test_missing_config_file_returns_defaults(isolated_config_manager):
    assert not isolated_config_manager.CONFIG_FILE.exists()

    config = isolated_config_manager._load_config()

    assert config == AutoHealConfig()


def test_non_object_json_root_falls_back_to_full_defaults(isolated_config_manager, caplog):
    isolated_config_manager.CONFIG_FILE.write_text(json.dumps(["not", "an", "object"]))

    config = isolated_config_manager._load_config()

    assert config == AutoHealConfig()
    assert "did not contain a JSON object" in caplog.text


def test_unparseable_json_falls_back_to_full_defaults_without_raising(isolated_config_manager, caplog):
    isolated_config_manager.CONFIG_FILE.write_text("{not valid json at all")

    config = isolated_config_manager._load_config()

    assert config == AutoHealConfig()
    assert "not valid JSON" in caplog.text
    assert str(isolated_config_manager.CONFIG_FILE) in caplog.text


def test_config_file_open_failure_falls_back_to_full_defaults_without_raising(
    isolated_config_manager, caplog
):
    """_load_config() catches OSError as well as JSON/decode errors, so an
    I/O-level failure opening an otherwise-valid config.json (e.g. a
    permission error) must be handled the same way as malformed content:
    fall back to defaults rather than raising."""
    _write_config(isolated_config_manager, _valid_config_dict())

    with patch("pathlib.Path.open", side_effect=OSError("permission denied")):
        config = isolated_config_manager._load_config()

    assert config == AutoHealConfig()
    assert "is not valid JSON" in caplog.text
    assert "permission denied" in caplog.text


def test_invalid_utf8_config_file_falls_back_to_full_defaults_without_raising(
    isolated_config_manager, caplog
):
    """A config.json with bytes that can't even be decoded as text must not crash init."""
    isolated_config_manager.CONFIG_FILE.write_bytes(b"\xff\xfe\x00invalid-utf8")

    config = isolated_config_manager._load_config()

    assert config == AutoHealConfig()
    assert "not valid JSON" in caplog.text
    assert str(isolated_config_manager.CONFIG_FILE) in caplog.text


def test_broken_custom_health_check_does_not_reset_autoheal_config_sections(
    isolated_config_manager, caplog
):
    payload = _valid_config_dict()
    payload["custom_health_checks"] = {
        "web": {"container_id": "web"}  # missing required 'check_type'
    }
    _write_config(isolated_config_manager, payload)

    config = isolated_config_manager._load_config()

    assert isolated_config_manager._custom_health_checks == {}
    assert config.monitor.interval_seconds == 45
    assert config.restart.mode == "health"
    assert "Failed to load custom_health_checks from disk" in caplog.text


def test_invalid_autoheal_section_does_not_prevent_custom_health_checks_loading(
    isolated_config_manager,
):
    payload = _valid_config_dict()
    payload["restart"]["cooldown_seconds"] = "not-a-number"
    payload["custom_health_checks"] = {
        "web": {
            "container_id": "web",
            "check_type": "http",
            "http_endpoint": "/healthz",
        }
    }
    _write_config(isolated_config_manager, payload)

    config = isolated_config_manager._load_config()

    default_restart = AutoHealConfig().restart
    assert config.restart == default_restart
    assert "web" in isolated_config_manager._custom_health_checks
    assert isolated_config_manager._custom_health_checks["web"].check_type == "http"


def test_real_config_manager_init_retains_valid_sections_and_health_checks(
    monkeypatch, tmp_path
):
    """Exercise the actual __init__ lifecycle, not just _load_config() in
    isolation: _load_custom_health_checks() only returns whatever
    _load_config() already set on self, so a real construction is the only
    way to prove that hand-off survives a partially invalid config.json."""
    payload = _valid_config_dict()
    payload["restart"]["cooldown_seconds"] = "not-a-number"
    payload["custom_health_checks"] = {
        "web": {
            "container_id": "web",
            "check_type": "http",
            "http_endpoint": "/healthz",
        }
    }
    (tmp_path / "config.json").write_text(json.dumps(payload))

    monkeypatch.setattr(ConfigManager, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ConfigManager, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(ConfigManager, "EVENTS_FILE", tmp_path / "events.json")
    monkeypatch.setattr(ConfigManager, "RESTART_COUNTS_FILE", tmp_path / "restart_counts.json")
    monkeypatch.setattr(ConfigManager, "QUARANTINE_FILE", tmp_path / "quarantine.json")
    monkeypatch.setattr(ConfigManager, "MAINTENANCE_FILE", tmp_path / "maintenance.json")

    manager = ConfigManager()

    default_restart = AutoHealConfig().restart
    assert manager._config.restart == default_restart
    assert manager._config.monitor.interval_seconds == 45
    assert manager._config.containers.selected == ["web"]
    assert manager._config.filters.whitelist_names == ["web-*"]
    assert "web" in manager._custom_health_checks
    assert manager._custom_health_checks["web"].check_type == "http"
