"""Behaviour tests for the Claude Code hooks in .claude/hooks/.

check_python_lint.py must report Ruff findings without changing the file and never get in the way
of an edit. readonly-bash.sh must steer read-only agents from the GraphQL-backed gh commands to
gh api. The real scripts are executed through their shebangs, as Claude Code runs them, with the
hook JSON they receive on stdin.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOKS = REPO_ROOT / ".claude" / "hooks"


def _run_hook(script, payload, env=None, cwd=None):
    # The repository's own fixed scripts; nothing here is untrusted input.
    return subprocess.run(  # noqa: S603
        [HOOKS / script],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_lint_hook_parses_as_python_3_13():
    # Claude Code runs the hook with whatever python3 is installed, not the Dockerfile's Python:
    # 3.13 in Claude Code cloud sessions. Ruff's py315 target can rewrite code into syntax that
    # 3.13 rejects.
    source = (HOOKS / "check_python_lint.py").read_text()
    ast.parse(source, feature_version=(3, 13))
    assert source.startswith("#!/usr/bin/env python3\n")


# --- check_python_lint.py -----------------------------------------------------------------------

requires_ruff = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is required")


@pytest.fixture
def lint_root(tmp_path):
    root = tmp_path / "project"
    (root / ".linter-rules").mkdir(parents=True)
    shutil.copy(REPO_ROOT / ".linter-rules" / ".ruff.toml", root / ".linter-rules" / ".ruff.toml")
    return root


def _lint(root, file_path, env_path=None, cwd=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    if env_path is not None:
        env["PATH"] = env_path
    payload = {"tool_input": {"file_path": str(file_path)}, "cwd": str(root)}
    return _run_hook("check_python_lint.py", payload, env=env, cwd=cwd)


@requires_ruff
def test_lint_reports_ruff_findings_without_changing_the_file(lint_root):
    source = "import os\nx=1\n"
    target = lint_root / "bad.py"
    target.write_text(source)
    result = _lint(lint_root, target)
    assert result.returncode == 2
    assert "F401" in result.stderr
    assert "ruff format --check" in result.stderr
    assert target.read_text() == source


@requires_ruff
def test_lint_is_silent_for_a_clean_file(lint_root):
    target = lint_root / "clean.py"
    target.write_text('"""Clean module."""\n\nVALUE = 1\n')
    result = _lint(lint_root, target)
    assert (result.returncode, result.stderr) == (0, "")


@requires_ruff
def test_lint_applies_path_based_ignores_from_a_subdirectory(lint_root):
    # .ruff.toml ignores ANN201 under app/api/routes/; Claude Code may run the hook from app/.
    routes = lint_root / "app" / "api" / "routes"
    routes.mkdir(parents=True)
    target = routes / "handlers.py"
    target.write_text('"""Routes."""\n\n\ndef handler():\n    return 1\n')
    result = _lint(lint_root, target, cwd=lint_root / "app")
    assert (result.returncode, result.stderr) == (0, "")


@requires_ruff
def test_lint_checks_files_in_another_worktree(lint_root, tmp_path):
    # CLAUDE_PROJECT_DIR stays on the original checkout when Claude works in another worktree.
    worktree = tmp_path / "worktree"
    shutil.copytree(lint_root, worktree)
    subprocess.run(["git", "init", "-q", str(worktree)], check=True)  # noqa: S603, S607
    target = worktree / "bad.py"
    target.write_text("import os\n")
    result = _lint(lint_root, target)
    assert result.returncode == 2
    assert "F401" in result.stderr


@requires_ruff
def test_lint_truncates_long_reports(lint_root):
    target = lint_root / "many.py"
    target.write_text("".join(f"import mod{i}\n" for i in range(300)))
    result = _lint(lint_root, target)
    assert result.returncode == 2
    assert result.stderr.rstrip().endswith("(truncated)")


@requires_ruff
def test_lint_ignores_files_outside_the_project(lint_root, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("import os\n")
    assert _lint(lint_root, outside).returncode == 0


def test_lint_ignores_non_python_files(lint_root):
    target = lint_root / "notes.md"
    target.write_text("import os\n")
    assert _lint(lint_root, target).returncode == 0


def test_lint_does_nothing_without_ruff(lint_root, tmp_path):
    target = lint_root / "bad.py"
    target.write_text("import os\n")
    # A PATH with python3, so the shebang resolves, but no ruff.
    python_only = tmp_path / "python-only"
    python_only.mkdir()
    (python_only / "python3").symlink_to(sys.executable)
    assert _lint(lint_root, target, env_path=str(python_only)).returncode == 0


def test_lint_never_blocks_on_bad_input():
    assert _run_hook("check_python_lint.py", "not json").returncode == 0
    assert _run_hook("check_python_lint.py", {"tool_input": {}}).returncode == 0


# --- readonly-bash.sh ---------------------------------------------------------------------------

requires_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")


@requires_jq
@pytest.mark.parametrize(
    "command", ["gh issue view 1 --comments", "gh pr view 1", "gh pr checks 1", "gh pr list"]
)
def test_readonly_hook_points_graphql_commands_to_gh_api(command):
    result = _run_hook("readonly-bash.sh", {"tool_input": {"command": command}})
    assert result.returncode == 2
    assert "gh api" in result.stderr


@requires_jq
@pytest.mark.parametrize(
    "command",
    ["gh api repos/o/r/issues/1/comments", "gh pr diff 1", "gh run view 5", "git log -n 3"],
)
def test_readonly_hook_allows_read_only_commands(command):
    result = _run_hook("readonly-bash.sh", {"tool_input": {"command": command}})
    assert result.returncode == 0, result.stderr
