"""Regression checks for the mutation updater workflow's trigger and safeguards."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_TEXT = (REPO_ROOT / ".github" / "workflows" / "update-mutation-results.yml").read_text()
TRIGGERS = WORKFLOW_TEXT.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]


def test_push_to_main_ignores_only_the_badge_file_and_dispatch_is_kept():
    # paths-ignore skips a push only when every changed file is ignored, so a
    # badge-only push does not loop but a mixed or code push still runs.
    expected = (
        "  push:\n"
        "    branches:\n"
        "      - main\n"
        "    paths-ignore:\n"
        '      - ".github/badges/mutation.json"\n'
        "  workflow_dispatch:\n"
    )
    assert expected in TRIGGERS
    assert "    paths:" not in TRIGGERS


def test_workflow_keeps_stale_result_and_badge_only_publication_safeguards():
    assert "steps.fresh.outputs.current == 'true'" in WORKFLOW_TEXT
    assert "add-paths: .github/badges/mutation.json" in WORKFLOW_TEXT
    assert '[ "$files" = "$BADGE_FILE" ]' in WORKFLOW_TEXT
