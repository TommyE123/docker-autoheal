"""Contract checks for the Release Please integration.

Release Please itself owns Conventional-Commits parsing and SemVer
calculation - these tests don't reimplement or re-verify that. They pin
down the handful of things this repository's own configuration and
workflow must get right: the bootstrap point, the starting version, and
that Docker publishing is gated on - and consumes - Release Please's own
output rather than recalculating anything.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "release-please.yml").read_text(encoding="utf-8")
AUTO_MERGE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "release-please-auto-merge.yml"
).read_text(encoding="utf-8")


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

    # release-please bumps this on every Release PR, so pin the shape (a
    # real SemVer, not a fresh-repo default) rather than a specific version -
    # a literal here would fail on every open Release PR by design.
    version = manifest["."]
    assert version not in ("0.0.0", "0.1.0")
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)


def test_version_file_matches_the_manifest():
    # The "simple" release-type maintains version.txt as its version file -
    # it must exist and agree with the manifest, or release-please's next
    # bump would be calculated from the wrong starting point.
    manifest = json.loads((REPO_ROOT / ".release-please-manifest.json").read_text())
    assert (REPO_ROOT / "version.txt").read_text(encoding="utf-8").strip() == manifest["."]


def test_docker_job_only_runs_when_a_release_was_actually_created():
    assert "needs.release-please.outputs.release_created == 'true'" in WORKFLOW


def test_beta_job_runs_after_release_please_regardless_of_release_creation():
    beta_job = re.search(
        r"(?ms)^  beta-build:\n(.*?)(?=^  [\w-]+:\n|\Z)", WORKFLOW
    ).group(1)

    assert re.search(r"^    needs: release-please$", beta_job, re.MULTILINE)
    assert "release_created" not in beta_job


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


def test_beta_job_only_keeps_beta_on_docker_hub_and_prunes_old_ghcr_beta_tags():
    assert "type=raw,value=beta" in WORKFLOW
    assert "type=raw,value=beta-{{sha}}" in WORKFLOW
    assert "delete-tags:" in WORKFLOW
    assert "beta-[0-9a-f]{7}" in WORKFLOW
    assert "keep-n-tagged: 20" in WORKFLOW
    assert "exclude-tags:" in WORKFLOW
    assert "^beta$|^latest$" in WORKFLOW
    assert "steps.meta-dockerhub.outputs.tags" in WORKFLOW
    assert "steps.meta-ghcr.outputs.tags" in WORKFLOW


def test_release_please_uses_a_non_default_token_so_its_pr_gets_normal_checks():
    # The default GITHUB_TOKEN is deliberately prevented by GitHub from
    # triggering other workflow runs, so a Release PR authored with it never
    # gets validate-title/unit-tests run and can never satisfy Protect Main.
    assert "token: ${{ secrets.RELEASE_PLEASE_TOKEN }}" in WORKFLOW


def test_weekly_workflow_schedules_for_friday_3pm_uk_time_and_supports_manual_dispatch():
    # The timezone field makes GitHub evaluate this cron as Europe/London
    # wall-clock time, so it stays 15:00 UK local across the GMT/BST
    # changeover without a separate runtime guard.
    assert '- cron: "0 15 * * 5"' in AUTO_MERGE_WORKFLOW
    assert 'timezone: "Europe/London"' in AUTO_MERGE_WORKFLOW
    assert "workflow_dispatch:" in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_has_a_race_safe_concurrency_group():
    assert "group: release-please-auto-merge" in AUTO_MERGE_WORKFLOW
    assert "cancel-in-progress: false" in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_matches_the_release_pr_by_repository_specific_characteristics():
    # Title/version is explicitly excluded as the selector since it changes
    # every release; match on the PR's stable, repository-specific shape.
    assert '--base main --state open --label "autorelease: pending"' in AUTO_MERGE_WORKFLOW
    assert '.headRefName == "release-please--branches--main"' in AUTO_MERGE_WORKFLOW
    assert ".headRepositoryOwner.login == $owner" in AUTO_MERGE_WORKFLOW
    assert ".headRepository.name == $repo" in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_does_not_match_on_author():
    # release-please.yml authenticates with a PAT (RELEASE_PLEASE_TOKEN), so
    # the Release PR is authored by that PAT's account, not
    # github-actions[bot]. Matching on author would silently stop finding
    # the PR the moment that token started being used.
    assert ".author.login" not in AUTO_MERGE_WORKFLOW
    assert "number,author," not in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_fails_safely_on_multiple_matches_without_merging():
    assert 'count" -eq 1' in AUTO_MERGE_WORKFLOW
    assert "exit 1" in AUTO_MERGE_WORKFLOW
    assert "expected at most 1" in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_is_idempotent_when_auto_merge_already_enabled():
    assert "autoMergeRequest != null" in AUTO_MERGE_WORKFLOW
    assert "already_enabled" in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_delegates_to_native_auto_merge_only():
    # Must enable native auto-merge and get out of the way - no polling,
    # no manual merge, no re-implementation of check/approval logic.
    assert "gh pr merge" in AUTO_MERGE_WORKFLOW
    assert "--auto" in AUTO_MERGE_WORKFLOW
    assert "--squash" in AUTO_MERGE_WORKFLOW
    assert "sleep" not in AUTO_MERGE_WORKFLOW
    assert "while" not in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_uses_least_privilege_permissions():
    assert "pull-requests: write" in AUTO_MERGE_WORKFLOW
    assert "contents: write" not in AUTO_MERGE_WORKFLOW


def test_weekly_workflow_enables_auto_merge_with_the_non_default_token():
    # gh pr merge --auto authenticates via GH_TOKEN. The default
    # GITHUB_TOKEN can have its resulting merge-completion push suppressed
    # from triggering release-please.yml's own push trigger - the same
    # class of problem release-please.yml itself was fixed for.
    assert "GH_TOKEN: ${{ secrets.RELEASE_PLEASE_TOKEN }}" in AUTO_MERGE_WORKFLOW
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" not in AUTO_MERGE_WORKFLOW
