"""
Unit tests for configuration initialization
Tests the automatic creation of default configuration files
"""

import json
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from app.config import init_defaults
from app.config.init_defaults import (
    get_default_config,
    get_default_events,
    get_default_maintenance,
    get_default_quarantine,
    init_data_file,
    initialize_defaults,
    reset_to_defaults,
)


class TestInitDefaults:
    """Test configuration initialization"""

    def setup_method(self):
        """Create a temporary directory for each test"""
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        """Clean up temporary directory after each test"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_initialize_creates_all_files(self):
        """Test that initialize_defaults creates all required files"""
        result = initialize_defaults(self.temp_dir)
        assert result == self.temp_dir

        # Check all files were created
        assert (self.temp_dir / "config.json").exists()
        assert (self.temp_dir / "events.json").exists()
        assert (self.temp_dir / "quarantine.json").exists()
        assert (self.temp_dir / "maintenance.json").exists()
        assert (self.temp_dir / "logs").exists()
        assert (self.temp_dir / "logs").is_dir()

    def test_initialize_does_not_overwrite(self):
        """Test that initialize_defaults doesn't overwrite existing files"""
        config_file = self.temp_dir / "config.json"

        # Create a custom config
        custom_data = {"test": "custom_value"}
        with config_file.open("w") as f:
            json.dump(custom_data, f)

        # Run initialization
        initialize_defaults(self.temp_dir)

        # Verify custom config was not overwritten
        with config_file.open("r") as f:
            loaded_data = json.load(f)

        assert loaded_data == custom_data

    def test_default_config_structure(self):
        """Test that default config has all required fields"""
        config = get_default_config()

        # Check top-level keys
        assert "monitor" in config
        assert "containers" in config
        assert "restart" in config
        assert "filters" in config
        assert "ui" in config
        assert "alerts" in config
        assert "observability" in config
        assert "uptime_kuma" in config
        assert "notifications" in config

        # Check monitor settings
        assert config["monitor"]["interval_seconds"] == 30
        assert config["monitor"]["label_key"] == "autoheal"
        assert config["monitor"]["label_value"] == "true"
        assert config["monitor"]["include_all"] is False

        # Check restart settings
        assert config["restart"]["mode"] == "on-failure"
        assert config["restart"]["max_restarts"] == 3
        assert config["restart"]["cooldown_seconds"] == 60

        # Check UI settings
        assert config["ui"]["enable"] is True
        assert config["ui"]["listen_port"] == 3131

        # Check observability settings
        assert config["observability"]["prometheus_enabled"] is True
        assert config["observability"]["metrics_port"] == 9090
        assert config["observability"]["log_level"] == "INFO"

    def test_default_events_is_empty_list(self):
        """Test that default events is an empty list"""
        events = get_default_events()
        assert events == []
        assert isinstance(events, list)

    def test_default_quarantine_is_empty_list(self):
        """Test that default quarantine is an empty list"""
        quarantine = get_default_quarantine()
        assert quarantine == []
        assert isinstance(quarantine, list)

    def test_default_maintenance_structure(self):
        """Test that default maintenance has correct structure"""
        maintenance = get_default_maintenance()
        assert "enabled" in maintenance
        assert "start_time" in maintenance
        assert maintenance["enabled"] is False
        assert maintenance["start_time"] is None

    def test_config_json_is_valid(self):
        """Test that created config.json is valid JSON"""
        initialize_defaults(self.temp_dir)
        config_file = self.temp_dir / "config.json"

        with config_file.open("r") as f:
            data = json.load(f)  # Should not raise exception

        assert isinstance(data, dict)

    def test_events_json_is_valid(self):
        """Test that created events.json is valid JSON"""
        initialize_defaults(self.temp_dir)
        events_file = self.temp_dir / "events.json"

        with events_file.open("r") as f:
            data = json.load(f)

        assert isinstance(data, list)

    def test_reset_to_defaults(self):
        """Test that reset_to_defaults overwrites existing files"""
        # Create initial config
        initialize_defaults(self.temp_dir)

        # Modify config
        config_file = self.temp_dir / "config.json"
        with config_file.open("r") as f:
            config = json.load(f)
        config["monitor"]["interval_seconds"] = 99
        with config_file.open("w") as f:
            json.dump(config, f)

        # Reset to defaults
        reset_to_defaults(self.temp_dir)

        # Verify config was reset
        with config_file.open("r") as f:
            config = json.load(f)
        assert config["monitor"]["interval_seconds"] == 30

    def test_logs_directory_created(self):
        """Test that logs subdirectory is created"""
        initialize_defaults(self.temp_dir)
        logs_dir = self.temp_dir / "logs"

        assert logs_dir.exists()
        assert logs_dir.is_dir()

    def test_creates_nested_directories(self):
        """Test that initialization creates nested directories if needed"""
        nested_dir = self.temp_dir / "nested" / "path"
        initialize_defaults(nested_dir)

        assert nested_dir.exists()
        assert (nested_dir / "config.json").exists()

    def test_json_formatting(self):
        """Test that JSON files are properly formatted (indented)"""
        initialize_defaults(self.temp_dir)
        config_file = self.temp_dir / "config.json"

        with config_file.open("r") as f:
            content = f.read()

        # Check that JSON is indented (not minified)
        assert "\n" in content  # Has newlines
        assert "  " in content  # Has indentation


