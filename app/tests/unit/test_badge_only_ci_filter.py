"""Contract checks for the badge-only CI filter.

The automated mutation badge PR changes only .github/badges/mutation.json. The heavy
pull request workflows skip their jobs for it through the reusable badge-only-check
workflow. These tests pin down that the skip is wired to every heavy job, that a skipped
job can never be produced for a mixed PR, and that the committed badge file has the shape
the lightweight validation expects.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
BADGE_FILE = ".github/badges/mutation.json"
SKIP_CONDITION = "${{ needs.changes.outputs.badge-only != 'true' }}"

# workflow file -> jobs that must be skipped for badge-only PRs.
GATED_JOBS = {
    "tests.yml": ["unit-tests", "frontend-tests"],
    "docker-build.yml": ["build-amd64", "smoke-test", "arm64-startup"],
    "mega-linter.yml": ["megalinter"],
}


def _job_block(workflow: str, job: str) -> str:
    """Return the text of one top-level job in a workflow file."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    jobs_text = text.split("\njobs:\n", 1)[1]
    match = re.search(rf"^  {re.escape(job)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", jobs_text, re.M | re.S)
    assert match, f"{job} not found in {workflow}"
    return match.group(1)


@pytest.mark.parametrize(
    ("workflow", "job"),
    [(wf, job) for wf, jobs in GATED_JOBS.items() for job in jobs],
)
def test_heavy_job_is_skipped_for_badge_only_prs(workflow, job):
    block = _job_block(workflow, job)

    assert f"if: {SKIP_CONDITION}" in block
    assert re.search(r"needs:\s*(\[[^\]]*\bchanges\b[^\]]*\]|changes\b)", block)


@pytest.mark.parametrize("workflow", sorted(GATED_JOBS))
def test_changes_job_calls_the_shared_detector(workflow):
    block = _job_block(workflow, "changes")

    assert "uses: ./.github/workflows/badge-only-check.yml" in block
    assert "pull-requests: read" in block


@pytest.mark.parametrize("workflow", sorted(GATED_JOBS))
def test_gated_workflows_still_trigger_on_every_pull_request(workflow):
    # A paths filter would leave required checks pending; skipping must happen per job.
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    on_block = text.split("\njobs:\n", 1)[0]

    assert "paths:" not in on_block
    assert "paths-ignore:" not in on_block


def test_detector_only_reports_badge_only_when_every_path_is_the_badge_file():
    text = (WORKFLOWS / "badge-only-check.yml").read_text(encoding="utf-8")

    assert f"BADGE_FILE: {BADGE_FILE}" in text
    # Fails safe: default false, only true for a pull request whose every path is the badge.
    assert "badge_only=false" in text
    assert 'grep -vxF "$BADGE_FILE"' in text
    # A rename's source path is considered too, so it cannot hide another file.
    assert "previous_filename" in text
    assert "pull_request" in text


def test_validation_runs_only_for_badge_only_prs():
    block = _job_block("badge-only-check.yml", "validate-badge")

    assert "needs.detect.outputs.badge-only == 'true'" in block


def test_committed_badge_file_matches_the_validated_shape():
    badge = json.loads((REPO_ROOT / BADGE_FILE).read_text(encoding="utf-8"))

    assert badge["schemaVersion"] == 1
    assert badge["label"] == "Mutation"
    assert re.fullmatch(r"[0-9]+(\.[0-9]+)?%", badge["message"])
    assert isinstance(badge["color"], str) and badge["color"]


def _validate(badge_text: str) -> int:
    """Run the workflow's own jq expression against badge text."""
    text = (WORKFLOWS / "badge-only-check.yml").read_text(encoding="utf-8")
    expression = re.search(r"jq -e '\n(.*?)\n\s*' \"\$BADGE_FILE\"", text, re.S).group(1)
    return subprocess.run(
        ["jq", "-e", expression],
        input=badge_text,
        text=True,
        capture_output=True,
        check=False,
    ).returncode


@pytest.mark.skipif(
    subprocess.run(["which", "jq"], capture_output=True, check=False).returncode != 0,
    reason="jq not installed",
)
def test_validation_accepts_the_committed_badge_and_rejects_bad_ones():
    committed = (REPO_ROOT / BADGE_FILE).read_text(encoding="utf-8")

    assert _validate(committed) == 0
    assert _validate("{}") != 0
    assert _validate('{"schemaVersion": 2, "label": "Mutation", "message": "1%", "color": "red"}') != 0
    assert _validate('{"schemaVersion": 1, "label": "Mutation", "message": "n/a", "color": "red"}') != 0
    assert _validate("not json") != 0
