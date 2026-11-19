"""AUTOHEAL_DATA_DIR overrides where ConfigManager stores its state."""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import config_manager as config_manager_module
from app.config.config_manager import DATA_DIR_ENV, ConfigManager

_FILES = (
    "CONFIG_FILE",
    "EVENTS_FILE",
    "RESTART_COUNTS_FILE",
    "QUARANTINE_FILE",
    "MAINTENANCE_FILE",
)


@pytest.fixture
def data_dir_default(tmp_path, monkeypatch):
    """Make the class default a temp directory, standing in for the real /data."""
    default = tmp_path / "default"
    for attribute, name in zip(
        _FILES,
        (
            "config.json",
            "events.json",
            "restart_counts.json",
            "quarantine.json",
            "maintenance.json",
        ),
        strict=True,
    ):
        monkeypatch.setattr(ConfigManager, attribute, default / name)
    monkeypatch.setattr(ConfigManager, "DATA_DIR", default)
    return default


def test_class_default_is_still_data():
    assert Path("/data") == ConfigManager.DATA_DIR
    assert DATA_DIR_ENV == "AUTOHEAL_DATA_DIR"


def test_without_override_the_default_directory_is_used(data_dir_default, monkeypatch):
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)

    manager = ConfigManager()

    assert data_dir_default == manager.DATA_DIR
    assert data_dir_default / "config.json" == manager.CONFIG_FILE
    assert (data_dir_default / "config.json").exists()


def test_override_moves_every_state_file(data_dir_default, tmp_path, monkeypatch, caplog):
    override = tmp_path / "custom"
    monkeypatch.setenv(DATA_DIR_ENV, str(override))

    with caplog.at_level(logging.INFO, logger=config_manager_module.logger.name):
        manager = ConfigManager()

    assert f"persistent storage at {override}" in caplog.text
    assert override == manager.DATA_DIR
    for attribute in _FILES:
        assert getattr(manager, attribute).parent == override
    assert (override / "config.json").exists()
    assert not data_dir_default.exists()


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_override_is_ignored(data_dir_default, monkeypatch, value):
    monkeypatch.setenv(DATA_DIR_ENV, value)

    assert data_dir_default == ConfigManager().DATA_DIR


def test_override_is_applied_before_any_disk_access(data_dir_default, tmp_path, monkeypatch):
    override = tmp_path / "custom"
    monkeypatch.setenv(DATA_DIR_ENV, str(override))
    seen: list[Path] = []
    real_mkdir = Path.mkdir

    def recording_mkdir(self, *args, **kwargs):
        seen.append(self)
        return real_mkdir(self, *args, **kwargs)

    def recording_remove(directory):
        seen.append(Path(directory))

    def recording_defaults(directory):
        seen.append(Path(directory))

    with (
        patch.object(Path, "mkdir", recording_mkdir),
        patch.object(config_manager_module, "_remove_orphaned_temp_files", recording_remove),
        patch.object(config_manager_module, "initialize_defaults", recording_defaults),
    ):
        ConfigManager()

    assert seen
    assert all(path == override for path in seen)


def test_unusable_override_still_falls_back_to_the_local_directory(
    data_dir_default, tmp_path, monkeypatch
):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so a directory cannot be created beneath it")
    monkeypatch.setenv(DATA_DIR_ENV, str(blocker / "data"))
    monkeypatch.chdir(tmp_path)

    manager = ConfigManager()

    assert Path("./data") == manager.DATA_DIR
    assert Path("./data") / "config.json" == manager.CONFIG_FILE
    assert (tmp_path / "data" / "config.json").exists()


def test_an_exported_override_does_not_leak_into_the_unit_tests():
    """The autouse fixture in conftest.py clears it, so isolated tests stay isolated."""
    assert DATA_DIR_ENV not in os.environ
