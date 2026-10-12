"""Regression checks for the mutation workflow's badge-only push guard."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "mutation-badge-only-push.sh"
BADGE = ".github/badges/mutation.json"
SUBJECT = "mutation: update mutation score badge"


def git(repo, *args):
    result = subprocess.run(  # noqa: S603 - fixed git invocation in a temp repo
        ["git", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit(repo, files, subject):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        git(repo, "add", name)
    git(repo, "commit", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    commit(tmp_path, {BADGE: "0", "a.py": "0"}, "chore: base")
    return tmp_path


def skips(repo, before, after="HEAD"):
    after = git(repo, "rev-parse", after)
    result = subprocess.run(["bash", str(SCRIPT), before, after], cwd=repo, check=False)  # noqa: S603, S607
    return result.returncode == 0


def test_badge_only_commit_is_skipped(repo):
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, {BADGE: "1"}, f"{SUBJECT} (#7)")
    assert skips(repo, base)


def test_normal_commit_is_not_skipped(repo):
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, {"a.py": "1"}, "fix: something")
    assert not skips(repo, base)


def test_badge_file_with_other_subject_is_not_skipped(repo):
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, {BADGE: "1"}, "chore: update mutation results")
    assert not skips(repo, base)


def test_mutation_subject_touching_other_files_is_not_skipped(repo):
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, {BADGE: "1", "a.py": "1"}, SUBJECT)
    assert not skips(repo, base)


def test_mixed_push_is_not_skipped(repo):
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, {BADGE: "1"}, SUBJECT)
    commit(repo, {"a.py": "1"}, "feat: real work")
    assert not skips(repo, base)


def test_unknown_or_zero_before_is_not_skipped(repo):
    commit(repo, {BADGE: "1"}, SUBJECT)
    assert not skips(repo, "0" * 40)
    assert not skips(repo, "1" * 40)


def test_diverged_history_is_not_skipped(repo):
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "other")
    old_tip = commit(repo, {BADGE: "2"}, "fix: abandoned work")
    git(repo, "checkout", "-q", "-")
    git(repo, "reset", "-q", "--hard", base)
    commit(repo, {BADGE: "1"}, SUBJECT)
    # Both SHAs exist and only the badge differs between them (so the commit
    # and diff checks alone would pass), but the old tip is not its ancestor (a force push), so it must not skip.
    assert not skips(repo, old_tip)


TESTED_SCRIPT = REPO_ROOT / ".github" / "scripts" / "mutation-tested-push.sh"


def mutation_tested(repo, tmp_path, pulls, runs, before="0" * 40):
    """Run mutation-tested-push.sh with a stub `gh` serving canned API output."""
    stub = tmp_path / "bin"
    stub.mkdir(parents=True)
    (stub / "gh").write_text(
        '#!/usr/bin/env bash\ncase "$2" in\n'
        f"  */pulls) echo '{pulls}' ;;\n"
        f"  *runs*) echo '{runs}' ;;\nesac\n"
    )
    (stub / "gh").chmod(0o755)
    after = git(repo, "rev-parse", "HEAD")
    env = {"PATH": f"{stub}:/usr/bin:/bin", "GITHUB_REPOSITORY": "o/r", "GH_TOKEN": "x"}
    cmd = ["bash", str(TESTED_SCRIPT), before, after]
    return subprocess.run(cmd, cwd=repo, env=env, check=False).returncode == 0  # noqa: S603


def test_runs_when_merged_pr_has_successful_mutation_run(repo, tmp_path):
    # Squash merge: the PR head SHA differs from the commit on main; the head is used.
    assert mutation_tested(repo, tmp_path / "a", "headsha", "1")


def test_not_run_without_pr_or_successful_mutation_run(repo, tmp_path):
    assert not mutation_tested(repo, tmp_path / "b", "", "1")  # no merged PR for the commit
    assert not mutation_tested(repo, tmp_path / "c", "headsha", "0")  # no successful run
