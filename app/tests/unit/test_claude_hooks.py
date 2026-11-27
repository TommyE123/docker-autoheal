"""Behaviour tests for the Claude Code hooks in .claude/hooks/.

guard_git_push.py must block force pushes and pushes to main, ask before pushing a branch whose
name breaks CLAUDE.md's rule, and let everything else through. check_python_lint.py must report
Ruff findings without changing the file and never get in the way of an edit. readonly-bash.sh
must steer read-only agents from the GraphQL-backed gh commands to gh api. The real scripts are
executed through their shebangs, as Claude Code runs them, with the hook JSON they receive on
stdin.
"""

import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOKS = REPO_ROOT / ".claude" / "hooks"


def _run_hook(script, payload, env=None):
    # The repository's own fixed scripts; nothing here is untrusted input.
    return subprocess.run(  # noqa: S603
        [HOOKS / script],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(cwd, *args):
    subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), *args],  # noqa: S607
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )


@pytest.fixture
def repo(tmp_path):
    """A clone of a local remote, on `main`, with one commit and a `v1.0.0` tag."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(remote), str(clone))
    _git(clone, "commit", "--allow-empty", "-m", "initial")
    _git(clone, "push", "origin", "main")
    _git(clone, "tag", "v1.0.0")
    return clone


def _guard(repo, command):
    return _run_hook("guard_git_push.py", {"tool_input": {"command": command}, "cwd": str(repo)})


def _decision(result):
    if result.returncode == 2:
        return "block"
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return "allow"
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    return output["permissionDecision"]


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin fix/1-some-fix",
        "git push -f origin fix/1-some-fix",
        "git push -uf origin fix/1-some-fix",
        "git push --force-with-lease origin fix/1-some-fix",
        "git push --force-with-lease=fix/1-some-fix:abc123 origin fix/1-some-fix",
        "git push --mirror origin",
        "git push origin +fix/1-some-fix",
        "git push origin +HEAD:fix/1-some-fix",
        "git -C . push --force origin fix/1-some-fix",
        "git -c push.default=current push -f",
        "/usr/bin/git push -f origin fix/1-some-fix",
        "cd . && git push -f origin fix/1-some-fix",
        "git status\ngit push --force origin fix/1-some-fix",
        "echo `git push -f origin fix/1-some-fix`",
        "# Push the rewritten branch\ngit push --force origin fix/1-some-fix",
        "git fetch origin  # refresh\ngit push -f origin fix/1-some-fix",
        "git push origin fix/12-issue#12 --force",
        "bash -c 'git push --force origin fix/1-some-fix'",
        'sh -lc "cd . && git push -f origin fix/1-some-fix"',
        "eval git push -f origin fix/1-some-fix",
        "cat <<'EOF' > notes.md\ngit push origin main\nEOF\ngit push -f origin fix/1-some-fix",
        'echo "<<EOF"\ngit push -f origin fix/1-some-fix',
    ],
)
def test_force_push_is_blocked(repo, command):
    result = _guard(repo, command)
    assert _decision(result) == "block"
    assert "force-push" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push origin HEAD:main",
        "git push origin HEAD:refs/heads/main",
        "git push origin :main",
        "git push origin --delete main",
        "git push -d origin main",
        "git push",
    ],
)
def test_push_to_main_is_blocked(repo, command):
    # The fixture's current branch is main, so a bare `git push` targets it too.
    result = _guard(repo, command)
    assert _decision(result) == "block"
    assert "`main`" in result.stderr


def test_bare_push_follows_upstream_to_main(repo):
    # A feature branch created from origin/main tracks it, so a bare push would update main.
    _git(repo, "checkout", "-b", "fix/1-some-fix", "--track", "origin/main")
    _git(repo, "config", "push.default", "upstream")
    assert _decision(_guard(repo, "git push")) == "block"


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin ccr-7c111260-nb365r",
        "git push -u origin claude/brave-cannon-x1rfr7",
        "git push origin feat/one",
        "git push origin feat/one-two-three-four-five-six",
        "git push origin Fix/1-some-fix",
        "git push origin HEAD:wip",
        "git push --all origin",
        "git push origin --delete ccr-7c111260-nb365r",
        "git push origin :fix/1-some-fix",
    ],
)
def test_non_compliant_branch_or_deletion_asks_the_user(repo, command):
    result = _guard(repo, command)
    assert _decision(result) == "ask"
    assert (
        "guard_git_push hook"
        in json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    )


def test_bare_push_of_non_compliant_current_branch_asks(repo):
    _git(repo, "checkout", "-b", "my-branch")
    assert _decision(_guard(repo, "git push -u origin HEAD")) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin fix/353-restart-handling",
        "git push origin docs/update-readme",
        "git push origin feat/one-two-three-four-five",
        "git push -o ci.skip origin feat/new-thing",
        "git push --push-option=ci.skip origin feat/new-thing",
        "git push --repo origin origin feat/new-thing",
        "git push origin feat/new-thing 2>&1 | tail -3",
        "git push origin HEAD:refs/heads/chore/12-tidy-up",
        "git push origin v1.0.0",
        "git push origin refs/tags/v2.0.0",
        "git push --tags",
        "git push -- origin fix/1-some-fix",
        'git commit -m "never git push --force to main"',
        "git commit -F - <<'EOF'\nchore: note\n\ngit push -f is blocked\nEOF",
        "cat > notes.md <<'EOF'\ngit push origin main is blocked\nEOF",
        "gh pr create --body-file - <<-EOF\n\tgit push origin main\n\tEOF",
        "git commit -m \"$(cat <<'EOF'\ngit push --force\nEOF\n)\"",
        "# git push -f is blocked\ngit status",
        "bash -c 'git push origin fix/1-some-fix'",
        "bash scripts/push.sh",
        "git log --grep push",
        "echo push",
        "ls",
    ],
)
def test_other_commands_pass_through(repo, command):
    assert _decision(_guard(repo, command)) == "allow"


def test_bare_push_of_compliant_current_branch_passes(repo):
    _git(repo, "checkout", "-b", "fix/1-some-fix")
    assert _decision(_guard(repo, "git push")) == "allow"
    assert _decision(_guard(repo, "git push -u origin HEAD")) == "allow"


def test_block_wins_over_ask(repo):
    result = _guard(repo, "git push origin wip && git push -f origin fix/1-some-fix")
    assert _decision(result) == "block"


def test_deeply_nested_shells_are_blocked(repo):
    command = "git push origin fix/1-some-fix"
    for _ in range(5):
        command = f"bash -c {shlex.quote(command)}"
    result = _guard(repo, command)
    assert _decision(result) == "block"
    assert "too deeply" in result.stderr


def test_unbalanced_quotes_still_checked(repo):
    assert _decision(_guard(repo, "git push -f origin fix/1-some-fix 'oops")) == "block"


def test_unreadable_input_without_a_visible_push_passes():
    assert _decision(_run_hook("guard_git_push.py", "not json")) == "allow"
    assert _decision(_run_hook("guard_git_push.py", {"tool_input": {}})) == "allow"


def test_guard_fails_closed_for_a_push_it_cannot_check():
    # A non-string cwd makes the guard raise while checking the push.
    payload = {"tool_input": {"command": "git push"}, "cwd": 123}
    result = _run_hook("guard_git_push.py", payload)
    assert _decision(result) == "block"
    assert "could not check" in result.stderr


@pytest.mark.parametrize("script", ["guard_git_push.py", "check_python_lint.py"])
def test_hooks_parse_as_python_3_10(script):
    # Claude Code runs the hooks with whatever python3 is installed, not the Dockerfile's Python.
    source = (HOOKS / script).read_text()
    ast.parse(source, filename=script, feature_version=(3, 10))
    assert source.startswith("#!/usr/bin/env python3\n")


# --- check_python_lint.py -----------------------------------------------------------------------

requires_ruff = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is required")


@pytest.fixture
def lint_root(tmp_path):
    root = tmp_path / "project"
    (root / ".linter-rules").mkdir(parents=True)
    shutil.copy(REPO_ROOT / ".linter-rules" / ".ruff.toml", root / ".linter-rules" / ".ruff.toml")
    return root


def _lint(root, file_path, env_path=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    if env_path is not None:
        env["PATH"] = env_path
    payload = {"tool_input": {"file_path": str(file_path)}, "cwd": str(root)}
    return _run_hook("check_python_lint.py", payload, env=env)


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
