#!/usr/bin/env python3
"""GitHub Actions entrypoint for Gemini-powered issue triage.

Reads the triggering issue from environment variables (populated by
.github/workflows/issue-triage.yml from the `issues` webhook event),
classifies it with Gemini, validates the result, and applies the
kind/*, area/*, status/* label changes - or, in dry-run mode, just logs
what it would have done.

All classification/validation/decision logic lives in
app/services/issue_triage.py and is unit tested there; this script is thin
orchestration glue and is not covered by the unit-test suite (see
.coveragerc), matching the existing app/scripts/ convention.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.issue_triage import (
    Classification,
    Decision,
    Outcome,
    build_gemini_payload,
    build_needs_info_comment,
    call_gemini,
    compute_label_changes,
    decide,
    has_needs_info_comment,
    has_sufficient_content,
    parse_classification,
    truncate_body,
    truncate_title,
)

GITHUB_API_HOST = "https://api.github.com"
DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_SYSTEM_PROMPT_PATH = ".github/triage/system-prompt.txt"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _github_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return session


def _apply_label_changes(
    github_session: requests.Session, repo: str, issue_number: int, to_add, to_remove
) -> None:
    for label in to_remove:
        # Label names contain "/" (kind/bug, status/needs-triage, ...), which
        # must be percent-encoded or GitHub reads it as extra path segments.
        response = github_session.delete(
            f"{GITHUB_API_HOST}/repos/{repo}/issues/{issue_number}/labels/{quote(label, safe='')}",
            timeout=30,
        )
        if response.status_code not in (200, 404):
            response.raise_for_status()

    if to_add:
        response = github_session.post(
            f"{GITHUB_API_HOST}/repos/{repo}/issues/{issue_number}/labels",
            json={"labels": to_add},
            timeout=30,
        )
        response.raise_for_status()


def _post_needs_info_comment_if_absent(
    github_session: requests.Session, repo: str, issue_number: int
) -> None:
    response = github_session.get(
        f"{GITHUB_API_HOST}/repos/{repo}/issues/{issue_number}/comments",
        params={"per_page": 100},
        timeout=30,
    )
    response.raise_for_status()
    comment_bodies = [comment.get("body") for comment in response.json()]

    if has_needs_info_comment(comment_bodies):
        print(f"Issue #{issue_number}: needs-information comment already present, skipping.")
        return

    response = github_session.post(
        f"{GITHUB_API_HOST}/repos/{repo}/issues/{issue_number}/comments",
        json={"body": build_needs_info_comment()},
        timeout=30,
    )
    response.raise_for_status()


def _report(issue_number: int, decision: Decision, to_add, to_remove, dry_run: bool) -> None:
    print(f"Issue #{issue_number}")
    if decision.classification:
        c: Classification = decision.classification
        print("Classification:")
        print(f"  kind: {c.kind}")
        print(f"  area: {c.area}")
        print(f"  confidence: {c.confidence}")
    print(f"Outcome: {decision.outcome.value}" + (f" ({decision.reason})" if decision.reason else ""))
    print("Would add:" if dry_run else "Adding:")
    for label in to_add:
        print(f"  {label}")
    print("Would remove:" if dry_run else "Removing:")
    for label in to_remove:
        print(f"  {label}")


def main() -> int:
    dry_run = _env_bool("DRY_RUN", default=False)

    repo = os.environ["GITHUB_REPOSITORY"]
    issue_number = int(os.environ["ISSUE_NUMBER"])
    title = truncate_title(os.environ.get("ISSUE_TITLE", ""))
    body = truncate_body(os.environ.get("ISSUE_BODY", ""))
    current_labels = json.loads(os.environ.get("ISSUE_LABELS_JSON", "[]"))
    github_token = os.environ["GITHUB_TOKEN"]
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    system_prompt_path = os.environ.get("SYSTEM_PROMPT_PATH", DEFAULT_SYSTEM_PROMPT_PATH)

    exit_code = 0

    if not has_sufficient_content(title, body):
        decision = Decision(outcome=Outcome.INSUFFICIENT_INFO)
    elif not gemini_api_key:
        print("::error::GEMINI_API_KEY is not configured", file=sys.stderr)
        decision = Decision(outcome=Outcome.INVALID, reason="GEMINI_API_KEY not configured")
        exit_code = 1
    else:
        system_prompt = Path(system_prompt_path).read_text(encoding="utf-8")
        payload = build_gemini_payload(system_prompt, title, body)
        result = call_gemini(requests.Session(), gemini_api_key, model, payload)
        if not result.ok:
            print(f"::error::Gemini call failed: {result.error}", file=sys.stderr)
            decision = Decision(outcome=Outcome.INVALID, reason=result.error)
            exit_code = 1
        else:
            validation = parse_classification(result.text)
            decision = decide(validation)

    changes = compute_label_changes(
        decision.outcome, current_labels, decision.classification
    )

    _report(issue_number, decision, changes.to_add, changes.to_remove, dry_run)

    if dry_run:
        print("Dry run: no GitHub mutations performed.")
        return exit_code

    github_session = _github_session(github_token)
    _apply_label_changes(github_session, repo, issue_number, changes.to_add, changes.to_remove)

    if decision.outcome == Outcome.INSUFFICIENT_INFO:
        _post_needs_info_comment_if_absent(github_session, repo, issue_number)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
