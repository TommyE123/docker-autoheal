"""Contract checks for the Release Please integration.

Release Please itself owns Conventional-Commits parsing and SemVer
calculation - these tests don't reimplement or re-verify that. They pin
down the handful of things this repository's own configuration and
workflow must get right: the bootstrap point, the starting version, and
that Docker publishing is gated on - and consumes - Release Please's own
output rather than recalculating anything.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "release-please.yml").read_text(encoding="utf-8")


def test_config_bootstraps_from_the_last_real_release_commit():
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text())

    # This is the commit tagged v2.0.16 - the actual last production release.
    # Bootstrapping here (not at the repo's first commit) stops release-please
    # from treating years of existing history as unreleased changes.
    assert config["bootstrap-sha"] == "437dd523de66735bedf72d1e90d325fde88fff46"
    assert config["packages"]["."]["release-type"] == "simple"

    # Release notes live on GitHub Releases, not a committed CHANGELOG.md.
    assert config["skip-changelog"] is True

    expected_sections = {
        "feat": "Features",
        "fix": "Bug Fixes",
        "deps": "Dependencies",
        "perf": "Performance Improvements",
        "revert": "Reverts",
        "chore": "Chores",
        "docs": "Documentation",
        "style": "Styles",
        "refactor": "Refactors",
        "test": "Tests",
        "build": "Build System",
        "ci": "Continuous Integration",
    }

    actual_sections = {
        section["type"]: section["section"]
        for section in config["changelog-sections"]
    }

    assert actual_sections == expected_sections


def test_manifest_starts_from_the_actual_last_released_version():
    manifest = json.loads((REPO_ROOT / ".release-please-manifest.json").read_text())

    # Must never look like a fresh repo starting at 0.0.0/0.1.0.
    assert manifest["."] == "2.0.16"


def test_version_file_matches_the_manifest():
    # The "simple" release-type maintains version.txt as its version file -
    # it must exist and agree with the manifest, or release-please's next
    # bump would be calculated from the wrong starting point.
    assert (REPO_ROOT / "version.txt").read_text(encoding="utf-8").strip() == "2.0.16"


def test_docker_job_only_runs_when_a_release_was_actually_created():
    assert "needs.release-please.outputs.release_created == 'true'" in WORKFLOW


def test_docker_job_consumes_the_release_please_tag_not_its_own_calculation():
    assert "type=raw,value=${{ needs.release-please.outputs.tag_name }}" in WORKFLOW
    assert "type=raw,value=latest" in WORKFLOW
    # No independent version math (git tag/describe based calculation) left behind.
    assert "git tag" not in WORKFLOW
    assert "git describe" not in WORKFLOW


def test_release_please_and_docker_publish_are_one_workflow_run():
    # Same-workflow job gating (needs:/if:), not a second workflow waiting on
    # a tag/release event - see the workflow's own comments for why.
    assert "on:\n  push:\n    branches:\n      - main" in WORKFLOW
    assert "needs: release-please" in WORKFLOW


def test_docker_publishing_targets_are_unchanged():
    assert "docker.io/${{ secrets.DOCKERHUB_USERNAME }}/docker-autoheal" in WORKFLOW
    assert "ghcr.io/${{ github.repository_owner }}/docker-autoheal" in WORKFLOW
    assert "linux/amd64,linux/arm64" in WORKFLOW


def test_release_please_runs_on_the_friday_schedule():
    assert 'cron: "0 13 * * 5"' in WORKFLOW


def test_auto_merge_step_only_runs_on_the_scheduled_event():
    assert "if: github.event_name == 'schedule'" in WORKFLOW


def test_auto_merge_falls_back_to_the_release_branch_when_release_please_output_is_empty():
    # steps.release.outputs.pr is only populated when Release Please
    # created/updated the PR in *this* run. An existing Release PR left
    # unchanged (no release-worthy commits since it was opened) must still
    # be found and merged on the scheduled run, not silently skipped.
    assert (
        'gh pr list --repo "$REPO" \\\n'
        '              --head "release-please--branches--main" --base main --state open'
        in WORKFLOW
    )


def test_auto_merge_fallback_lookup_excludes_fork_prs():
    # `gh pr list --head <branch>` matches on branch name alone across every
    # fork, and `--head owner:branch` isn't supported by the CLI - so a
    # same-named fork PR (gh pr list returns the most recently created match
    # first) could otherwise outrank the real Release PR and be picked
    # instead. The fallback must also pin the head repository to this repo.
    assert "headRepositoryOwner,headRepository" in WORKFLOW
    assert '.headRepositoryOwner.login == $owner and .headRepository.nameWithOwner == $repo' in WORKFLOW


def test_auto_merge_checks_the_autorelease_pending_label_before_merging():
    assert "--json labels --jq" in WORKFLOW
    assert 'index("autorelease: pending")' in WORKFLOW


def test_auto_merge_uses_native_github_auto_merge():
    assert 'gh pr merge "$pr_number" --repo "$REPO" --auto --squash' in WORKFLOW
