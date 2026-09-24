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

    expected_sections = {
        "feat": "✨ Features",
        "fix": "🐛 Bug Fixes",
        "deps": "📦 Dependencies",
        "perf": "⚡ Performance Improvements",
        "revert": "⏪ Reverts",
        "chore": "🧹 Chores",
        "docs": "📝 Documentation",
        "style": "🎨 Styles",
        "refactor": "♻️ Refactors",
        "test": "✅ Tests",
        "build": "🏗️ Build System",
        "ci": "👷 Continuous Integration",
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


def test_changelog_exists_for_release_please_to_maintain():
    # release-please appends to this file as part of every Release PR - it
    # must already exist so that process has something to extend.
    assert (REPO_ROOT / "CHANGELOG.md").exists()


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
