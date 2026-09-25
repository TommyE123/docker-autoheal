"""Contract checks for the Release Please integration.

Release Please itself owns Conventional-Commits parsing and SemVer
calculation - these tests don't reimplement or re-verify that. They pin
down the handful of things this repository's own configuration and
workflow must get right: the bootstrap point, the starting version, and
that Docker publishing is gated on - and consumes - Release Please's own
output rather than recalculating anything.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "release-please.yml").read_text(encoding="utf-8")


def _extract_jq_program(after: str) -> str:
    """Pull one of the GHCR cleanup job's jq programs out of WORKFLOW verbatim,
    so a test that runs it can't drift from what the workflow actually executes.
    """
    start = WORKFLOW.index(after) + len(after)
    end = WORKFLOW.index("\n          ')", start)
    return WORKFLOW[start:end]


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


def test_beta_cleanup_docker_hub_calls_fail_on_http_errors():
    # curl's own -sS silences progress output but does not turn HTTP 4xx/5xx
    # responses into a non-zero exit code - only -f/--fail does that. Without
    # it, an auth or delete failure would be silently swallowed.
    assert 'curl -sS -f -X POST "https://hub.docker.com/v2/auth/token"' in WORKFLOW
    assert 'curl -sS -f -H "Authorization: Bearer ${jwt}" "$url"' in WORKFLOW
    assert "curl -sS -f -X DELETE" in WORKFLOW


def test_beta_cleanup_uses_the_pat_compatible_docker_hub_token_route():
    # /v2/users/login is deprecated, and a token it issues from a personal
    # access token (rather than a real password) is rejected by other Hub
    # APIs - including the tag list/delete calls this job depends on
    # (docker/hub-feedback#2438, #2006). /v2/auth/token is the current,
    # PAT-compatible route and returns `access_token` rather than `token`.
    assert "'{identifier: $id, secret: $secret}'" in WORKFLOW
    assert "| jq -r '.access_token')" in WORKFLOW
    assert 'curl -sS -f -X POST "https://hub.docker.com/v2/users/login"' not in WORKFLOW


def test_beta_cleanup_validates_the_docker_hub_login_token():
    assert 'if [ -z "$jwt" ] || [ "$jwt" = "null" ]; then' in WORKFLOW


def test_beta_cleanup_ghcr_uses_the_correct_route_for_org_owned_packages():
    # The GHCR package-versions API has separate routes for a user-owned vs.
    # an organization-owned package. Hardcoding the /users/ route would 404
    # on an org-owned repository. There's no github.* context value for
    # this (github.repository_owner_type doesn't exist - actionlint rejects
    # it), so the workflow must ask the REST API directly instead.
    assert 'github.repository_owner_type' not in WORKFLOW
    assert 'owner_type=$(gh api "users/${GHCR_OWNER}" --jq \'.type\')' in WORKFLOW
    assert 'if [ "$owner_type" = "Organization" ]; then' in WORKFLOW
    assert 'base="/orgs/${GHCR_OWNER}/packages/container/${package}"' in WORKFLOW
    assert 'base="/users/${GHCR_OWNER}/packages/container/${package}"' in WORKFLOW
    assert '"${base}/versions?per_page=100&page=${page}"' in WORKFLOW
    assert '"${base}/versions/${id}"' in WORKFLOW


def test_beta_cleanup_delete_loops_tolerate_individual_failures():
    # Both loops run under `set -euo pipefail` - without an explicit `||`,
    # one 404 (already-deleted version/tag from a concurrent run) or
    # transient 5xx would abort the loop and leave later, still-valid
    # deletions undone.
    assert (
        'gh api --method DELETE "${base}/versions/${id}" \\\n'
        '              || echo "::warning::failed to delete GHCR version ${id}, will retry next run"'
        in WORKFLOW
    )
    assert (
        '"https://hub.docker.com/v2/repositories/${DOCKERHUB_USERNAME}/${repo}/tags/${tag}/" \\\n'
        '              || echo "::warning::failed to delete Docker Hub tag ${tag}, will retry next run"'
        in WORKFLOW
    )


def test_beta_cleanup_ghcr_retention_accounts_for_the_protected_version():
    # The current beta-build push always tags one GHCR package version with
    # both `beta` and `beta-<sha>`. That version is (correctly) never a
    # deletion candidate, but its beta-<sha> tag still occupies one slot of
    # BETA_TAGS_TO_KEEP - so the deletable candidates must only keep
    # (keep - protected_count), not the full keep count, or retention becomes
    # one tag too generous.
    assert "protected_count=$(echo \"$versions\" | jq '" in WORKFLOW
    assert "effective_keep=$((keep - protected_count))" in WORKFLOW
    assert '[ "$effective_keep" -lt 0 ] && effective_keep=0' in WORKFLOW
    assert "--argjson keep \"$effective_keep\"" in WORKFLOW


def test_beta_cleanup_ghcr_jq_filters_compute_the_right_deletions():
    # The tests above only check that the retention logic's text is present -
    # they can't catch a broken jq predicate or off-by-one in the actual
    # filters. This executes the real programs (extracted from WORKFLOW, so
    # they can't drift) against a fixture mirroring the GHCR versions API.
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")

    protected_count_program = _extract_jq_program('protected_count=$(echo "$versions" | jq \'')
    to_delete_program = _extract_jq_program(
        'to_delete=$(echo "$versions" | jq -r --argjson keep "$effective_keep" \''
    )

    def version(version_id, tags, created_at):
        return {"id": version_id, "created_at": created_at, "metadata": {"container": {"tags": tags}}}

    # One version currently carries both `beta` and a `beta-<sha>` tag (the
    # latest beta-build push) - protected. 25 older, beta-only versions.
    # One real release version and one untagged (multi-arch child) version -
    # both must never be touched regardless of age or count.
    versions = [version(0, ["beta", "beta-aaaaaaa"], "2026-01-26T00:00:00Z")]
    versions += [version(i, [f"beta-{i:07x}"], f"2026-01-{i + 1:02d}T00:00:00Z") for i in range(1, 26)]
    versions.append(version(100, ["v1.2.3"], "2025-01-01T00:00:00Z"))
    versions.append(version(101, [], "2025-01-01T00:00:00Z"))
    versions_json = json.dumps(versions)

    def run_jq(program, *args):
        result = subprocess.run(
            ["jq", *args, program],
            input=versions_json,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    protected_count = int(run_jq(protected_count_program).strip())
    assert protected_count == 1

    keep = 20
    effective_keep = max(keep - protected_count, 0)
    assert effective_keep == 19

    to_delete_ids = {int(x) for x in run_jq(to_delete_program, "-r", "--argjson", "keep", str(effective_keep)).split()}
    # The 6 oldest of the 25 beta-only versions (25 - effective_keep=19).
    assert to_delete_ids == {1, 2, 3, 4, 5, 6}
    assert 0 not in to_delete_ids  # protected beta + beta-<sha> version
    assert 100 not in to_delete_ids  # release version
    assert 101 not in to_delete_ids  # untagged version

    all_beta_only_ids = {int(x) for x in run_jq(to_delete_program, "-r", "--argjson", "keep", "0").split()}
    assert all_beta_only_ids == set(range(1, 26))


def test_beta_cleanup_docker_hub_jq_filter_computes_the_right_deletions():
    # Same rationale as the GHCR test above: this executes the real Docker
    # Hub retention filter (extracted from WORKFLOW) against a fixture
    # mirroring the Hub tags API, rather than only asserting the text exists.
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")

    to_delete_program = _extract_jq_program(
        'to_delete=$(echo "$tags" | jq -r --argjson keep "$keep" \''
    )

    def tag(name, last_updated):
        return {"name": name, "last_updated": last_updated}

    # 25 beta-<sha> tags plus the mutable `beta` tag and a release tag, which
    # must never be touched regardless of age.
    tags = [tag(f"beta-{i:07x}", f"2026-01-{i + 1:02d}T00:00:00Z") for i in range(25)]
    tags.append(tag("beta", "2026-01-26T00:00:00Z"))
    tags.append(tag("v1.2.3", "2025-01-01T00:00:00Z"))
    tags_json = json.dumps(tags)

    def run_jq(program, *args):
        result = subprocess.run(
            ["jq", *args, program],
            input=tags_json,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    to_delete_names = set(run_jq(to_delete_program, "-r", "--argjson", "keep", "20").split())
    # The 5 oldest of the 25 beta-<sha> tags (25 - keep=20).
    assert to_delete_names == {f"beta-{i:07x}" for i in range(5)}
    assert "beta" not in to_delete_names
    assert "v1.2.3" not in to_delete_names
