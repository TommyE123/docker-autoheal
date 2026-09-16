"""Gemini-backed GitHub issue classification: validation and label-diff logic.

This module is intentionally free of GitHub/Gemini I/O beyond the single
`call_gemini` HTTP call (which takes an injected session so it can be
exercised deterministically in tests). Everything else here is pure
functions so the classification, validation, truncation, and label-change
decisions can be unit tested without a live Gemini API call.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

# The runtime allow-list Gemini's classification is validated against. This
# is intentionally a separate list from the GitHub label definitions in
# .github/labels.yml (which own name/color/description for the repo's
# kind/*, area/* labels) and from the values described in
# .github/triage/system-prompt.txt (which tell the model what it may
# return) - all three must be updated together when the taxonomy changes.
ALLOWED_KINDS = ("bug", "enhancement", "documentation", "chore")
ALLOWED_AREAS = (
    "docker",
    "restart",
    "health-check",
    "config",
    "logging",
    "github-actions",
    "tests",
)

CONFIDENCE_THRESHOLD = 0.60
TITLE_MAX_CHARS = 500
BODY_MAX_CHARS = 8000

# Below this many combined, stripped characters of title+body, an issue is
# treated as too thin to classify at all (rather than sent to Gemini).
MIN_CONTENT_CHARS = 15

NEEDS_INFO_MARKER = "<!-- autoheal-triage:needs-information -->"

GEMINI_API_HOST = "https://generativelanguage.googleapis.com"
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_BACKOFF_SECONDS = (2, 4, 8)


def truncate_title(title: Optional[str]) -> str:
    return (title or "")[:TITLE_MAX_CHARS]


def truncate_body(body: Optional[str]) -> str:
    return (body or "")[:BODY_MAX_CHARS]


def has_sufficient_content(title: Optional[str], body: Optional[str]) -> bool:
    """Reject only genuinely empty/minimal issues, not merely short ones."""
    combined = f"{title or ''} {body or ''}".strip()
    return len(combined) >= MIN_CONTENT_CHARS


def has_issue_changed(
    original_title: Optional[str],
    original_body: Optional[str],
    current_title: Optional[str],
    current_body: Optional[str],
) -> bool:
    """Has the issue's content changed since the title/body we classified?

    The workflow's `cancel-in-progress` concurrency group only cancels a
    superseded run on a best-effort basis - GitHub Actions cancellation
    takes a moment to land, so an older run can still be mid-flight (or
    already past cancellation) when a newer one starts. This is a precise,
    content-based backstop: comparing the exact title/body a run classified
    against the issue's current title/body right before that run mutates
    labels. Unrelated activity (a comment, someone else's label change)
    never trips it, because only an actual title/body edit does - and any
    such edit already fires its own `edited` event with a fresh, correct
    run of its own.
    """
    return (original_title or "") != (current_title or "") or (
        original_body or ""
    ) != (current_body or "")


@dataclass(frozen=True)
class Classification:
    kind: str
    area: str
    confidence: float


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    classification: Optional[Classification] = None
    error: Optional[str] = None


def parse_classification(raw_text: Optional[str]) -> ValidationResult:
    """Validate a raw Gemini response string before it can touch GitHub.

    Never trust the model: this checks the response exists, parses as JSON,
    is an object with exactly the three expected fields, and that both
    `kind` and `area` are members of the configured allow-lists.
    """
    if not raw_text:
        return ValidationResult(valid=False, error="empty response")

    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return ValidationResult(valid=False, error="malformed JSON")

    if not isinstance(data, dict):
        return ValidationResult(valid=False, error="response is not a JSON object")

    if set(data.keys()) != {"kind", "area", "confidence"}:
        return ValidationResult(valid=False, error="unexpected or missing fields")

    kind = data["kind"]
    area = data["area"]
    confidence = data["confidence"]

    if not isinstance(kind, str) or kind not in ALLOWED_KINDS:
        return ValidationResult(valid=False, error=f"invalid kind: {kind!r}")

    if not isinstance(area, str) or area not in ALLOWED_AREAS:
        return ValidationResult(valid=False, error=f"invalid area: {area!r}")

    # bool is a subclass of int in Python; explicitly excluded so `true`/
    # `false` are never accepted as a confidence value.
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return ValidationResult(valid=False, error=f"invalid confidence: {confidence!r}")

    if not (0.0 <= float(confidence) <= 1.0):
        return ValidationResult(valid=False, error=f"confidence out of range: {confidence!r}")

    return ValidationResult(
        valid=True,
        classification=Classification(kind=kind, area=area, confidence=float(confidence)),
    )


class Outcome(str, Enum):
    CLASSIFIED = "classified"
    LOW_CONFIDENCE = "low_confidence"
    INVALID = "invalid"
    INSUFFICIENT_INFO = "insufficient_info"


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    classification: Optional[Classification] = None
    reason: Optional[str] = None


def decide(
    validation: ValidationResult, threshold: float = CONFIDENCE_THRESHOLD
) -> Decision:
    """Turn a validated (or rejected) Gemini response into a triage decision.

    Any failure mode - malformed response, invalid values, or confidence
    below the threshold - falls safely back to leaving the issue in
    needs-triage rather than partially applying a classification.
    """
    if not validation.valid:
        return Decision(outcome=Outcome.INVALID, reason=validation.error)

    classification = validation.classification
    if classification is None:
        raise ValueError("classification is required when validation is valid")

    if classification.confidence < threshold:
        return Decision(
            outcome=Outcome.LOW_CONFIDENCE,
            classification=classification,
            reason="confidence below threshold",
        )

    return Decision(outcome=Outcome.CLASSIFIED, classification=classification)


@dataclass(frozen=True)
class LabelChanges:
    to_add: list
    to_remove: list


def compute_label_changes(
    outcome: Outcome,
    current_labels: Iterable[str],
    classification: Optional[Classification] = None,
) -> LabelChanges:
    """Compute the minimal label add/remove set for a triage decision.

    Only ever mutates kind/*, area/*, and status/* labels; anything else on
    the issue (priority, assignment, unrelated labels, ...) is left alone.
    """
    current = set(current_labels)

    if outcome == Outcome.CLASSIFIED:
        if classification is None:
            raise ValueError("classification is required when outcome is CLASSIFIED")
        new_kind = f"kind/{classification.kind}"
        new_area = f"area/{classification.area}"
        keep = {new_kind, new_area}

        to_add = sorted(keep - current)
        to_remove = sorted(
            label
            for label in current
            if label not in keep
            and (
                label.startswith(("kind/", "area/"))
                or label in ("status/needs-triage", "status/needs-information")
            )
        )
        return LabelChanges(to_add=to_add, to_remove=to_remove)

    if outcome == Outcome.INSUFFICIENT_INFO:
        to_add = sorted({"status/needs-information"} - current)
        to_remove = sorted({"status/needs-triage"} & current)
        return LabelChanges(to_add=to_add, to_remove=to_remove)

    # LOW_CONFIDENCE or INVALID: fail safe, ensure needs-triage is the only
    # status label (a prior needs-information must not linger alongside it).
    # Never partially apply a classification.
    to_add = sorted({"status/needs-triage"} - current)
    to_remove = sorted({"status/needs-information"} & current)
    return LabelChanges(to_add=to_add, to_remove=to_remove)


def compute_desired_labels(
    outcome: Outcome,
    current_labels: Iterable[str],
    classification: Optional[Classification] = None,
) -> list:
    """Compute the full label set the issue should have after this decision.

    This is the complete set - unrelated labels included - meant to be
    applied with a single atomic "replace all labels" call, rather than
    separate remove/add calls that could leave an issue with neither its
    old nor its new classification if the second call fails.
    """
    current = set(current_labels)
    changes = compute_label_changes(outcome, current, classification)
    desired = (current - set(changes.to_remove)) | set(changes.to_add)
    return sorted(desired)


def build_needs_info_comment() -> str:
    return (
        f"{NEEDS_INFO_MARKER}\n"
        "Thanks for opening this issue! To help us triage it, could you add:\n\n"
        "- What happened\n"
        "- What you expected to happen\n"
        "- Steps to reproduce\n"
        "- docker-autoheal version\n"
        "- Docker version\n"
        "- Host OS\n"
        "- Relevant logs (please redact any secrets)\n\n"
        "This will help route the issue correctly."
    )


def has_needs_info_comment(comment_bodies: Iterable[Optional[str]]) -> bool:
    return any(NEEDS_INFO_MARKER in (body or "") for body in comment_bodies)


def build_gemini_payload(system_prompt: str, title: str, body: str) -> dict:
    user_content = (
        f"Issue title:\n{title}\n\n"
        f"Issue body:\n{body if body else '(no body provided)'}"
    )
    return {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(ALLOWED_KINDS)},
                    "area": {"type": "string", "enum": list(ALLOWED_AREAS)},
                    "confidence": {"type": "number"},
                },
                "required": ["kind", "area", "confidence"],
            },
        },
    }


def extract_gemini_text(response_json: dict) -> Optional[str]:
    try:
        return response_json["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None


@dataclass(frozen=True)
class GeminiCallResult:
    ok: bool
    text: Optional[str] = None
    error: Optional[str] = None


def call_gemini(
    session,
    api_key: str,
    model: str,
    payload: dict,
    timeout: float = 30.0,
    max_attempts: int = 3,
    sleep_fn=time.sleep,
) -> GeminiCallResult:
    """Call the Gemini generateContent REST API with small, bounded retries.

    `session` is any object exposing `.post(url, headers=..., json=...,
    timeout=...)` returning a `requests.Response`-like object - a real
    `requests.Session` in production, a stub in tests. The API key is only
    ever placed in a request header, never in the URL or logged.
    """
    url = f"{GEMINI_API_HOST}/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.post(url, headers=headers, json=payload, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - any transport failure is retryable
            last_error = f"request failed: {exc}"
            if attempt < max_attempts:
                sleep_fn(_BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)])
                continue
            return GeminiCallResult(ok=False, error=last_error)

        if response.status_code == 200:
            try:
                response_json = response.json()
            except (TypeError, ValueError):
                return GeminiCallResult(ok=False, error="malformed Gemini response JSON")
            text = extract_gemini_text(response_json)
            if text is None:
                return GeminiCallResult(ok=False, error="malformed Gemini response shape")
            return GeminiCallResult(ok=True, text=text)

        last_error = f"Gemini API returned HTTP {response.status_code}"
        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < max_attempts:
            sleep_fn(_BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)])
            continue
        return GeminiCallResult(ok=False, error=last_error)

    raise AssertionError("unreachable: loop always returns before exhausting attempts")
