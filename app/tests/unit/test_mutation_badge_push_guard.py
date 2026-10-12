"""Regression checks for the mutation workflow's badge-only push guard."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "mutation-badge-only-push.sh"
BADGE = ".github/badges/mutation.json"
SUBJECT = "mutation: update mutation score badge"


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


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
    result = subprocess.run(["bash", str(SCRIPT), before, after], cwd=repo)
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
