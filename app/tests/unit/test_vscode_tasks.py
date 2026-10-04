"""Contract check for the VS Code Docker Stack task.

Kept out of ``test_main_lifecycle.py`` because it reads ``.vscode/tasks.json`` relative to the
repository root, which does not exist inside ``mutants/``. It imports nothing from ``app/``, so
mutation testing ignores it (see ``pyproject.toml``).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_run_docker_stack_task_does_not_detect_an_ip():
    tasks = json.loads(
        (REPO_ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8")
    )["tasks"]
    task = next(t for t in tasks if t["label"] == "Autoheal: Run Docker Stack")

    assert task["command"] == (
        "docker compose -p docker-autoheal-dev -f docker-compose.yml -f docker-compose.dev.yml up --build autoheal"
    )
    assert "hostname" not in task["command"]
