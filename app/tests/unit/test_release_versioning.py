"""Unit tests for the release classification and version-safety tooling.

These cover ``scripts/release``, the single release controller's brain: what a
pull request's ``release:*`` label means, which version a release produces, and
the safety rules that stop a release tag ever being reused, moved or guessed.
"""

import json
from pathlib import Path

import pytest

from scripts.release import versioning
from scripts.release.cli import main
from scripts.release.versioning import (
    MergedPullRequest,
    ReleaseError,
    Version,
    classify,
    labels_at_merge_time,
    latest_release,
    plan_already_released,
    plan_from_labels,
    plan_maintenance,
    plan_resume,
    plan_version,
    validate_candidate,
)

EXISTING_TAGS = ["v2", "v2.0.0", "v2.0.1", "v2.0.2", "v2.0.3", "v2.0.4"]


def write(path: Path, payload: object) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestClassification:
    def test_single_label_is_the_release_type(self):
        assert classify(["bug", "release:minor"]) == "minor"

    def test_missing_label_is_rejected(self):
        with pytest.raises(ReleaseError, match="no release classification label"):
            classify(["bug", "documentation"])

    def test_multiple_labels_are_rejected(self):
        with pytest.raises(ReleaseError, match="more than one"):
            classify(["release:patch", "release:minor"])

    def test_invalid_label_is_rejected(self):
        with pytest.raises(ReleaseError, match="invalid release classification"):
            classify(["release:hotfix"])

    def test_duplicate_of_the_same_label_is_one_classification(self):
        assert classify(["release:patch", "release:patch"]) == "patch"


class TestVersionCalculation:
    def test_patch_release(self):
        assert Version.parse("v1.8.4").bump("patch") == Version(1, 8, 5)

    def test_minor_release(self):
        assert Version.parse("v1.8.4").bump("minor") == Version(1, 9, 0)

    def test_major_release(self):
        assert Version.parse("v1.8.4").bump("major") == Version(2, 0, 0)

    def test_release_none_produces_no_version(self):
        with pytest.raises(ReleaseError, match="does not produce a new version"):
            Version.parse("v1.8.4").bump("none")

    def test_invalid_release_tag_is_rejected(self):
        for tag in ("1.8.4", "v1.8", "v1.8.4-rc1", "v01.8.4", "latest", "v2"):
            with pytest.raises(ReleaseError, match="not a valid release tag"):
                Version.parse(tag)

    def test_latest_release_ignores_non_release_tags(self):
        assert latest_release(EXISTING_TAGS) == Version(2, 0, 4)

    def test_latest_release_orders_numerically_not_lexically(self):
        assert latest_release(["v2.0.9", "v2.0.10"]) == Version(2, 0, 10)

    def test_missing_release_tag_fails_closed(self):
        with pytest.raises(ReleaseError, match="could not determine the current release"):
            latest_release(["v2", "not-a-release"])

    def test_first_release_is_calculated_from_the_zero_base(self):
        plan = plan_version("minor", [], allow_first_release=True)

        assert plan.current == Version(0, 0, 0)
        assert plan.version == Version(0, 1, 0)
        assert plan.create_tag is True

    def test_version_does_not_depend_on_the_number_of_changes(self):
        for _ in range(3):
            assert plan_version("patch", EXISTING_TAGS).version == Version(2, 0, 5)


