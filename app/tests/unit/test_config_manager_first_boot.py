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
from typing import Type

import pytest
from pydantic import BaseModel

from app.config.config_manager import AutoHealConfig, ConfigManager
from app.config.init_defaults import get_default_config


def _assert_keys_match_model_fields(data: dict, model: Type[BaseModel], path: str) -> None:
    """Recursively assert data's keys exactly match model's fields, at every level.

    Pydantic v2's default `extra` behaviour is to silently ignore an unknown
    field, and a field that's simply absent falls back to its own default -
    neither raises. So AutoHealConfig(**sections) would quietly drop a
    typo'd/renamed/stray key in get_default_config(), or quietly paper over
    an omitted one, without the empty-dir equality test above necessarily
    catching it (it only compares the fully-constructed objects, so it
    can't distinguish "correctly defaulted" from "silently defaulted
    because the hand-maintained dict forgot this field"). Checking for
    exact key-set equality - not just "every present key is valid" - at
    every level, not only the top, is what makes this catch a missing or
    unknown *nested* field (e.g. notifications.enabled) too, not only a
    top-level section. Recurses into a nested dict whose corresponding
    field is itself a BaseModel (e.g. restart.backoff).
    """
    fields = model.model_fields
    data_keys = set(data.keys())
    field_keys = set(fields.keys())
    assert data_keys == field_keys, (
        f"{path} does not exactly match {model.__name__}'s fields - "
        f"missing: {sorted(field_keys - data_keys)}, unknown: {sorted(data_keys - field_keys)}"
    )
    for key, value in data.items():
        if isinstance(value, dict):
            field_type = fields[key].annotation
            if isinstance(field_type, type) and issubclass(field_type, BaseModel):
                _assert_keys_match_model_fields(value, field_type, f"{path}.{key}")


def _valid_top_level_config() -> dict:
    """get_default_config()'s current output, minus custom_health_checks
    (which is popped and parsed separately, never a field of AutoHealConfig
    itself) - a known-good baseline the meta-tests below deliberately
    corrupt in one specific way each, so each failure is isolated to the
    thing it's meant to prove the helper catches."""
    return {key: value for key, value in get_default_config().items() if key != "custom_health_checks"}


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


def test_get_default_config_keys_match_autohealconfig_schema():
    """Direct schema-parity check, catching drift in the direction the
    empty-dir equality test above cannot: a future typo, renamed key, stray
    extra key, or silently-omitted key in get_default_config() - at the top
    level or nested inside a section - would be silently papered over by
    AutoHealConfig(**sections) (Pydantic ignores unknown fields and defaults
    missing ones, neither raises), so that test would still pass even
    though the defaults dict no longer matches the real schema.
    custom_health_checks is deliberately excluded - it's popped and parsed
    separately before AutoHealConfig is ever constructed, not a field of
    AutoHealConfig itself."""
    _assert_keys_match_model_fields(_valid_top_level_config(), AutoHealConfig, "get_default_config()")


def test_schema_parity_helper_detects_an_unknown_top_level_key():
    """Proves the guard above actually fires on drift, rather than
    vacuously passing: an extra, unrecognized top-level key must be
    rejected."""
    data = _valid_top_level_config()
    data["monitorrr"] = {}

    with pytest.raises(AssertionError, match="monitorrr"):
        _assert_keys_match_model_fields(data, AutoHealConfig, "root")


def test_schema_parity_helper_detects_a_missing_top_level_key():
    """Proves the guard would have caught the actual bug this issue fixes:
    get_default_config() silently omitting an entire top-level section
    (notifications) that AutoHealConfig defines."""
    data = _valid_top_level_config()
    del data["notifications"]

    with pytest.raises(AssertionError, match="notifications"):
        _assert_keys_match_model_fields(data, AutoHealConfig, "root")


def test_schema_parity_helper_detects_an_unknown_nested_key():
    """A misspelled/extra key nested inside a section (not just at the top
    level) must also be rejected."""
    data = _valid_top_level_config()
    data["monitor"] = {**data["monitor"], "interval_secondz": 30}

    with pytest.raises(AssertionError, match="interval_secondz"):
        _assert_keys_match_model_fields(data, AutoHealConfig, "root")


def test_schema_parity_helper_detects_a_missing_nested_key():
    """The nested counterpart to the missing-top-level-key test above: a
    section present but missing one of its own fields (e.g.
    notifications.enabled) must be rejected too - the original version of
    this helper only checked that *present* nested keys were valid, which
    would have missed this direction of drift entirely."""
    data = _valid_top_level_config()
    data["notifications"] = {key: value for key, value in data["notifications"].items() if key != "enabled"}

    with pytest.raises(AssertionError, match="enabled"):
        _assert_keys_match_model_fields(data, AutoHealConfig, "root")


def test_first_boot_survives_config_json_missing_a_field(monkeypatch, tmp_path):
    """Realistic 'existing user upgrades to a new image version' path: an
    on-disk config.json from before a schema change is missing an entire
    section. ConfigManager() must still boot into a usable config with that
    section defaulted, rather than raising."""
    _redirect_manager_paths(monkeypatch, tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    old_config = get_default_config()
    # Simulates an on-disk config.json predating a schema change - not
    # get_default_config()'s own current output, which (as of this fix) has
    # no such gap. AutoHealConfig().notifications is the section's real
    # documented default, so removing it here (rather than adding some other
    # field) exercises the exact fallback the earlier schema-drift bug
    # relied on this test to protect against.
    del old_config["notifications"]
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


def test_first_boot_ignores_an_unknown_extra_top_level_section(monkeypatch, tmp_path):
    """The reverse of the missing-section case above: an on-disk config.json
    with a stray top-level section AutoHealConfig doesn't define (e.g. left
    over from a removed feature, or hand-edited) must be silently ignored
    rather than raising - _build_config_from_sections() only ever reads keys
    it recognizes out of the raw data, so an unrecognized key is never
    passed to any model constructor in the first place."""
    _redirect_manager_paths(monkeypatch, tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    new_config = get_default_config()
    new_config["totally_unknown_section"] = {"foo": "bar"}
    new_config["monitor"]["interval_seconds"] = 999
    (tmp_path / "config.json").write_text(json.dumps(new_config))

    manager = ConfigManager()

    assert manager.get_config().monitor.interval_seconds == 999
    assert not hasattr(manager.get_config(), "totally_unknown_section")
