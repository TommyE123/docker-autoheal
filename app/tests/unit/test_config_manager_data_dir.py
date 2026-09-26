"""Tests for ConfigManager's AUTOHEAL_DATA_DIR override (issue #4).

``ConfigManager.DATA_DIR`` is a class attribute evaluated once, via
``_resolve_data_dir()``, at class-definition time -- i.e. at import time,
before ``__init__``/``_ensure_data_directory`` ever run. ``_resolve_data_dir``
is tested directly here since it is pure and side-effect free; a full
``ConfigManager()`` construction only needs an env var reload for the one
end-to-end test confirming the override actually reaches the class.
"""

import importlib.util

import app.config.config_manager as config_manager_module
from app.config.config_manager import _resolve_data_dir


def _load_module_copy():
    """Execute config_manager.py's source as an independent module object.

    A plain ``importlib.reload`` would replace ``sys.modules`` in place,
    changing the identity of classes (``AutoHealConfig``, ``HealthCheckConfig``,
    etc.) that every other test module already imported by reference - breaking
    isinstance/equality checks across the whole suite. Loading the source under
    a throwaway module name avoids that entirely: it re-evaluates the class
    attributes (including DATA_DIR, via _resolve_data_dir()) against the
    current environment without touching the shared module or its singleton.
    """
    spec = importlib.util.spec_from_file_location(
        "app.config._config_manager_reload_probe",
        config_manager_module.__file__,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_data_dir_defaults_to_slash_data_when_unset(monkeypatch):
    monkeypatch.delenv("AUTOHEAL_DATA_DIR", raising=False)

    assert _resolve_data_dir() == config_manager_module.Path("/data")


def test_resolve_data_dir_uses_override_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOHEAL_DATA_DIR", str(tmp_path / "custom-data"))

    assert _resolve_data_dir() == tmp_path / "custom-data"


def test_resolve_data_dir_falls_back_to_default_on_empty_override(monkeypatch):
    """An empty string override (e.g. an unset-but-defined env var in some
    deployment tooling) must not resolve to Path(""), the CWD."""
    monkeypatch.setenv("AUTOHEAL_DATA_DIR", "")

    assert _resolve_data_dir() == config_manager_module.Path("/data")


def test_config_manager_construction_honors_data_dir_override(monkeypatch, tmp_path):
    """End-to-end: with AUTOHEAL_DATA_DIR set, a freshly constructed
    ConfigManager (and its dependent file paths) uses the override, and its
    data directory is actually created there."""
    override_dir = tmp_path / "autoheal-data"
    monkeypatch.setenv("AUTOHEAL_DATA_DIR", str(override_dir))

    module = _load_module_copy()
    manager = module.ConfigManager()

    assert manager.DATA_DIR == override_dir
    assert manager.CONFIG_FILE == override_dir / "config.json"
    assert override_dir.is_dir()
