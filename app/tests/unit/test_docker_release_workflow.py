"""Structural checks for the SemVer-based Docker release workflow.

The actual Conventional-Commits-to-SemVer calculation is delegated to the
established `mathieudutour/github-tag-action` (itself built on
`@semantic-release/commit-analyzer`), so these tests do not reimplement that
logic. They verify that this repository's workflow wires that tool's output
into the existing Docker Hub/GHCR/multi-arch/latest publishing correctly, and
that a release is only produced from it - never guessed independently.
"""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "docker-release.yml"


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def steps_by_name(workflow: dict) -> dict[str, dict]:
    return {step["name"]: step for step in workflow["jobs"]["release"]["steps"]}


class TestVersionCalculation:
    def test_uses_an_established_semver_action_pinned_by_full_sha(self):
        steps = steps_by_name(load_workflow())
        tag_step = steps["Determine next SemVer version"]

        assert tag_step["uses"].startswith("mathieudutour/github-tag-action@"), (
            "version calculation must come from the established "
            "Conventional-Commits/SemVer action, not custom logic"
        )
        sha = tag_step["uses"].split("@", 1)[1].split(" ", 1)[0]
        assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), (
            "third-party actions must be pinned by a full commit SHA, "
            f"matching this repo's convention; got {sha!r}"
        )

    def test_no_bump_when_no_conventional_commit_matches(self):
        tag_step = steps_by_name(load_workflow())["Determine next SemVer version"]

        assert tag_step["with"]["default_bump"] is False, (
            "a push with no fix/feat/breaking-change commit (docs, chore, "
            "ci, test, style, refactor, ...) must not produce a release"
        )

    def test_only_releases_from_the_main_branch(self):
        tag_step = steps_by_name(load_workflow())["Determine next SemVer version"]

        assert tag_step["with"]["release_branches"] == "main"


class TestExistingReleaseRetrySafety:
    def test_an_existing_tag_on_this_commit_is_reused_not_recalculated(self):
        steps = steps_by_name(load_workflow())
        detect = steps["Detect existing release for current commit"]
        calculate = steps["Determine next SemVer version"]

        assert "git tag --points-at" in detect["run"]
        assert calculate["if"] == "steps.existing.outputs.found != 'true'", (
            "recalculating a version on a commit that is already tagged "
            "would risk skipping past its own tag"
        )

    def test_detected_tag_matches_semver_format(self):
        detect = steps_by_name(load_workflow())["Detect existing release for current commit"]

        assert r"^v[0-9]+\.[0-9]+\.[0-9]+$" in detect["run"], (
            "the retry-safety check must only recognise valid vMAJOR.MINOR.PATCH tags"
        )

    def test_resolve_step_prefers_existing_tag_over_a_newly_calculated_one(self):
        resolve = steps_by_name(load_workflow())["Resolve release version"]

        assert resolve["run"].strip().startswith('VERSION="${EXISTING_TAG:-$NEW_TAG}"')


class TestReleaseGating:
    """Every publishing step must be skipped when no version was resolved."""

    GATED_STEPS = (
        "Set up QEMU",
        "Set up Docker Buildx",
        "Login to Docker Hub",
        "Login to GHCR",
        "Extract metadata",
        "Build and push Docker image",
        "Create GitHub release",
        "Update Docker Hub description",
    )

    def test_every_publishing_step_is_gated_on_a_resolved_version(self):
        steps = steps_by_name(load_workflow())
        for name in self.GATED_STEPS:
            assert steps[name]["if"] == "steps.resolve.outputs.version != ''", (
                f"{name!r} must not run unless a release version was resolved"
            )


class TestExistingPublishingIsUnchanged:
    def test_image_names_and_registries_are_unchanged(self):
        meta = steps_by_name(load_workflow())["Extract metadata"]
        images = meta["with"]["images"]

        assert "docker.io/${{ secrets.DOCKERHUB_USERNAME }}/docker-autoheal" in images
        assert "ghcr.io/${{ github.repository_owner }}/docker-autoheal" in images

    def test_version_and_latest_tags_are_both_produced(self):
        meta = steps_by_name(load_workflow())["Extract metadata"]
        tags = meta["with"]["tags"]

        assert "type=raw,value=${{ steps.resolve.outputs.version }}" in tags
        assert "type=raw,value=latest" in tags

    def test_multi_arch_build_is_unchanged(self):
        build = steps_by_name(load_workflow())["Build and push Docker image"]

        assert build["with"]["platforms"] == "linux/amd64,linux/arm64"
        assert build["with"]["push"] is True

    def test_dockerhub_description_step_is_unchanged(self):
        description = steps_by_name(load_workflow())["Update Docker Hub description"]

        assert description["with"]["readme-filepath"] == "./DOCKER_HUB_README.md"


class TestWorkflowTriggerAndPermissions:
    def test_triggers_only_on_push_to_main(self):
        workflow = load_workflow()
        triggers = workflow[True] if True in workflow else workflow["on"]

        assert triggers["push"]["branches"] == ["main"]

    def test_release_publication_is_serialised(self):
        concurrency = load_workflow()["concurrency"]

        assert concurrency["group"] == "docker-publish-main"
        assert concurrency["cancel-in-progress"] is False

    def test_permissions_are_minimum_necessary(self):
        permissions = load_workflow()["permissions"]

        assert permissions == {"contents": "write", "packages": "write"}