class TestCandidateValidation:
    def test_candidate_matching_the_requested_type_passes(self):
        validate_candidate(Version(1, 8, 4), Version(1, 8, 5), "patch", ["v1.8.4"])

    def test_candidate_for_another_release_type_is_rejected(self):
        with pytest.raises(ReleaseError, match="is not the major release"):
            validate_candidate(Version(1, 8, 4), Version(1, 9, 0), "major", ["v1.8.4"])

    def test_existing_candidate_tag_is_rejected(self):
        with pytest.raises(ReleaseError, match="already exists"):
            validate_candidate(Version(1, 8, 5), Version(2, 0, 0), "major", ["v1.8.5", "v2.0.0"])

    def test_planning_always_starts_from_the_latest_release_tag(self):
        # v2.0.0 exists, so it - not v1.8.5 - is the release a major bump
        # follows. The candidate is recalculated, never forced onto an
        # existing tag.
        plan = plan_version("major", ["v1.8.5", "v2.0.0"])

        assert plan.current == Version(2, 0, 0)
        assert plan.version == Version(3, 0, 0)

    def test_candidate_must_be_greater_than_the_current_release(self):
        with pytest.raises(ReleaseError, match="is not the patch release"):
            validate_candidate(Version(2, 0, 4), Version(2, 0, 3), "patch", ["v2.0.4"])


class TestPlanFromLabels:
    def test_patch_label_releases_immediately(self):
        plan = plan_from_labels(["release:patch"], EXISTING_TAGS)

        assert plan.version is not None
        assert (plan.release, plan.version.tag, plan.create_tag) == (
            True,
            "v2.0.5",
            True,
        )

    def test_minor_label_releases_immediately(self):
        assert plan_from_labels(["release:minor"], EXISTING_TAGS).version == Version(2, 1, 0)

    def test_major_label_releases_immediately(self):
        assert plan_from_labels(["release:major"], EXISTING_TAGS).version == Version(3, 0, 0)

    def test_release_none_does_not_release(self):
        plan = plan_from_labels(["release:none"], EXISTING_TAGS)

        assert plan.release is False
        assert plan.version is None
        assert plan.create_tag is False


class TestMaintenanceRelease:
    def test_no_unreleased_changes_produces_no_release(self):
        plan = plan_maintenance([], EXISTING_TAGS)

        assert plan.release is False
        assert plan.version is None
        assert "no unreleased release:none" in plan.reason

    def test_a_single_unreleased_change_produces_one_patch_release(self):
        plan = plan_maintenance([MergedPullRequest(101, ["release:none"])], EXISTING_TAGS)

        assert plan.version is not None
        assert (plan.release, plan.release_type, plan.version.tag) == (
            True,
            "patch",
            "v2.0.5",
        )

    def test_several_unreleased_changes_still_produce_one_patch_release(self):
        plan = plan_maintenance(
            [
                MergedPullRequest(101, ["release:none"]),
                MergedPullRequest(102, ["release:none"]),
                MergedPullRequest(103, ["release:none", "documentation"]),
            ],
            EXISTING_TAGS,
        )

        assert plan.version == Version(2, 0, 5)
        assert "#101, #102, #103" in plan.reason

    def test_changes_already_included_in_an_earlier_release_are_not_released_again(
        self,
    ):
        # The workflow only passes pull requests merged after the latest release
        # tag, so a release:none change swept up by an earlier release never
        # reaches the Friday sweep.
        assert plan_maintenance([], ["v2.0.5", "v2.0.6"]).release is False

    def test_pull_requests_without_the_none_label_are_ignored(self):
        plan = plan_maintenance([MergedPullRequest(104, ["documentation"])], EXISTING_TAGS)

        assert plan.release is False


