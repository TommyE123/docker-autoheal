"""Behaviour tests for the badge-only CI scripts.

.github/scripts/badge-only.sh decides whether a pull request is the automated mutation badge
update (so CI can skip the expensive jobs); .github/scripts/validate-badge.sh is what the
required unit-tests check runs instead for such a PR. The invariant: uncertain detection never
suppresses normal CI, and an invalid badge file never passes. The real scripts are executed;
only `gh` is stubbed (it applies the script's own --jq filter to a canned API response).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
BADGE = ".github/badges/mutation.json"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")

GH_STUB = """#!/usr/bin/env bash
[ -z "${FAKE_API_FAIL:-}" ] || exit 1
while [ "$#" -gt 0 ]; do
  if [ "$1" = --jq ]; then
    expr=$2
  fi
  shift
done
printf '%s' "$FAKE_API_JSON" | jq -r "$expr"
"""


def _run(script, *args, env=None):
    # The repository's own fixed scripts; nothing here is untrusted input.
    return subprocess.run(  # noqa: S603
        [SCRIPTS / script, *map(str, args)], env=env, capture_output=True, text=True, check=False
    )


def _files(*entries):
    return json.dumps([{"filename": e} if isinstance(e, str) else e for e in entries])


def _detect(tmp_path, api_json=None, event="pull_request", api_fail=False):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    gh = stub_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    output = tmp_path / "github_output"
    env = {
        **os.environ,
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "EVENT_NAME": event,
        "PR": "1" if event == "pull_request" else "",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_OUTPUT": str(output),
        "FAKE_API_JSON": api_json or "[]",
        "FAKE_API_FAIL": "1" if api_fail else "",
    }
    assert _run("badge-only.sh", env=env).returncode == 0
    return output.read_text().strip()


@pytest.mark.parametrize(
    ("api_json", "event", "api_fail", "expected"),
    [
        (_files(BADGE), "pull_request", False, "true"),
        (_files(BADGE, "app/main.py"), "pull_request", False, "false"),
        (_files("app/main.py"), "pull_request", False, "false"),
        ("[]", "pull_request", False, "false"),
        (_files(BADGE), "pull_request", True, "false"),
        (_files(BADGE), "push", False, "false"),
        (_files(BADGE), "workflow_dispatch", False, "false"),
        # A rename onto the badge path would hide the file it removed.
        (
            _files({"filename": BADGE, "previous_filename": "app/main.py"}),
            "pull_request",
            False,
            "false",
        ),
        (
            _files({"filename": "app/main.py", "previous_filename": BADGE}),
            "pull_request",
            False,
            "false",
        ),
        (_files(BADGE + ".bak"), "pull_request", False, "false"),
    ],
    ids=[
        "badge-only",
        "badge-and-app",
        "app-only",
        "empty-response",
        "api-failure",
        "push-event",
        "dispatch-event",
        "rename-into-badge",
        "rename-out-of-badge",
        "lookalike-path",
    ],
)
def test_detector_only_reports_badge_only_when_certain(
    tmp_path, api_json, event, api_fail, expected
):
    assert _detect(tmp_path, api_json, event, api_fail) == f"badge-only={expected}"


def _validate(tmp_path, content):
    badge = tmp_path / "mutation.json"
    if content is not None:
        badge.write_text(content if isinstance(content, str) else json.dumps(content))
    return _run("validate-badge.sh", badge).returncode


def _badge(**overrides):
    # The shape `mutmut badge --label Mutation` writes (see mutation.sh).
    badge = {"schemaVersion": 1, "label": "Mutation", "message": "66.0%", "color": "#adff00"}
    badge.update(overrides)
    return {key: value for key, value in badge.items() if value is not None}


def test_committed_badge_file_is_valid():
    assert _run("validate-badge.sh", REPO_ROOT / BADGE).returncode == 0


@pytest.mark.parametrize("message", ["0.0%", "66.0%", "100.0%"])
def test_validation_accepts_generated_percentages(tmp_path, message):
    assert _validate(tmp_path, json.dumps(_badge(message=message), indent=4) + "\n") == 0


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(None, id="missing-file"),
        pytest.param("", id="empty-file"),
        pytest.param("{not json", id="malformed-json"),
        pytest.param("[]", id="not-an-object"),
        pytest.param(_badge(schemaVersion=None), id="no-schemaVersion"),
        pytest.param(_badge(label=None), id="no-label"),
        pytest.param(_badge(message=None), id="no-message"),
        pytest.param(_badge(color=None), id="no-color"),
        pytest.param(_badge(schemaVersion="1"), id="schemaVersion-string"),
        pytest.param(_badge(schemaVersion=2), id="schemaVersion-wrong"),
        pytest.param(_badge(label=""), id="label-empty"),
        pytest.param(_badge(label=1), id="label-number"),
        pytest.param(_badge(message=66.0), id="message-number"),
        pytest.param(_badge(color=123), id="color-number"),
        pytest.param(_badge(message="66%"), id="percentage-no-decimal"),
        pytest.param(_badge(message="66.0"), id="percentage-no-sign"),
        pytest.param(_badge(message="100.1%"), id="percentage-over-100"),
        pytest.param(_badge(message="-1.0%"), id="percentage-negative"),
        pytest.param(_badge(message="n/a"), id="percentage-text"),
        pytest.param(_badge(color="adff00"), id="color-no-hash"),
        pytest.param(_badge(color="#adf"), id="color-short"),
    ],
)
def test_validation_rejects_missing_or_invalid_badges(tmp_path, content):
    assert _validate(tmp_path, content) != 0
