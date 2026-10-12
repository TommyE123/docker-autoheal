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


def mutation_tested(repo, tmp_path, heads, runs, before="0" * 40):
    """Run mutation-tested-push.sh with a stub `gh`.

    ``heads`` maps a main commit SHA to its merged PR head SHA, ``runs`` maps a
    PR head SHA to its successful Mutation Testing run count.
    """
    stub = tmp_path / "bin"
    stub.mkdir(parents=True)
    cases = "".join(f"  *commits/{sha}/pulls) echo '{head}' ;;\n" for sha, head in heads.items())
    cases += "".join(f"  *\"head_sha={head}&\"*) echo '{n}' ;;\n" for head, n in runs.items())
    (stub / "gh").write_text(f'#!/usr/bin/env bash\ncase "$2" in\n{cases}  *) ;;\nesac\n')
    (stub / "gh").chmod(0o755)
    after = git(repo, "rev-parse", "HEAD")
    env = {"PATH": f"{stub}:/usr/bin:/bin", "GITHUB_REPOSITORY": "o/r", "GH_TOKEN": "x"}
    cmd = ["bash", str(TESTED_SCRIPT), before, after]
    return subprocess.run(cmd, cwd=repo, env=env, check=False).returncode == 0  # noqa: S603


def test_runs_when_merged_pr_has_successful_mutation_run(repo, tmp_path):
    # Squash merge: the PR head SHA differs from the commit on main; the head is used.
    tip = git(repo, "rev-parse", "HEAD")
    assert mutation_tested(repo, tmp_path / "a", {tip: "headsha"}, {"headsha": 1})


def test_not_run_without_pr_or_successful_mutation_run(repo, tmp_path):
    tip = git(repo, "rev-parse", "HEAD")
    assert not mutation_tested(repo, tmp_path / "b", {}, {"headsha": 1})  # no merged PR
    assert not mutation_tested(repo, tmp_path / "c", {tip: "headsha"}, {"headsha": 0})  # no run


def test_tested_commit_followed_by_untested_commit_is_not_run(repo, tmp_path):
    base = git(repo, "rev-parse", "HEAD")
    tested = commit(repo, {"a.py": "1"}, "fix: tested change (#1)")
    commit(repo, {"a.py": "2"}, "feat: untested change (#2)")
    heads, runs = {tested: "head1"}, {"head1": 1}
    assert not mutation_tested(repo, tmp_path / "d", heads, runs, before=base)


def test_all_commits_tested_is_run_and_badge_commits_are_exempt(repo, tmp_path):
    base = git(repo, "rev-parse", "HEAD")
    first = commit(repo, {"a.py": "1"}, "fix: one (#1)")
    commit(repo, {BADGE: "1"}, f"{SUBJECT} (#2)")
    second = commit(repo, {"a.py": "2"}, "fix: two (#3)")
    heads = {first: "h1", second: "h3"}
    assert mutation_tested(repo, tmp_path / "e", heads, {"h1": 1, "h3": 1}, before=base)
    assert not mutation_tested(repo, tmp_path / "f", heads, {"h1": 1}, before=base)
