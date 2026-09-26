"""Integration test for ConfigManager's real first-boot flow (issue #101).

A fresh deployment's config is defined twice, independently: once as a
hand-maintained dict in init_defaults.get_default_config(), and once as the
actual schema in AutoHealConfig's own Pydantic field defaults.
ConfigManager._load_config() reads the former back through the latter, but
nothing has ever exercised that round trip end-to-end - every other test
uses the isolated_config_manager fixture, which bypasses
__init__/_ensure_data_directory/initialize_defaults/_load_config entirely by
directly assigning `_config = AutoHealConfig()`.

This constructs a *real* ConfigManager() against a real (temporary, empty)
directory, letting __init__ run unmodified, to catch future drift between
the two independently-maintained definitions before it reaches a real
deployment's first boot.
"""

import json
from pathlib import Path

from app.config.config_manager import AutoHealConfig, ConfigManager
from app.config.init_defaults import get_default_config


def _redirect_manager_paths(monkeypatch, data_dir: Path) -> None:
    """Point every ConfigManager class-level data-file path at data_dir.

    monkeypatch.setattr on the class restores the originals automatically at
    the end of the test, so this doesn't need the manual try/finally restore
    isolated_config_manager (an autouse fixture covering the whole test
    suite) uses for the same class attributes.
    """
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


def test_first_boot_on_empty_data_dir_matches_autohealconfig_defaults(monkeypatch, tmp_path):
    """A real ConfigManager() constructed against a brand-new, empty data
    directory must produce exactly what a bare AutoHealConfig() would -
    proving get_default_config()'s hand-maintained dict and AutoHealConfig's
    own Pydantic defaults haven't drifted apart. If a future required field
    (or a renamed key) is added to one but not the other, this fails loudly
    instead of a real user's first boot silently absorbing the mismatch or
    crashing without warning."""
    _redirect_manager_paths(monkeypatch, tmp_path)

    manager = ConfigManager()

    assert manager.get_config() == AutoHealConfig()
    # initialize_defaults() wrote this file as a real side effect of
    # __init__, not something the test set up itself - confirm it exists.
    assert (tmp_path / "config.json").exists()


def test_get_default_config_dict_is_missing_notifications_key(monkeypatch, tmp_path):
    """Documents the actual drift this test module guards against: the
    hand-maintained dict has no 'notifications' key at all, even though
    AutoHealConfig.notifications is a real field. This is harmless today only
    because every AutoHealConfig field has a Pydantic default; the previous
    test is what actually proves ConfigManager's first-boot output is
    unaffected by that gap."""
    assert "notifications" not in get_default_config()


def test_first_boot_survives_config_json_missing_a_field(monkeypatch, tmp_path):
    """Realistic 'existing user upgrades to a new image version' path: an
    on-disk config.json from before a schema change is missing an entire
    section. ConfigManager() must still boot into a usable config with that
    section defaulted, rather than raising."""
    _redirect_manager_paths(monkeypatch, tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    old_config = get_default_config()
    assert "notifications" not in old_config
    # A non-default value here is essential to the test: monitor.interval_seconds
    # defaults to 30 in both get_default_config() and AutoHealConfig() itself, so
    # asserting against that shared value would pass even if loading silently
    # reset every section (including monitor) rather than genuinely preserving
    # what was on disk and only defaulting the missing one.
    old_config["monitor"]["interval_seconds"] = 999
    (tmp_path / "config.json").write_text(json.dumps(old_config))

    manager = ConfigManager()

    # Booted successfully, and the missing section fell back to its own
    # documented default rather than the whole config resetting or raising.
    assert manager.get_config().notifications == AutoHealConfig().notifications
    assert manager.get_config().monitor.interval_seconds == 999
