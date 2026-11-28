"""Behaviour tests for the Claude Code hooks in .claude/hooks/.

check_python_lint.py and check_markdown_lint.py must report Ruff and markdownlint findings
without changing the file and never get in the way of an edit. readonly-bash.sh must steer
read-only agents from the GraphQL-backed gh commands to gh api. The real scripts are executed
through their shebangs, as Claude Code runs them, with the hook JSON they receive on stdin.
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


@pytest.mark.parametrize("script", ["check_python_lint.py", "check_markdown_lint.py"])
def test_lint_hook_parses_as_python_3_13(script):
    # Claude Code runs the hook with whatever python3 is installed, not the Dockerfile's Python:
    # 3.13 in Claude Code cloud sessions. Ruff's py315 target can rewrite code into syntax that
    # 3.13 rejects.
    source = (HOOKS / script).read_text()
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


# --- check_markdown_lint.py ---------------------------------------------------------------------

requires_markdownlint = pytest.mark.skipif(
    shutil.which("markdownlint-cli2") is None, reason="markdownlint-cli2 is required"
)


@pytest.fixture
def md_root(tmp_path):
    root = tmp_path / "project"
    (root / ".linter-rules").mkdir(parents=True)
    config = ".linter-rules/.markdownlint.jsonc"
    shutil.copy(REPO_ROOT / config, root / config)
    return root


def _md_lint(root, file_path, env_path=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    if env_path is not None:
        env["PATH"] = env_path
    payload = {"tool_input": {"file_path": str(file_path)}, "cwd": str(root)}
    return _run_hook("check_markdown_lint.py", payload, env=env, cwd=root)


@requires_markdownlint
def test_markdown_lint_reports_findings_without_changing_the_file(md_root):
    source = "# Title\n\n" + "word " * 30 + "\n"
    target = md_root / "long.md"
    target.write_text(source)
    result = _md_lint(md_root, target)
    assert result.returncode == 2
    assert "MD013" in result.stderr
    assert target.read_text() == source


@requires_markdownlint
@pytest.mark.parametrize("name", ["release{a,b}.md", "notes (draft).md"])
def test_markdown_lint_treats_glob_characters_in_the_filename_literally(md_root, name):
    target = md_root / name
    target.write_text("# Title\n\n" + "word " * 30 + "\n")
    result = _md_lint(md_root, target)
    assert result.returncode == 2
    assert "MD013" in result.stderr


@requires_markdownlint
def test_markdown_lint_is_silent_for_a_clean_file(md_root):
    target = md_root / "clean.md"
    target.write_text("# Title\n\nShort line.\n")
    result = _md_lint(md_root, target)
    assert (result.returncode, result.stderr) == (0, "")


@requires_markdownlint
def test_markdown_lint_truncates_long_reports(md_root):
    target = md_root / "many.md"
    target.write_text("# Title\n\n" + "".join(f"{'word ' * 30}\n\n" for _ in range(60)))
    result = _md_lint(md_root, target)
    assert result.returncode == 2
    assert result.stderr.rstrip().endswith("(truncated)")


@requires_markdownlint
def test_markdown_lint_ignores_files_outside_the_project(md_root, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Title\n\n" + "word " * 30 + "\n")
    assert _md_lint(md_root, outside).returncode == 0


def test_markdown_lint_ignores_non_markdown_files(md_root):
    target = md_root / "notes.txt"
    target.write_text("word " * 30)
    assert _md_lint(md_root, target).returncode == 0


def test_markdown_lint_does_nothing_without_a_linter_or_npx(md_root, tmp_path):
    target = md_root / "long.md"
    target.write_text("# Title\n\n" + "word " * 30 + "\n")
    python_only = tmp_path / "python-only"
    python_only.mkdir()
    (python_only / "python3").symlink_to(sys.executable)
    assert _md_lint(md_root, target, env_path=str(python_only)).returncode == 0


def test_markdown_lint_is_silent_when_npx_cannot_fetch_the_linter(md_root, tmp_path):
    target = md_root / "long.md"
    target.write_text("# Title\n\n" + "word " * 30 + "\n")
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "python3").symlink_to(sys.executable)
    npx = fake / "npx"
    npx.write_text("#!/bin/sh\necho 'npm error network' >&2\nexit 1\n")
    npx.chmod(0o755)
    result = _md_lint(md_root, target, env_path=str(fake))
    assert (result.returncode, result.stderr) == (0, "")


def _fake_linter(directory, name, stderr="fake finding"):
    """Put a fake `name` on a PATH directory: it records its arguments and reports findings."""
    directory.mkdir(exist_ok=True)
    if not (directory / "python3").exists():
        (directory / "python3").symlink_to(sys.executable)
    script = directory / name
    script.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$@" > "${0%/*}/args.txt"\n'
        "echo 'markdownlint-cli2 v0.0.0 (markdownlint v0.0.0)'\n"
        f"printf '%s' '{stderr}' >&2\n"
        "exit 1\n"
    )
    script.chmod(0o755)
    return directory


def _recorded_args(directory):
    return (directory / "args.txt").read_text().splitlines()


@pytest.mark.parametrize("name", ["release{a,b}.md", "notes (draft).md", "plain.md"])
def test_markdown_lint_passes_the_edited_file_as_a_literal_path(md_root, tmp_path, name):
    target = md_root / name
    target.write_text("# Title\n")
    fake = _fake_linter(tmp_path / "bin", "markdownlint-cli2")
    result = _md_lint(md_root, target, env_path=str(fake))
    assert result.returncode == 2
    assert "fake finding" in result.stderr
    config = md_root / ".linter-rules" / ".markdownlint.jsonc"
    assert _recorded_args(fake) == ["--config", str(config), f":{target.resolve()}"]


def test_markdown_lint_truncates_long_reports_from_a_fake_linter(md_root, tmp_path):
    target = md_root / "doc.md"
    target.write_text("# Title\n")
    fake = _fake_linter(tmp_path / "bin", "markdownlint-cli2", stderr="x" * 6000)
    result = _md_lint(md_root, target, env_path=str(fake))
    assert result.returncode == 2
    assert result.stderr.rstrip().endswith("(truncated)")


def test_markdown_lint_uses_npx_when_the_linter_is_not_installed(md_root, tmp_path):
    target = md_root / "doc.md"
    target.write_text("# Title\n")
    fake = _fake_linter(tmp_path / "bin", "npx")
    result = _md_lint(md_root, target, env_path=str(fake))
    assert result.returncode == 2
    config = md_root / ".linter-rules" / ".markdownlint.jsonc"
    assert _recorded_args(fake) == [
        "--yes",
        "markdownlint-cli2",
        "--config",
        str(config),
        f":{target.resolve()}",
    ]


def test_markdown_lint_prefers_the_installed_linter_over_npx(md_root, tmp_path):
    target = md_root / "doc.md"
    target.write_text("# Title\n")
    fake = _fake_linter(tmp_path / "bin", "markdownlint-cli2")
    _fake_linter(fake, "npx", stderr="npx should not run")
    result = _md_lint(md_root, target, env_path=str(fake))
    assert result.returncode == 2
    assert "npx should not run" not in result.stderr


def test_markdown_lint_ignores_files_outside_the_project_with_a_fake_linter(md_root, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Title\n")
    fake = _fake_linter(tmp_path / "bin", "markdownlint-cli2")
    assert _md_lint(md_root, outside, env_path=str(fake)).returncode == 0
    assert not (fake / "args.txt").exists()


def test_markdown_lint_never_blocks_on_bad_input():
    assert _run_hook("check_markdown_lint.py", "not json").returncode == 0
    assert _run_hook("check_markdown_lint.py", {"tool_input": {}}).returncode == 0


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
