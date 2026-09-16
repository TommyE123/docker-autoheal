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

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.issue_triage import (
    Classification,
    Decision,
    Outcome,
    build_gemini_payload,
    build_needs_info_comment,
    call_gemini,
    compute_desired_labels,
    compute_label_changes,
    decide,
    has_issue_changed,
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


def _fetch_current_issue(github_session: requests.Session, repo: str, issue_number: int) -> dict:
    """Read the issue's live title/body/labels right before mutating it.

    The webhook payload's snapshot is taken at event time; Gemini
    classification (with retries) can take long enough for the issue to
    change in the meantime. Re-fetching immediately before mutating keeps
    that staleness window as small as possible, and gives main() the
    title/body it needs for the has_issue_changed() freshness check.
    """
    response = github_session.get(
        f"{GITHUB_API_HOST}/repos/{repo}/issues/{issue_number}",
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "title": payload.get("title"),
        "body": payload.get("body"),
        "labels": [label["name"] for label in payload["labels"]],
    }


def _replace_labels(
    github_session: requests.Session, repo: str, issue_number: int, desired_labels
) -> None:
    """Set the issue's full label set in a single call.

    GitHub's "set labels" endpoint replaces the entire label set atomically,
    so this can never leave an issue with neither its old nor its new
    classification - unlike a separate remove-then-add sequence, where a
    failure between the two calls would do exactly that.
    """
    response = github_session.put(
        f"{GITHUB_API_HOST}/repos/{repo}/issues/{issue_number}/labels",
        json={"labels": list(desired_labels)},
        timeout=30,
    )
    response.raise_for_status()


def _fetch_all_comment_bodies(github_session, repo: str, issue_number: int) -> list:
    """Read every comment body, paginating past the first 100.

    An issue with a long history could have more than one page of comments;
    stopping at page one risks missing our own earlier marker comment and
    posting a duplicate.

    `github_session` is duck-typed (just needs `.get()`), like
    `call_gemini`'s injected session, so tests can exercise pagination with
    a minimal fake rather than a real `requests.Session`.
    """
    bodies: list = []
    page = 1
    while True:
        response = github_session.get(
            f"{GITHUB_API_HOST}/repos/{repo}/issues/{issue_number}/comments",
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        bodies.extend(comment.get("body") for comment in batch)
        if len(batch) < 100:
            return bodies
        page += 1


def _post_needs_info_comment_if_absent(github_session, repo: str, issue_number: int) -> None:
    comment_bodies = _fetch_all_comment_bodies(github_session, repo, issue_number)

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
    raw_title = os.environ.get("ISSUE_TITLE", "")
    raw_body = os.environ.get("ISSUE_BODY", "")
    title = truncate_title(raw_title)
    body = truncate_body(raw_body)
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
    fresh_issue = _fetch_current_issue(github_session, repo, issue_number)

    if has_issue_changed(raw_title, raw_body, fresh_issue["title"], fresh_issue["body"]):
        print(
            f"Issue #{issue_number}: title/body changed since this run started classifying "
            "it; skipping label mutation so a fresher run (already triggered by that edit) "
            "doesn't get overwritten."
        )
        return exit_code

    desired_labels = compute_desired_labels(
        decision.outcome, fresh_issue["labels"], decision.classification
    )
    _replace_labels(github_session, repo, issue_number, desired_labels)

    if decision.outcome == Outcome.INSUFFICIENT_INFO:
        _post_needs_info_comment_if_absent(github_session, repo, issue_number)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
