"""
Unit tests for startup cleanup of orphaned atomic-write temp files (issue #566).

``_atomic_write_json`` writes to ``.<name>.<32 hex>.tmp`` and renames it over
the target. A hard kill between those steps leaves the temp file, a full copy
of the document (config.json holds credentials), in the data directory.
ConfigManager removes exactly those files when it starts.
"""

import logging
import uuid
from pathlib import Path

import pytest

from app.config.config_manager import ConfigManager, _remove_orphaned_temp_files

KNOWN_FILES = ("config.json", "events.json", "quarantine.json", "maintenance.json")


def _redirect_manager_paths(monkeypatch, data_dir: Path) -> None:
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


def _orphan(data_dir: Path, name: str) -> Path:
    path = data_dir / f".{name}.{uuid.uuid4().hex}.tmp"
    path.write_text('{"secret": "leftover"}')
    return path


@pytest.mark.parametrize("name", KNOWN_FILES)
def test_startup_removes_orphaned_temp_file_for_each_known_file(monkeypatch, tmp_path, name):
    _redirect_manager_paths(monkeypatch, tmp_path)
    orphan = _orphan(tmp_path, name)

    ConfigManager()

    assert not orphan.exists()


def test_startup_removes_multiple_orphans_and_logs_each(monkeypatch, tmp_path, caplog):
    _redirect_manager_paths(monkeypatch, tmp_path)
    orphans = [_orphan(tmp_path, "config.json"), _orphan(tmp_path, "config.json")]

    with caplog.at_level(logging.WARNING, logger="app.config.config_manager"):
        ConfigManager()

    assert not any(path.exists() for path in orphans)
    for path in orphans:
        assert any(str(path) in record.getMessage() for record in caplog.records)


def test_startup_leaves_non_matching_names_alone(monkeypatch, tmp_path):
    _redirect_manager_paths(monkeypatch, tmp_path)
    keep = [
        tmp_path / ".config.json.tmp",
        tmp_path / "config.json.tmp",
        tmp_path / f"config.json.{uuid.uuid4().hex}.tmp",  # not hidden
        tmp_path / f".other.json.{uuid.uuid4().hex}.tmp",  # unknown target
        tmp_path / f".restart_counts.json.{uuid.uuid4().hex}.tmp",  # never written atomically
        tmp_path / f".config.json.{uuid.uuid4().hex.upper()}.tmp",  # not lowercase hex
        tmp_path / f".config.json.{uuid.uuid4().hex[:31]}.tmp",  # too short
        tmp_path / f".config.json.{uuid.uuid4().hex}.tmp.bak",  # extra suffix
        tmp_path / "notes.txt",
    ]
    for path in keep:
        path.write_text("keep me")

    ConfigManager()

    for path in keep:
        assert path.read_text() == "keep me"


def test_startup_does_not_remove_directories_with_matching_names(monkeypatch, tmp_path):
    _redirect_manager_paths(monkeypatch, tmp_path)
    directory = tmp_path / f".config.json.{uuid.uuid4().hex}.tmp"
    directory.mkdir()

    ConfigManager()

    assert directory.is_dir()


def test_startup_does_not_follow_matching_symlinks(monkeypatch, tmp_path):
    _redirect_manager_paths(monkeypatch, tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("keep me")
    link = tmp_path / f".config.json.{uuid.uuid4().hex}.tmp"
    link.symlink_to(target)

    ConfigManager()

    assert link.is_symlink()
    assert target.read_text() == "keep me"


def test_startup_continues_when_an_orphan_cannot_be_removed(monkeypatch, tmp_path, caplog):
    _redirect_manager_paths(monkeypatch, tmp_path)
    orphan = _orphan(tmp_path, "config.json")
    real_unlink = Path.unlink

    def _failing_unlink(self, *args, **kwargs):
        if self == orphan:
            raise PermissionError("denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _failing_unlink)

    with caplog.at_level(logging.WARNING, logger="app.config.config_manager"):
        manager = ConfigManager()

    assert manager.get_config() is not None
    assert orphan.exists()
    assert any("Could not remove orphaned temp file" in r.getMessage() for r in caplog.records)


def test_scan_failure_is_logged_and_does_not_stop_startup(monkeypatch, tmp_path, caplog):
    _redirect_manager_paths(monkeypatch, tmp_path)
    real_iterdir = Path.iterdir

    def _failing_iterdir(self):
        if self == tmp_path:
            raise PermissionError("denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _failing_iterdir)

    with caplog.at_level(logging.WARNING, logger="app.config.config_manager"):
        _remove_orphaned_temp_files(tmp_path)

    assert any("Could not scan" in r.getMessage() for r in caplog.records)