class TestInitDataFile:
    """Test init_data_file edge cases"""

    def test_existing_file_returns_false(self, tmp_path):
        target = tmp_path / "existing.json"
        target.write_text("{}")

        assert init_data_file(target, {"a": 1}, "existing") is False
        assert target.read_text() == "{}"

    def test_write_failure_returns_false(self, tmp_path, monkeypatch):
        def fail_dump(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(init_defaults.json, "dump", fail_dump)

        assert init_data_file(tmp_path / "new.json", {"a": 1}, "new") is False


class TestInitializeDefaultsFallback:
    """Test directory creation failure handling"""

    def test_falls_back_to_local_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        unwritable = tmp_path / "blocker" / "data"
        (tmp_path / "blocker").write_text("a file, not a directory")

        result = initialize_defaults(unwritable)

        assert result == Path("./data")
        assert (tmp_path / "data" / "config.json").exists()

    def test_logs_dir_failure_is_not_fatal(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "logs").write_text("a file, not a directory")

        result = initialize_defaults(data_dir)

        assert result == data_dir
        assert (data_dir / "config.json").exists()


class TestResetToDefaults:
    """Test reset_to_defaults edge cases"""

    def test_overwrites_every_file(self, tmp_path):
        names = ["config.json", "events.json", "quarantine.json", "maintenance.json"]
        for name in names:
            (tmp_path / name).write_text('"stale"')

        reset_to_defaults(tmp_path)

        assert json.loads((tmp_path / "config.json").read_text()) == get_default_config()
        assert json.loads((tmp_path / "events.json").read_text()) == get_default_events()
        assert json.loads((tmp_path / "quarantine.json").read_text()) == get_default_quarantine()
        assert json.loads((tmp_path / "maintenance.json").read_text()) == get_default_maintenance()

    def test_write_errors_do_not_stop_remaining_files(self, tmp_path):
        # A directory named config.json makes opening it for writing fail.
        (tmp_path / "config.json").mkdir()

        reset_to_defaults(tmp_path)

        assert (tmp_path / "config.json").is_dir()
        assert json.loads((tmp_path / "events.json").read_text()) == get_default_events()
        assert json.loads((tmp_path / "quarantine.json").read_text()) == get_default_quarantine()
        assert json.loads((tmp_path / "maintenance.json").read_text()) == get_default_maintenance()


class TestCliMain:
    """Test the ``python -m app.config.init_defaults`` entry point"""

    def _run(self, monkeypatch, *args):
        monkeypatch.setattr(sys, "argv", ["init_defaults", *args])
        # Drop the cached module so runpy does not warn about re-execution.
        monkeypatch.delitem(sys.modules, "app.config.init_defaults", raising=False)
        runpy.run_module("app.config.init_defaults", run_name="__main__")

    def test_initialize(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "cli"

        self._run(monkeypatch, "--data-dir", str(target))

        assert "Initialization complete!" in capsys.readouterr().out
        assert (target / "config.json").exists()

    @pytest.mark.parametrize("answer", ["yes", "YES"])
    def test_reset_confirmed(self, tmp_path, monkeypatch, capsys, answer):
        (tmp_path / "events.json").write_text('["stale"]')
        monkeypatch.setattr("builtins.input", lambda _prompt: answer)

        self._run(monkeypatch, "--reset", "--data-dir", str(tmp_path))

        assert "Reset complete!" in capsys.readouterr().out
        assert json.loads((tmp_path / "events.json").read_text()) == []

    def test_reset_cancelled(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "events.json").write_text('["stale"]')
        monkeypatch.setattr("builtins.input", lambda _prompt: "no")

        self._run(monkeypatch, "--reset", "--data-dir", str(tmp_path))

        assert "Reset cancelled." in capsys.readouterr().out
        assert json.loads((tmp_path / "events.json").read_text()) == ["stale"]


class TestInitializeDefaultsIdempotent:
    """Test repeated initialization"""

    def test_second_run_creates_nothing(self, tmp_path, caplog):
        initialize_defaults(tmp_path)
        before = {p.name: p.read_text() for p in tmp_path.glob("*.json")}

        with caplog.at_level("INFO", logger=init_defaults.logger.name):
            initialize_defaults(tmp_path)

        assert {p.name: p.read_text() for p in tmp_path.glob("*.json")} == before
        assert "no initialization needed" in caplog.text
