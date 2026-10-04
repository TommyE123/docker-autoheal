"""Contract checks for the dev stack files: the VS Code task and the dev Compose bootstrap.

Kept in a module of their own because they read repository files relative to the repository
root, which does not exist inside ``mutants/``. They import nothing from ``app/`` directly, so
mutation testing ignores this module (see ``pyproject.toml``).
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_DEV = REPO_ROOT / "docker-compose.dev.yml"
SEED = '{"monitor":{"label_key":"autoheal.dev"}}'


def test_run_docker_stack_task_does_not_detect_an_ip():
    tasks = json.loads(
        (REPO_ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8")
    )["tasks"]
    task = next(t for t in tasks if t["label"] == "Autoheal: Run Docker Stack")

    assert task["command"] == (
        "docker compose -p docker-autoheal-dev -f docker-compose.yml "
        "-f docker-compose.dev.yml up --build autoheal"
    )
    assert "hostname" not in task["command"]


def _bootstrap_script() -> str:
    """The shell script the dev override runs before starting the app (its ``command``)."""
    text = COMPOSE_DEV.read_text(encoding="utf-8")
    block = re.search(r"- sh\n\s+- -c\n\s+- \|\n((?:        .*\n|\n)+)", text)
    assert block, "dev bootstrap command not found in docker-compose.dev.yml"
    return "\n".join(line[8:] for line in block.group(1).split("\n"))


def _run_bootstrap(data_dir: Path, config_text: str | None):
    """Run the real bootstrap against ``data_dir``; the final ``exec`` just prints STARTED."""
    if config_text is not None:
        (data_dir / "config.json").write_text(config_text, encoding="utf-8")
    script = _bootstrap_script()
    script = script.replace("exec python -m app.main", "echo STARTED")
    script = script.replace("python - <<", f"{sys.executable} - <<")
    script = script.replace("/data", str(data_dir))
    return subprocess.run(
        ["sh", "-c", script],
        cwd=data_dir if data_dir.exists() else data_dir.parent,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
class TestDevBootstrapFailsClosed:
    """The dev container must never start with the production ``autoheal=true`` label."""

    def test_first_start_seeds_the_dev_label_and_starts(self, tmp_path):
        result = _run_bootstrap(tmp_path, None)

        assert result.returncode == 0, result.stderr
        assert "STARTED" in result.stdout
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == SEED
        assert not (tmp_path / "config.json.tmp").exists()

    def test_valid_existing_config_is_kept_unchanged(self, tmp_path):
        # A legitimate user change to the monitoring label is preserved, not re-seeded.
        custom = '{"monitor":{"label_key":"my.dev","label_value":"yes"},"restart":{"mode":"both"}}'

        result = _run_bootstrap(tmp_path, custom)

        assert result.returncode == 0, result.stderr
        assert "STARTED" in result.stdout
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == custom

    @pytest.mark.parametrize(
        "config_text",
        [
            pytest.param('{"monitor":{"label_key":"autoh', id="malformed-json"),
            pytest.param("", id="empty-file"),
            pytest.param("[]", id="not-an-object"),
            pytest.param('{"restart":{"mode":"both"}}', id="monitor-section-missing"),
            pytest.param('{"monitor":"autoheal.dev"}', id="monitor-wrong-type"),
            pytest.param(
                '{"monitor":{"label_key":"autoheal.dev","interval_seconds":0}}',
                id="monitor-has-an-invalid-field",
            ),
            pytest.param('{"monitor":{}}', id="defaults-to-the-production-label"),
            pytest.param(
                '{"monitor":{"label_key":"autoheal","label_value":"true"}}',
                id="explicit-production-label",
            ),
        ],
    )
    def test_unusable_existing_config_stops_the_container(self, tmp_path, config_text):
        result = _run_bootstrap(tmp_path, config_text)

        assert result.returncode != 0
        assert "STARTED" not in result.stdout
        assert "Refusing to start" in result.stderr
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == config_text

    def test_failed_seed_stops_the_container(self, tmp_path):
        result = _run_bootstrap(tmp_path / "missing", None)

        assert result.returncode != 0
        assert "STARTED" not in result.stdout