class TestRetryAndConcurrency:
    def test_retry_reuses_the_tag_created_by_a_partial_attempt(self):
        plan = plan_from_labels(["release:patch"], EXISTING_TAGS + ["v2.0.5"], resume_tag="v2.0.5")

        assert plan.version is not None
        assert (plan.release, plan.version.tag, plan.create_tag) == (
            True,
            "v2.0.5",
            False,
        )

    def test_maintenance_retry_reuses_the_tag_of_the_partial_attempt(self):
        plan = plan_maintenance([], EXISTING_TAGS + ["v2.0.5"], resume_tag="v2.0.5")

        assert plan.version is not None
        assert (plan.release, plan.version.tag, plan.create_tag) == (
            True,
            "v2.0.5",
            False,
        )

    def test_retry_never_increments_the_version(self):
        plan = plan_from_labels(["release:major"], EXISTING_TAGS + ["v3.0.0"], resume_tag="v3.0.0")

        assert plan.version == Version(3, 0, 0)

    def test_resuming_a_tag_that_does_not_exist_fails_closed(self):
        with pytest.raises(ReleaseError, match="the tag does not exist"):
            plan_resume("v2.0.9", EXISTING_TAGS)

    def test_resuming_a_superseded_release_fails_closed(self):
        with pytest.raises(ReleaseError, match="is a newer release"):
            plan_resume("v2.0.4", EXISTING_TAGS + ["v2.0.5"])

    def test_release_none_is_never_turned_into_a_resumed_release(self):
        plan = plan_from_labels(["release:none"], EXISTING_TAGS + ["v2.0.5"], resume_tag="v2.0.5")

        assert plan.release is False

    def test_a_release_published_after_planning_blocks_the_second_release(self):
        # Two releases race: the first publishes v2.0.5, so the second must be
        # blocked at the release-time re-validation rather than reusing the tag.
        planned = plan_version("patch", EXISTING_TAGS)
        assert planned.version is not None
        published_by_the_other_release = EXISTING_TAGS + [planned.version.tag]

        with pytest.raises(ReleaseError, match="already exists"):
            validate_candidate(
                Version(2, 0, 4),
                planned.version,
                "patch",
                published_by_the_other_release,
            )


class TestAlreadyReleasedCommitIsANoOp:
    """Regression coverage: re-running the workflow on a commit that already
    has a *published* GitHub Release must never calculate a new version.

    This is distinct from resuming a partial failure (plan_resume): here the
    release already fully succeeded, so the only correct plan is "nothing to
    do" - not "the next patch/minor/major after this one".
    """

    def test_a_fully_released_commit_produces_no_new_release(self):
        plan = plan_already_released("v2.0.4", EXISTING_TAGS)

        assert plan.release is False
        assert plan.version is None
        assert plan.current == Version(2, 0, 4)
        assert "already released" in plan.reason

    def test_rerunning_classification_on_an_already_released_commit_is_a_no_op(self):
        # Without the already_released_tag guard this would classify the
        # merged PR's label again and calculate v2.0.5 - a second release for
        # a commit that was already fully published as v2.0.4.
        plan = plan_from_labels(["release:patch"], EXISTING_TAGS, already_released_tag="v2.0.4")

        assert plan.release is False
        assert plan.version is None

    def test_already_released_takes_priority_over_an_invalid_label(self):
        # Even a broken/duplicate classification on the merged PR must not
        # block or reinterpret an already-published commit - there is
        # nothing left to classify.
        plan = plan_from_labels(
            ["release:patch", "release:minor"],
            EXISTING_TAGS,
            already_released_tag="v2.0.4",
        )

        assert plan.release is False

    def test_already_released_takes_priority_over_a_resume_tag(self):
        plan = plan_from_labels(
            ["release:patch"],
            EXISTING_TAGS,
            resume_tag="v2.0.4",
            already_released_tag="v2.0.4",
        )

        assert plan.release is False

    def test_rerunning_a_maintenance_release_on_an_already_released_commit_is_a_no_op(
        self,
    ):
        # Without the guard this would find zero deferred PRs and legitimately
        # report "no release" anyway in most cases - but the guard makes the
        # no-op unconditional and independent of what release:none PRs exist,
        # so it holds even if that accounting is ever wrong.
        plan = plan_maintenance(
            [MergedPullRequest(101, ["release:none"])],
            EXISTING_TAGS,
            already_released_tag="v2.0.4",
        )

        assert plan.release is False

    def test_already_released_tag_must_exist(self):
        with pytest.raises(ReleaseError, match="does not exist"):
            plan_already_released("v2.0.9", EXISTING_TAGS)


