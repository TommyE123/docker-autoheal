"""
Unit tests for module-level code that only runs when a module is imported.

``app/main.py`` falls back to ``./data/logs`` when ``/data/logs`` can't be
created, and ``app/api/api.py`` tolerates a missing ``static/assets`` directory.
Both modules are executed with ``runpy`` under a throwaway module name, so the
real ``app.main`` and ``app.api.api`` in ``sys.modules`` are never replaced.
The working directory is a temporary directory and logging handlers are faked,
so nothing is written outside ``tmp_path``.
"""

import asyncio
import logging
import runpy
from pathlib import Path
from unittest.mock import MagicMock

import prometheus_client
import pytest
from fastapi import FastAPI

# runpy warns that the module is already imported; running a copy is the point here.
pytestmark = pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")


@pytest.fixture
def sandboxed_import(tmp_path, monkeypatch):
    """Run from ``tmp_path`` with logging set-up faked and ``/data/logs`` unwritable."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(logging, "basicConfig", MagicMock())
    monkeypatch.setattr(logging, "FileHandler", MagicMock())
    # app.main registers its metrics at import time; a second run would collide.
    monkeypatch.setattr(prometheus_client, "Counter", MagicMock())
    monkeypatch.setattr(prometheus_client, "Gauge", MagicMock())

    real_mkdir = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self == Path("/data/logs"):
            raise PermissionError("read-only file system")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    return tmp_path


def test_main_falls_back_to_local_log_dir_when_data_is_not_writable(sandboxed_import):
    namespace = runpy.run_module("app.main", run_name="app_main_fallback")

    assert namespace["LOG_DIR"] == Path("./data/logs")
    assert namespace["LOG_FILE"] == Path("./data/logs/autoheal.log")
    assert (sandboxed_import / "data" / "logs").is_dir()


def test_main_entry_point_runs_the_service(sandboxed_import, monkeypatch):
    started = []

    def fake_run(coroutine):
        started.append(coroutine.cr_code.co_name)
        coroutine.close()

    monkeypatch.setattr(asyncio, "run", fake_run)

    runpy.run_module("app.main", run_name="__main__")

    assert started == ["main"]


def test_api_survives_a_missing_assets_directory(sandboxed_import, caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.api"):
        runpy.run_module("app.api.api", run_name="app_api_no_assets")

    assert "Assets directory not found" in caplog.text


def test_api_mounts_the_assets_directory_when_present(sandboxed_import, caplog):
    (sandboxed_import / "static" / "assets").mkdir(parents=True)

    with caplog.at_level(logging.DEBUG, logger="app.api.api"):
        namespace = runpy.run_module("app.api.api", run_name="app_api_with_assets")

    assert "Static assets mounted" in caplog.text
    assert "Assets directory not found" not in caplog.text
    assert any(getattr(route, "path", None) == "/assets" for route in namespace["app"].routes)


def test_api_survives_a_static_assets_mount_failure(sandboxed_import, monkeypatch, caplog):
    (sandboxed_import / "static" / "assets").mkdir(parents=True)

    def fail_mount(self, path, app, name=None):
        raise RuntimeError("mount failed")

    monkeypatch.setattr(FastAPI, "mount", fail_mount)

    with caplog.at_level(logging.WARNING, logger="app.api.api"):
        runpy.run_module("app.api.api", run_name="app_api_mount_failure")

    assert "Assets directory not found: mount failed" in caplog.text
