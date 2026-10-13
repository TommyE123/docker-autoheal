"""
Unit tests for crash-safe persistence in ConfigManager (issue #441).

Every persisted file (config.json, events.json, quarantine.json,
maintenance.json) used to be written with ``Path.open("w")`` + ``json.dump``,
which truncates the target before the new content is written. A failure part
way through (full disk, OOM kill, crash) therefore destroyed the previous good
copy; for config.json the next load then fell back to factory defaults,
losing user settings and restart counts.

These tests interrupt the serialisation mid-write and require the previous
file to survive byte for byte.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import config_manager as config_manager_module
from app.config.config_manager import AutoHealEvent


def _event(message: str) -> AutoHealEvent:
    return AutoHealEvent(
        timestamp=datetime.now(UTC),
        container_id="container-1",
        container_name="web",
        event_type="restart",
        restart_count=1,
        status="success",
        message=message,
    )


def _save_config(manager, interval: int) -> None:
    config = manager.get_config()
    config.monitor.interval_seconds = interval
    manager.update_config(config)


# Each case: (file attribute, "first save" action, "second save" action).
# The first save establishes a good file; the second is interrupted mid-write.
PERSISTENCE_CASES = {
    "config": (
        "CONFIG_FILE",
        lambda m: _save_config(m, 45),
        lambda m: _save_config(m, 99),
    ),
    "events": (
        "EVENTS_FILE",
        lambda m: m.add_event(_event("first")),
        lambda m: m.add_event(_event("second")),
    ),
    "quarantine": (
        "QUARANTINE_FILE",
        lambda m: m.quarantine_container("container-1"),
        lambda m: m.quarantine_container("container-2"),
    ),
    "maintenance": (
        "MAINTENANCE_FILE",
        lambda m: m.enable_maintenance_mode(),
        lambda m: m.disable_maintenance_mode(),
    ),
}


def _interrupted_dump(obj, fp, **kwargs):
    """Stand-in for json.dump that writes a partial document, then fails."""
    fp.write('{"partial": ')
    fp.flush()
    raise OSError(28, "No space left on device")


@pytest.mark.parametrize("case", PERSISTENCE_CASES)
def test_interrupted_write_keeps_previous_file(isolated_config_manager, monkeypatch, case):
    file_attribute, first_save, second_save = PERSISTENCE_CASES[case]
    manager = isolated_config_manager
    path: Path = getattr(manager, file_attribute)

    first_save(manager)
    good_bytes = path.read_bytes()
    assert json.loads(good_bytes) is not None

    monkeypatch.setattr(config_manager_module.json, "dump", _interrupted_dump)
    second_save(manager)  # the save error is logged, not raised (existing behaviour)

    assert path.read_bytes() == good_bytes
    assert list(path.parent.glob(f".{path.name}.*")) == [], "temporary file was left behind"


def test_interrupted_config_write_does_not_reset_settings_on_next_load(
    isolated_config_manager, monkeypatch
):
    manager = isolated_config_manager
    _save_config(manager, 45)

    # Scoped context: a bare monkeypatch.undo() would also revert the autouse
    # fixtures' patches (asyncio.sleep, notification manager) mid-test.
    with monkeypatch.context() as patch_context:
        patch_context.setattr(config_manager_module.json, "dump", _interrupted_dump)
        _save_config(manager, 99)

    assert manager._load_config().monitor.interval_seconds == 45


@pytest.mark.parametrize("case", PERSISTENCE_CASES)
def test_write_is_flushed_to_disk_before_replacing_the_file(
    isolated_config_manager, monkeypatch, case
):
    file_attribute, first_save, _ = PERSISTENCE_CASES[case]
    manager = isolated_config_manager
    path: Path = getattr(manager, file_attribute)

    calls: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def recording_fsync(fd):
        calls.append("fsync")
        return real_fsync(fd)

    def recording_replace(src, dst):
        calls.append("replace")
        assert Path(src).parent == path.parent, "temp file must share the target's directory"
        assert Path(dst) == path
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "replace", recording_replace)

    first_save(manager)

    assert calls == ["fsync", "replace"]


def test_successful_save_keeps_format_and_existing_file_mode(isolated_config_manager):
    manager = isolated_config_manager
    _save_config(manager, 45)
    manager.CONFIG_FILE.chmod(0o640)

    _save_config(manager, 50)

    text = manager.CONFIG_FILE.read_text()
    assert text == json.dumps(json.loads(text), indent=2, default=str)
    assert json.loads(text)["monitor"]["interval_seconds"] == 50
    assert manager.CONFIG_FILE.stat().st_mode & 0o777 == 0o640
    assert list(manager.DATA_DIR.glob(".config.json.*")) == []


def test_symlinked_file_is_written_through_not_replaced(isolated_config_manager):
    manager = isolated_config_manager
    real_file = manager.DATA_DIR / "real-config.json"
    real_file.write_text("{}")
    manager.CONFIG_FILE.symlink_to(real_file)

    _save_config(manager, 45)

    assert manager.CONFIG_FILE.is_symlink()
    assert json.loads(real_file.read_text())["monitor"]["interval_seconds"] == 45


@pytest.mark.parametrize("failing_step", ["fsync", "replace"])
@pytest.mark.parametrize("case", PERSISTENCE_CASES)
def test_failure_after_serialisation_keeps_previous_file_and_cleans_up(
    isolated_config_manager, monkeypatch, case, failing_step
):
    file_attribute, first_save, second_save = PERSISTENCE_CASES[case]
    manager = isolated_config_manager
    path: Path = getattr(manager, file_attribute)

    first_save(manager)
    good_bytes = path.read_bytes()

    def failing(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(os, failing_step, failing)
    second_save(manager)

    assert path.read_bytes() == good_bytes
    assert list(path.parent.glob(f".{path.name}.*")) == [], "temporary file was left behind"
