"""Contract checks for the SemVer-based Docker release workflow.

The actual Conventional-Commits-to-SemVer calculation is delegated to the
established `mathieudutour/github-tag-action`, so these tests don't
reimplement that logic - they just pin down the handful of things this
repository's workflow must get right around it.
"""

from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "docker-release.yml"
).read_text(encoding="utf-8")


def test_uses_the_established_semver_action_pinned_by_full_sha():
    assert "mathieudutour/github-tag-action@a22cf08638b34d5badda920f9daf6e72c477b07b" in WORKFLOW


def test_calculates_in_dry_run_so_no_tag_is_created_before_publishing():
    assert "dry_run: true" in WORKFLOW


def test_non_release_commits_produce_no_release():
    assert "default_bump: false" in WORKFLOW


def test_only_releases_from_main():
    assert "release_branches: main" in WORKFLOW


def test_docker_tags_use_the_resolved_version_and_latest():
    assert "type=raw,value=${{ steps.resolve.outputs.version }}" in WORKFLOW
    assert "type=raw,value=latest" in WORKFLOW


def test_an_existing_tag_on_this_commit_is_reused_not_recalculated():
    assert "git tag --points-at" in WORKFLOW
    # the dry-run calculation step must be skipped once a tag already exists
    assert "if: steps.existing.outputs.found != 'true'" in WORKFLOW


def test_the_git_tag_is_only_created_after_the_image_is_published():
    # Match the actual step declarations, not just the words anywhere in the
    # file (e.g. in a comment), so a future edit that moves the real step
    # can't slip past this check while a stray comment keeps it passing.
    build_index = WORKFLOW.index("- name: Build and push Docker image")
    tag_index = WORKFLOW.index("- name: Create Git tag")

    assert build_index < tag_index, (
        "a release tag must never exist for an image that hasn't successfully built and pushed yet"
    )
    # and never re-created when this run is just resuming an existing release
    tag_step = WORKFLOW[tag_index : WORKFLOW.index("- name: Create GitHub release")]
    assert "steps.existing.outputs.found != 'true'" in tag_step