class TestLabelsAtMergeTime:
    """Regression: label changes made after a PR merges must not silently alter
    the release classification.

    The release workflow reconstructs labels from the GitHub Issues Events API
    at the ``merged_at`` timestamp rather than reading current PR labels.  The
    event log is append-only, so replaying it up to that timestamp gives the
    immutable label state at the moment of merge.
    """

    _MERGE_TIME = "2024-01-15T10:00:00Z"

    def _events(self, *entries):
        return list(entries)

    def _labeled(self, name, at):
        return {"event": "labeled", "created_at": at, "label": {"name": name}}

    def _unlabeled(self, name, at):
        return {"event": "unlabeled", "created_at": at, "label": {"name": name}}

    def test_label_changed_after_merge_does_not_affect_classification(self):
        # The specific failure mode: PR was validated with release:minor,
        # then the label was changed to release:patch after merge.  The
        # classification must still be minor.
        events = [
            self._labeled("release:minor", "2024-01-14T09:00:00Z"),
            self._unlabeled("release:minor", "2024-01-16T11:00:00Z"),
            self._labeled("release:patch", "2024-01-16T11:01:00Z"),
        ]

        result = labels_at_merge_time(events, self._MERGE_TIME)

        assert result == ["release:minor"]
        assert "release:patch" not in result

    def test_label_present_at_merge_is_included(self):
        events = [self._labeled("release:patch", "2024-01-14T09:00:00Z")]

        assert labels_at_merge_time(events, self._MERGE_TIME) == ["release:patch"]

    def test_label_removed_before_merge_is_not_included(self):
        events = [
            self._labeled("release:minor", "2024-01-14T09:00:00Z"),
            self._unlabeled("release:minor", "2024-01-14T10:00:00Z"),
            self._labeled("release:patch", "2024-01-14T11:00:00Z"),
        ]

        result = labels_at_merge_time(events, self._MERGE_TIME)

        assert result == ["release:patch"]
        assert "release:minor" not in result

    def test_label_added_after_merge_is_excluded(self):
        events = [self._labeled("release:major", "2024-01-16T12:00:00Z")]

        assert labels_at_merge_time(events, self._MERGE_TIME) == []

    def test_non_label_events_are_ignored(self):
        events = [
            {"event": "merged", "created_at": "2024-01-15T10:00:00Z"},
            self._labeled("release:patch", "2024-01-14T09:00:00Z"),
            {"event": "review_requested", "created_at": "2024-01-14T08:00:00Z"},
            {"event": "commented", "created_at": "2024-01-14T07:00:00Z"},
        ]

        assert labels_at_merge_time(events, self._MERGE_TIME) == ["release:patch"]

    def test_events_at_exactly_merge_time_are_included(self):
        # A label event with created_at == merged_at is on the boundary;
        # it should be included, not excluded.
        events = [self._labeled("release:minor", self._MERGE_TIME)]

        assert labels_at_merge_time(events, self._MERGE_TIME) == ["release:minor"]

    def test_empty_event_log_returns_no_labels(self):
        assert labels_at_merge_time([], self._MERGE_TIME) == []

    def test_multiple_non_release_labels_are_preserved(self):
        events = [
            self._labeled("bug", "2024-01-14T08:00:00Z"),
            self._labeled("release:patch", "2024-01-14T09:00:00Z"),
            self._labeled("documentation", "2024-01-14T10:00:00Z"),
        ]

        result = labels_at_merge_time(events, self._MERGE_TIME)

        assert "release:patch" in result
        assert "bug" in result
        assert "documentation" in result

    def test_result_is_sorted(self):
        events = [
            self._labeled("z-label", "2024-01-14T08:00:00Z"),
            self._labeled("a-label", "2024-01-14T09:00:00Z"),
        ]

        result = labels_at_merge_time(events, self._MERGE_TIME)

        assert result == sorted(result)


