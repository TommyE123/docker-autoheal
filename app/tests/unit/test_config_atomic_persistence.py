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

import errno
import json
import os
import stat
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


@pytest.mark.parametrize("existing_mode", [0o600, 0o640, 0o644])
def test_temp_file_is_never_more_permissive_than_the_file_it_replaces(
    isolated_config_manager, monkeypatch, existing_mode
):
    """A hardened file (e.g. 0600, it holds credentials) must not be copied into a
    temp file that is readable under a permissive umask, even briefly."""
    manager = isolated_config_manager
    _save_config(manager, 45)
    manager.CONFIG_FILE.chmod(existing_mode)

    modes_at_creation: list[int] = []
    real_fchmod = os.fchmod

    def spying_fchmod(fd, mode):
        modes_at_creation.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_fchmod(fd, mode)

    monkeypatch.setattr(os, "fchmod", spying_fchmod)
    previous_umask = os.umask(0o022)
    try:
        _save_config(manager, 50)
    finally:
        os.umask(previous_umask)

    assert modes_at_creation == [0o600]
    assert stat.S_IMODE(manager.CONFIG_FILE.stat().st_mode) == existing_mode


def test_new_file_gets_the_umask_default_mode(isolated_config_manager):
    manager = isolated_config_manager
    previous_umask = os.umask(0o027)
    try:
        _save_config(manager, 45)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(manager.CONFIG_FILE.stat().st_mode) == 0o640


def _other_owner() -> tuple[int, int] | None:
    """A (uid, gid) different from this process's, if one can be assigned here.

    root may hand a file to any owner; anyone else may only move a file they own
    to one of their own groups.
    """
    if os.geteuid() == 0:
        return 12345, 23456
    other_groups = [gid for gid in os.getgroups() if gid != os.getegid()]
    return (os.geteuid(), other_groups[0]) if other_groups else None


def test_existing_file_ownership_is_preserved(isolated_config_manager):
    """config.json is documented as hand-editable; a save must not hand the file
    to whoever runs the service (the old in-place write never changed the owner)."""
    owner = _other_owner()
    if owner is None:
        pytest.skip("needs root, or a second group to give the file to")
    uid, gid = owner
    manager = isolated_config_manager
    _save_config(manager, 45)
    os.chown(manager.CONFIG_FILE, uid, gid)
    manager.CONFIG_FILE.chmod(0o640)

    _save_config(manager, 50)

    after = manager.CONFIG_FILE.stat()
    assert (after.st_uid, after.st_gid) == (uid, gid)
    assert stat.S_IMODE(after.st_mode) == 0o640
    assert json.loads(manager.CONFIG_FILE.read_text())["monitor"]["interval_seconds"] == 50


def test_ownership_is_restored_before_the_final_mode_while_still_owner_only(
    isolated_config_manager, monkeypatch
):
    """chown can clear setuid/setgid bits, so the mode must be applied after it; and
    the temp file must still be owner-only (0600) while ownership changes hands."""
    manager = isolated_config_manager
    _save_config(manager, 45)
    existing = manager.CONFIG_FILE.stat()

    calls: list[tuple] = []
    real_fchown, real_fchmod = os.fchown, os.fchmod

    def spying_fchown(fd, uid, gid):
        calls.append(("fchown", uid, gid, stat.S_IMODE(os.fstat(fd).st_mode)))
        return real_fchown(fd, uid, gid)

    def spying_fchmod(fd, mode):
        calls.append(("fchmod", mode))
        return real_fchmod(fd, mode)

    monkeypatch.setattr(os, "fchown", spying_fchown)
    monkeypatch.setattr(os, "fchmod", spying_fchmod)

    _save_config(manager, 50)

    assert calls == [
        ("fchown", existing.st_uid, existing.st_gid, 0o600),
        ("fchmod", stat.S_IMODE(existing.st_mode)),
    ]


@pytest.mark.parametrize("error", [errno.EPERM, errno.EINVAL])
def test_save_still_succeeds_when_ownership_cannot_be_restored(
    isolated_config_manager, monkeypatch, error
):
    """Without the privilege (or on a filesystem that cannot chown) ownership is a
    best effort; the data and mode must still be saved and nothing left behind."""
    manager = isolated_config_manager
    _save_config(manager, 45)
    manager.CONFIG_FILE.chmod(0o640)

    def refusing_fchown(fd, uid, gid):
        raise OSError(error, os.strerror(error))

    monkeypatch.setattr(os, "fchown", refusing_fchown)
    _save_config(manager, 50)

    assert json.loads(manager.CONFIG_FILE.read_text())["monitor"]["interval_seconds"] == 50
    assert stat.S_IMODE(manager.CONFIG_FILE.stat().st_mode) == 0o640
    assert list(manager.DATA_DIR.glob(".config.json.*")) == []


def test_new_file_ownership_is_left_to_the_process(isolated_config_manager, monkeypatch):
    manager = isolated_config_manager
    chowned: list[tuple] = []
    monkeypatch.setattr(os, "fchown", lambda *args: chowned.append(args))

    _save_config(manager, 45)

    assert chowned == []
    assert manager.CONFIG_FILE.stat().st_uid == os.geteuid()