class TestCommandLineInterface:
    def test_validate_pr_accepts_a_valid_classification(self, tmp_path, monkeypatch):
        output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))

        exit_code = main(
            [
                "validate-pr",
                "--labels-file",
                write(tmp_path / "labels.json", ["release:minor"]),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 0
        assert "version=v2.1.0" in output.read_text(encoding="utf-8")

    def test_validate_pr_rejects_a_missing_classification(self, tmp_path, capsys):
        exit_code = main(
            [
                "validate-pr",
                "--labels-file",
                write(tmp_path / "labels.json", ["documentation"]),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 1
        assert "::error::" in capsys.readouterr().err

    def test_labels_may_be_github_label_objects(self, tmp_path, monkeypatch):
        output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))

        exit_code = main(
            [
                "validate-pr",
                "--labels-file",
                write(tmp_path / "labels.json", [{"name": "release:patch"}]),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 0
        assert "version=v2.0.5" in output.read_text(encoding="utf-8")

    def test_tags_may_be_a_plain_newline_separated_list(self, tmp_path, monkeypatch):
        output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        tags = tmp_path / "tags.txt"
        tags.write_text("\n".join(EXISTING_TAGS) + "\n", encoding="utf-8")

        exit_code = main(
            [
                "validate-pr",
                "--labels-file",
                write(tmp_path / "labels.json", ["release:patch"]),
                "--tags-file",
                str(tags),
            ]
        )

        assert exit_code == 0
        assert "current_version=v2.0.4" in output.read_text(encoding="utf-8")

    def test_plan_maintenance_reports_no_release(self, tmp_path, monkeypatch):
        output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))

        exit_code = main(
            [
                "plan-maintenance",
                "--pull-requests-file",
                write(tmp_path / "prs.json", []),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 0
        assert "release=false" in output.read_text(encoding="utf-8")

    def test_plan_maintenance_deduplicates_pull_requests(self, tmp_path, monkeypatch):
        output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        pull_requests = [
            {"number": 101, "labels": [{"name": "release:none"}]},
            {"number": 101, "labels": [{"name": "release:none"}]},
        ]

        exit_code = main(
            [
                "plan-maintenance",
                "--pull-requests-file",
                write(tmp_path / "prs.json", pull_requests),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 0
        assert "1 unreleased release:none pull request(s): #101" in output.read_text(
            encoding="utf-8"
        )

    def test_plan_release_with_already_released_tag_is_a_no_op(self, tmp_path, monkeypatch):
        output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))

        exit_code = main(
            [
                "plan-release",
                "--labels-file",
                write(tmp_path / "labels.json", ["release:patch"]),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
                "--already-released-tag",
                "v2.0.4",
            ]
        )

        assert exit_code == 0
        result = output.read_text(encoding="utf-8")
        assert "release=false" in result
        assert "version=\n" in result or result.rstrip().endswith("version=")

    def test_plan_maintenance_with_already_released_tag_is_a_no_op(self, tmp_path, monkeypatch):
        output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        pull_requests = [{"number": 101, "labels": [{"name": "release:none"}]}]

        exit_code = main(
            [
                "plan-maintenance",
                "--pull-requests-file",
                write(tmp_path / "prs.json", pull_requests),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
                "--already-released-tag",
                "v2.0.4",
            ]
        )

        assert exit_code == 0
        assert "release=false" in output.read_text(encoding="utf-8")

    def test_verify_release_blocks_a_candidate_that_now_exists(self, tmp_path, capsys):
        exit_code = main(
            [
                "verify-release",
                "--version",
                "v2.0.5",
                "--release-type",
                "patch",
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS + ["v2.0.5"]),
            ]
        )

        assert exit_code == 1
        assert "already exists" in capsys.readouterr().err

    def test_verify_release_accepts_a_still_valid_candidate(self, tmp_path):
        exit_code = main(
            [
                "verify-release",
                "--version",
                "v2.0.5",
                "--release-type",
                "patch",
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 0

    def test_verify_release_requires_the_tag_when_resuming(self, tmp_path, capsys):
        exit_code = main(
            [
                "verify-release",
                "--version",
                "v2.0.5",
                "--create-tag",
                "false",
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_resolve_labels_outputs_labels_at_merge_time(self, tmp_path, capsys):
        # Regression: label changed after merge must not silently alter the
        # classification that the release workflow uses.
        events = [
            {"event": "labeled", "created_at": "2024-01-14T09:00:00Z",
             "label": {"name": "release:minor"}},
            {"event": "unlabeled", "created_at": "2024-01-16T11:00:00Z",
             "label": {"name": "release:minor"}},
            {"event": "labeled", "created_at": "2024-01-16T11:01:00Z",
             "label": {"name": "release:patch"}},
        ]

        exit_code = main(
            [
                "resolve-labels",
                "--events-file",
                write(tmp_path / "events.json", events),
                "--merged-at",
                "2024-01-15T10:00:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output == ["release:minor"]

    def test_resolve_labels_empty_events_returns_empty_array(self, tmp_path, capsys):
        exit_code = main(
            [
                "resolve-labels",
                "--events-file",
                write(tmp_path / "events.json", []),
                "--merged-at",
                "2024-01-15T10:00:00Z",
            ]
        )

        assert exit_code == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_resolve_labels_handles_multi_page_paginated_response(
        self, tmp_path, capsys
    ):
        # gh api --paginate writes one JSON array per page with no outer
        # wrapper, so a multi-page response is multiple arrays concatenated.
        # Without this fix json.loads raises "Extra data" on the second page.
        #
        # Failure scenario: a PR has enough label events to span two API
        # pages; the release workflow calls gh api ... --paginate, producing
        # two concatenated arrays in the events file; resolve-labels fails
        # with a JSONDecodeError and the release run aborts.
        page1 = [
            {"event": "labeled", "created_at": "2024-01-10T00:00:00Z",
             "label": {"name": "release:patch"}},
        ]
        page2 = [
            {"event": "unlabeled", "created_at": "2024-01-11T00:00:00Z",
             "label": {"name": "release:patch"}},
            {"event": "labeled", "created_at": "2024-01-12T00:00:00Z",
             "label": {"name": "release:none"}},
        ]
        events_file = tmp_path / "pr-events.json"
        # Write the two pages exactly as gh api --paginate would produce them.
        events_file.write_text(
            json.dumps(page1) + "\n" + json.dumps(page2), encoding="utf-8"
        )

        exit_code = main(
            [
                "resolve-labels",
                "--events-file",
                str(events_file),
                "--merged-at",
                "2024-01-15T00:00:00Z",
            ]
        )

        assert exit_code == 0
        assert json.loads(capsys.readouterr().out) == ["release:none"]

    def test_resolve_labels_events_out_of_order_uses_created_at(
        self, tmp_path, capsys
    ):
        # GitHub Issues Events API has no documented ordering guarantee.
        # If events arrive newest-first (reverse chronological), naive replay
        # produces the wrong label: applying unlabeled before labeled leaves
        # the wrong label in the set.
        #
        # Sequence of label changes:
        #   1. release:patch added
        #   2. release:patch removed
        #   3. release:minor added
        #   (PR merges — correct classification is release:minor)
        #
        # Failure scenario: API returns events in reverse order;
        # without sorting by created_at the loop sees unlabeled(patch) first
        # (which discards nothing), then labeled(minor), then labeled(patch),
        # yielding ["release:minor", "release:patch"] instead of
        # ["release:minor"].
        events_reversed = [
            {"event": "labeled", "created_at": "2024-01-12T00:00:00Z",
             "label": {"name": "release:minor"}},
            {"event": "unlabeled", "created_at": "2024-01-11T00:00:00Z",
             "label": {"name": "release:patch"}},
            {"event": "labeled", "created_at": "2024-01-10T00:00:00Z",
             "label": {"name": "release:patch"}},
        ]
        events_file = tmp_path / "pr-events.json"
        events_file.write_text(json.dumps(events_reversed), encoding="utf-8")

        exit_code = main(
            [
                "resolve-labels",
                "--events-file",
                str(events_file),
                "--merged-at",
                "2024-01-15T00:00:00Z",
            ]
        )

        assert exit_code == 0
        assert json.loads(capsys.readouterr().out) == ["release:minor"]

    def test_unreadable_input_fails_closed(self, tmp_path, capsys):
        exit_code = main(
            [
                "validate-pr",
                "--labels-file",
                str(tmp_path / "missing.json"),
                "--tags-file",
                write(tmp_path / "tags.json", EXISTING_TAGS),
            ]
        )

        assert exit_code == 1
        assert "::error::" in capsys.readouterr().err


class TestModuleContract:
    def test_only_the_four_release_labels_are_recognised(self):
        assert versioning.RELEASE_LABELS == (
            "release:none",
            "release:patch",
            "release:minor",
            "release:major",
        )


class TestReleaseWorkflows:
    """Guard the release workflow properties that the tooling cannot enforce."""

    @staticmethod
    def load(name):
        yaml = pytest.importorskip("yaml")
        workflow = Path(__file__).resolve().parents[3] / ".github/workflows" / name
        return yaml.safe_load(workflow.read_text(encoding="utf-8"))

    def test_release_is_the_only_controller_and_never_auto_patches_a_push(self):
        workflow = self.load("docker-release.yml")
        # PyYAML resolves the workflow's bare `on:` key to the boolean True.
        triggers = workflow[True]

        assert set(triggers) == {"push", "schedule", "workflow_dispatch"}
        assert triggers["push"]["branches"] == ["main"]
        # Friday maintenance sweep.
        assert triggers["schedule"] == [{"cron": "0 9 * * 5"}]
        # A push only releases when the plan job says so, from the merged pull
        # request's classification label.
        assert workflow["jobs"]["release"]["if"] == "needs.plan.outputs.release == 'true'"

    def test_release_operations_are_serialised(self):
        concurrency = self.load("docker-release.yml")["concurrency"]

        assert concurrency["group"] == "release-publication"
        assert concurrency["cancel-in-progress"] is False

    def test_manual_dispatch_cannot_bypass_the_pr_release_classification(self):
        # workflow_dispatch must only be able to re-run classification of an
        # already-merged pull request or trigger the Friday sweep - never
        # request a patch/minor/major release directly, which would let
        # someone publish a release the required PR check never validated.
        options = self.load("docker-release.yml")[True]["workflow_dispatch"]["inputs"][
            "release_type"
        ]["options"]

        assert set(options) == {"auto", "maintenance"}

    def test_workflow_dispatch_cannot_publish_an_unmerged_ref(self):
        # workflow_dispatch lets a caller pick any branch or tag to run this
        # workflow against; push is already restricted to main by its own
        # trigger and schedule always runs the default branch, but nothing
        # else stops a dispatched run from tagging and publishing a feature
        # branch's tip commit. Both jobs must refuse to proceed unless the
        # ref actually is main, before either one checks out any code.
        for job_name in ("plan", "release"):
            steps = self.load("docker-release.yml")["jobs"][job_name]["steps"]
            names = [step.get("name", "") for step in steps]

            guard_index = names.index("Refuse releases from any ref other than main")
            checkout_index = names.index("Checkout code")
            assert guard_index < checkout_index, job_name

            guard_step = steps[guard_index]
            # github.ref is piped through env rather than interpolated
            # straight into the shell, so a ref name can't inject into it.
            assert "github.ref" in guard_step["env"]["REF"]
            assert "refs/heads/main" in guard_step["run"]
            assert "exit 1" in guard_step["run"]

    def test_the_tag_is_created_before_the_image_is_published(self):
        steps = self.load("docker-release.yml")["jobs"]["release"]["steps"]
        names = [step.get("name", "") for step in steps]

        assert names.index("Re-validate release before publishing") < names.index(
            "Create release tag"
        )
        assert names.index("Create release tag") < names.index("Build and push Docker image")
        assert names.index("Build and push Docker image") < names.index("Create GitHub release")

    def test_an_unpublished_tag_elsewhere_blocks_every_other_release_path(self):
        # If the highest semantic tag anywhere in history has no published
        # GitHub Release, and it isn't this commit's own tag (which is
        # already handled by resume/already-released), the run must fail
        # closed rather than silently calculating past the stalled release -
        # a normal classification release would skip its version, and the
        # Friday sweep would use its commit as a boundary and lose the
        # release:none PRs that were meant to ride the next release.
        step = next(
            step
            for step in self.load("docker-release.yml")["jobs"]["plan"]["steps"]
            if step.get("id") == "resume"
        )
        run = step["run"]

        assert "HIGHEST_TAG" in run
        assert "PUBLISHED_HIGHEST_TAG" in run
        assert '"$HIGHEST_TAG" != "$PUBLISHED_HIGHEST_TAG"' in run
        assert "exit 1" in run

    def test_image_naming_and_registries_are_unchanged(self):
        steps = self.load("docker-release.yml")["jobs"]["release"]["steps"]
        metadata = next(step for step in steps if step.get("id") == "meta")

        assert (
            "docker.io/${{ secrets.DOCKERHUB_USERNAME }}/docker-autoheal"
            in metadata["with"]["images"]
        )
        assert (
            "ghcr.io/${{ github.repository_owner }}/docker-autoheal" in metadata["with"]["images"]
        )
        assert "type=raw,value=latest" in metadata["with"]["tags"]

    def test_classification_uses_events_api_not_current_labels(self):
        # Guard the immutability fix: the classification step must reconstruct
        # labels from the GitHub Issues Events API (append-only) rather than
        # reading the current mutable PR labels.
        step = next(
            s
            for s in self.load("docker-release.yml")["jobs"]["plan"]["steps"]
            if s.get("id") == "classification"
        )
        run = step["run"]

        assert "issues" in run and "events" in run, (
            "classification step must call the GitHub Issues Events API"
        )
        assert "resolve-labels" in run, (
            "classification step must use resolve-labels for merge-time label reconstruction"
        )
        assert ".labels[" not in run, (
            "classification step must not read current PR labels from the API response"
        )

    def test_maintenance_classification_uses_events_api_not_current_labels(self):
        # Regression guard: the maintenance step must also reconstruct labels
        # from the GitHub Issues Events API at merge time, not from the current
        # mutable PR labels returned by the search/issues endpoint.
        #
        # Failure scenario: a PR is merged with release:none; someone removes
        # the label afterwards; the Friday sweep reads current labels and
        # omits the PR from the maintenance release entirely.
        step = next(
            s
            for s in self.load("docker-release.yml")["jobs"]["plan"]["steps"]
            if "Collect unreleased release:none pull requests" in s.get("name", "")
        )
        run = step["run"]

        assert "issues" in run and "events" in run, (
            "maintenance step must call the GitHub Issues Events API"
        )
        assert "resolve-labels" in run, (
            "maintenance step must use resolve-labels for merge-time label reconstruction"
        )
        assert ".labels[" not in run, (
            "maintenance step must not read current PR labels from the search response"
        )

    def test_pull_request_validation_uses_no_secrets(self):
        workflow = self.load("release-validation.yml")

        assert workflow["permissions"] == {"contents": "read"}
        assert "secrets." not in json.dumps(workflow)
        assert "validate-release" in workflow["jobs"]
