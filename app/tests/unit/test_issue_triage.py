import json

import pytest
import requests

import app.scripts.triage_issue as triage_script
from app.services import issue_triage as triage

# --- truncation / pre-flight content check ---------------------------------


def test_truncate_title_within_limit_is_unchanged():
    assert triage.truncate_title("short title") == "short title"


def test_truncate_title_oversized_is_truncated():
    title = "x" * 600
    result = triage.truncate_title(title)
    assert len(result) == triage.TITLE_MAX_CHARS
    assert result == "x" * triage.TITLE_MAX_CHARS


def test_truncate_body_oversized_is_truncated():
    body = "y" * 9000
    result = triage.truncate_body(body)
    assert len(result) == triage.BODY_MAX_CHARS


def test_truncate_title_none_becomes_empty_string():
    assert triage.truncate_title(None) == ""


def test_empty_issue_is_insufficient():
    assert triage.has_sufficient_content("", "") is False
    assert triage.has_sufficient_content(None, None) is False


def test_title_only_issue_can_be_sufficient():
    # From the issue spec: a title alone can carry enough signal.
    title = "Container does not restart after Uptime Kuma reports DOWN"
    assert triage.has_sufficient_content(title, "") is True


def test_normal_issue_form_issue_is_sufficient():
    title = "Bug: restart loop on unhealthy container"
    body = "## Describe the bug\n\nContainer keeps restarting every 5 seconds."
    assert triage.has_sufficient_content(title, body) is True


def test_minimal_single_word_issue_is_insufficient():
    assert triage.has_sufficient_content("help", "") is False


# --- classification validation ----------------------------------------------


@pytest.mark.parametrize("kind", triage.ALLOWED_KINDS)
def test_valid_classification_for_each_kind(kind):
    raw = json.dumps({"kind": kind, "area": "docker", "confidence": 0.75})
    result = triage.parse_classification(raw)
    assert result.valid is True
    assert result.classification is not None
    assert result.classification.kind == kind


@pytest.mark.parametrize("area", triage.ALLOWED_AREAS)
def test_valid_classification_for_each_area(area):
    raw = json.dumps({"kind": "bug", "area": area, "confidence": 0.75})
    result = triage.parse_classification(raw)
    assert result.valid is True
    assert result.classification is not None
    assert result.classification.area == area


def test_invalid_kind_is_rejected():
    raw = json.dumps({"kind": "not-a-kind", "area": "docker", "confidence": 0.9})
    result = triage.parse_classification(raw)
    assert result.valid is False
    assert result.error is not None
    assert "kind" in result.error


def test_invalid_area_is_rejected():
    raw = json.dumps({"kind": "bug", "area": "not-an-area", "confidence": 0.9})
    result = triage.parse_classification(raw)
    assert result.valid is False
    assert result.error is not None
    assert "area" in result.error


def test_malformed_json_is_rejected():
    result = triage.parse_classification("{not valid json")
    assert result.valid is False
    assert result.classification is None


def test_missing_fields_is_rejected():
    raw = json.dumps({"kind": "bug", "area": "docker"})
    result = triage.parse_classification(raw)
    assert result.valid is False


def test_extra_unexpected_field_is_rejected():
    raw = json.dumps(
        {"kind": "bug", "area": "docker", "confidence": 0.9, "reasoning": "because"}
    )
    result = triage.parse_classification(raw)
    assert result.valid is False


def test_non_object_json_is_rejected():
    result = triage.parse_classification(json.dumps(["bug", "docker", 0.9]))
    assert result.valid is False


def test_empty_response_is_rejected():
    result = triage.parse_classification("")
    assert result.valid is False
    result = triage.parse_classification(None)
    assert result.valid is False


@pytest.mark.parametrize("confidence", [-0.1, 1.1, "high", True, None])
def test_invalid_confidence_is_rejected(confidence):
    raw = json.dumps({"kind": "bug", "area": "docker", "confidence": confidence})
    result = triage.parse_classification(raw)
    assert result.valid is False


# --- confidence threshold decisions ------------------------------------------


def test_confidence_below_threshold_is_low_confidence():
    raw = json.dumps({"kind": "bug", "area": "docker", "confidence": 0.59})
    decision = triage.decide(triage.parse_classification(raw))
    assert decision.outcome is triage.Outcome.LOW_CONFIDENCE


def test_confidence_exactly_at_threshold_is_classified():
    raw = json.dumps({"kind": "bug", "area": "docker", "confidence": 0.60})
    decision = triage.decide(triage.parse_classification(raw))
    assert decision.outcome is triage.Outcome.CLASSIFIED


def test_confidence_above_threshold_is_classified():
    raw = json.dumps({"kind": "bug", "area": "docker", "confidence": 0.95})
    decision = triage.decide(triage.parse_classification(raw))
    assert decision.outcome is triage.Outcome.CLASSIFIED


def test_invalid_response_decision_is_invalid():
    decision = triage.decide(triage.parse_classification("not json"))
    assert decision.outcome is triage.Outcome.INVALID


# --- label diff computation --------------------------------------------------


def test_classified_adds_new_kind_and_area_and_removes_old_ones():
    classification = triage.Classification(kind="bug", area="restart", confidence=0.9)
    changes = triage.compute_label_changes(
        triage.Outcome.CLASSIFIED,
        current_labels=["kind/bug", "area/docker", "status/needs-triage", "priority:high"],
        classification=classification,
    )
    assert changes.to_add == ["area/restart"]
    assert sorted(changes.to_remove) == ["area/docker", "status/needs-triage"]
    # Unrelated labels (e.g. priority:high) must never be touched.
    assert "priority:high" not in changes.to_remove


def test_classified_is_idempotent_when_labels_already_correct():
    classification = triage.Classification(kind="bug", area="restart", confidence=0.9)
    changes = triage.compute_label_changes(
        triage.Outcome.CLASSIFIED,
        current_labels=["kind/bug", "area/restart"],
        classification=classification,
    )
    assert changes.to_add == []
    assert changes.to_remove == []


def test_low_confidence_keeps_needs_triage_and_changes_nothing_else():
    changes = triage.compute_label_changes(
        triage.Outcome.LOW_CONFIDENCE, current_labels=["status/needs-triage"]
    )
    assert changes.to_add == []
    assert changes.to_remove == []


def test_low_confidence_ensures_needs_triage_present():
    changes = triage.compute_label_changes(triage.Outcome.LOW_CONFIDENCE, current_labels=[])
    assert changes.to_add == ["status/needs-triage"]
    assert changes.to_remove == []


def test_invalid_response_fails_safe_like_low_confidence():
    changes = triage.compute_label_changes(triage.Outcome.INVALID, current_labels=[])
    assert changes.to_add == ["status/needs-triage"]
    assert changes.to_remove == []


def test_low_confidence_replaces_needs_information_with_needs_triage():
    changes = triage.compute_label_changes(
        triage.Outcome.LOW_CONFIDENCE,
        current_labels=["status/needs-information", "priority:high"],
    )
    assert changes.to_add == ["status/needs-triage"]
    assert changes.to_remove == ["status/needs-information"]
    # Unrelated labels must never be touched.
    assert "priority:high" not in changes.to_remove


def test_invalid_replaces_needs_information_with_needs_triage():
    changes = triage.compute_label_changes(
        triage.Outcome.INVALID,
        current_labels=["status/needs-information", "priority:high"],
    )
    assert changes.to_add == ["status/needs-triage"]
    assert changes.to_remove == ["status/needs-information"]
    # Unrelated labels must never be touched.
    assert "priority:high" not in changes.to_remove


def test_insufficient_info_swaps_needs_triage_for_needs_information():
    changes = triage.compute_label_changes(
        triage.Outcome.INSUFFICIENT_INFO, current_labels=["status/needs-triage"]
    )
    assert changes.to_add == ["status/needs-information"]
    assert changes.to_remove == ["status/needs-triage"]


def test_classified_requires_classification_argument():
    with pytest.raises(ValueError):
        triage.compute_label_changes(triage.Outcome.CLASSIFIED, current_labels=[])


# --- full desired-label-set computation (for atomic replacement) ------------


def test_desired_labels_reclassification_preserves_unrelated_labels():
    classification = triage.Classification(kind="enhancement", area="docker", confidence=0.9)
    desired = triage.compute_desired_labels(
        triage.Outcome.CLASSIFIED,
        current_labels=["kind/bug", "area/restart", "priority:high", "good first issue"],
        classification=classification,
    )
    assert desired == ["area/docker", "good first issue", "kind/enhancement", "priority:high"]


def test_desired_labels_matches_add_remove_semantics_when_classified():
    classification = triage.Classification(kind="bug", area="restart", confidence=0.9)
    current = ["kind/bug", "area/docker", "status/needs-triage", "priority:high"]
    changes = triage.compute_label_changes(
        triage.Outcome.CLASSIFIED, current_labels=current, classification=classification
    )
    desired = triage.compute_desired_labels(
        triage.Outcome.CLASSIFIED, current_labels=current, classification=classification
    )
    expected = (set(current) - set(changes.to_remove)) | set(changes.to_add)
    assert set(desired) == expected
    assert set(desired) == {"kind/bug", "area/restart", "priority:high"}


def test_desired_labels_insufficient_info_preserves_unrelated_labels():
    desired = triage.compute_desired_labels(
        triage.Outcome.INSUFFICIENT_INFO,
        current_labels=["status/needs-triage", "good first issue"],
    )
    assert desired == ["good first issue", "status/needs-information"]


def test_desired_labels_low_confidence_is_a_pure_superset_of_current():
    current = ["priority:high"]
    desired = triage.compute_desired_labels(triage.Outcome.LOW_CONFIDENCE, current_labels=current)
    assert set(current) <= set(desired)
    assert set(desired) - set(current) == {"status/needs-triage"}


# --- needs-information comment marker ----------------------------------------


def test_needs_info_comment_contains_marker():
    assert triage.NEEDS_INFO_MARKER in triage.build_needs_info_comment()


def test_has_needs_info_comment_detects_marker():
    bodies = ["unrelated comment", f"blah {triage.NEEDS_INFO_MARKER} blah"]
    assert triage.has_needs_info_comment(bodies) is True


def test_has_needs_info_comment_false_when_absent():
    bodies = ["unrelated comment", None, "another one"]
    assert triage.has_needs_info_comment(bodies) is False


# --- Gemini request/response plumbing ----------------------------------------


def test_build_gemini_payload_has_structured_schema():
    payload = triage.build_gemini_payload("system prompt", "title", "body")
    schema = payload["generationConfig"]["responseSchema"]
    assert schema["required"] == ["kind", "area", "confidence"]
    assert set(schema["properties"]["kind"]["enum"]) == set(triage.ALLOWED_KINDS)
    assert set(schema["properties"]["area"]["enum"]) == set(triage.ALLOWED_AREAS)
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_extract_gemini_text_happy_path():
    response = {"candidates": [{"content": {"parts": [{"text": '{"kind": "bug"}'}]}}]}
    assert triage.extract_gemini_text(response) == '{"kind": "bug"}'


@pytest.mark.parametrize(
    "response",
    [{}, {"candidates": []}, {"candidates": [{"content": {"parts": []}}]}, None],
)
def test_extract_gemini_text_malformed_shapes(response):
    assert triage.extract_gemini_text(response) is None


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    """Returns queued responses/exceptions in order, one per .post() call."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _ok_response(kind="bug", area="docker", confidence=0.9):
    text = json.dumps({"kind": kind, "area": area, "confidence": confidence})
    return _FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_call_gemini_success_on_first_attempt():
    session = _FakeSession([_ok_response()])
    result = triage.call_gemini(session, "key", "gemini-2.5-flash-lite", {}, sleep_fn=lambda s: None)
    assert result.ok is True
    assert session.calls == 1


def test_call_gemini_api_key_never_in_url_or_error():
    session = _FakeSession([_FakeResponse(401)])
    result = triage.call_gemini(session, "super-secret-key", "model", {}, sleep_fn=lambda s: None)
    assert result.ok is False
    assert "super-secret-key" not in (result.error or "")


def test_call_gemini_failure_response_no_retry_on_4xx():
    session = _FakeSession([_FakeResponse(400)])
    result = triage.call_gemini(session, "key", "model", {}, sleep_fn=lambda s: None)
    assert result.ok is False
    assert session.calls == 1


def test_call_gemini_retries_transient_5xx_then_succeeds():
    session = _FakeSession([_FakeResponse(503), _ok_response()])
    result = triage.call_gemini(session, "key", "model", {}, sleep_fn=lambda s: None)
    assert result.ok is True
    assert session.calls == 2


def test_call_gemini_rate_limited_exhausts_retries_and_fails():
    session = _FakeSession([_FakeResponse(429), _FakeResponse(429), _FakeResponse(429)])
    result = triage.call_gemini(
        session, "key", "model", {}, max_attempts=3, sleep_fn=lambda s: None
    )
    assert result.ok is False
    assert session.calls == 3
    assert result.error is not None
    assert "429" in result.error


def test_call_gemini_network_exception_is_treated_as_failure():
    session = _FakeSession([ConnectionError("boom"), ConnectionError("boom")])
    result = triage.call_gemini(
        session, "key", "model", {}, max_attempts=2, sleep_fn=lambda s: None
    )
    assert result.ok is False
    assert session.calls == 2


def test_call_gemini_malformed_success_response_is_failure():
    session = _FakeSession([_FakeResponse(200, {"unexpected": "shape"})])
    result = triage.call_gemini(session, "key", "model", {}, sleep_fn=lambda s: None)
    assert result.ok is False


# --- end-to-end: label mutation is a single atomic call ----------------------


class _RecordingGithubSession:
    """A session standing in for both the Gemini and GitHub API calls main()
    makes. delete()/label-endpoint post() raise, so if the script ever
    regresses to a separate remove-then-add sequence (which could leave an
    issue with neither its old nor new classification if the second call
    failed) the test fails immediately rather than merely under-counting.
    """

    def __init__(self, gemini_text):
        self.headers = {}
        self.calls = []
        self._gemini_text = gemini_text

    def post(self, url, headers=None, json=None, timeout=None):
        if "generativelanguage.googleapis.com" in url:
            self.calls.append(("POST", url, json))
            return _FakeResponse(
                200,
                {"candidates": [{"content": {"parts": [{"text": self._gemini_text}]}}]},
            )
        if url.endswith("/labels"):
            raise AssertionError("label mutation must use PUT, not POST")
        self.calls.append(("POST", url, json))
        return _FakeResponse(201, {})

    def delete(self, url, headers=None, timeout=None):
        raise AssertionError("label mutation must use PUT, not DELETE")

    def put(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PUT", url, json))
        return _FakeResponse(200, {})

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, None))
        return _FakeResponse(200, [])


def _run_main_with_fake_session(
    monkeypatch, tmp_path, gemini_text, current_labels, title, dry_run=False
):
    prompt_path = tmp_path / "system-prompt.txt"
    prompt_path.write_text("system prompt")

    session = _RecordingGithubSession(gemini_text)
    monkeypatch.setattr(triage_script.requests, "Session", lambda: session)

    monkeypatch.setenv("GITHUB_REPOSITORY", "TommyE123/docker-autoheal")
    monkeypatch.setenv("ISSUE_NUMBER", "142")
    monkeypatch.setenv("ISSUE_TITLE", title)
    monkeypatch.setenv("ISSUE_BODY", "")
    monkeypatch.setenv("ISSUE_LABELS_JSON", json.dumps(current_labels))
    monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("SYSTEM_PROMPT_PATH", str(prompt_path))
    if dry_run:
        monkeypatch.setenv("DRY_RUN", "true")
    else:
        monkeypatch.delenv("DRY_RUN", raising=False)

    exit_code = triage_script.main()
    return exit_code, session


def test_main_reclassification_is_single_put_and_preserves_unrelated_labels(
    monkeypatch, tmp_path
):
    gemini_text = json.dumps({"kind": "enhancement", "area": "docker", "confidence": 0.9})
    current_labels = ["kind/bug", "area/restart", "priority:high", "good first issue"]

    exit_code, session = _run_main_with_fake_session(
        monkeypatch,
        tmp_path,
        gemini_text,
        current_labels,
        title="Add support for restart backoff / cooldown period",
    )

    assert exit_code == 0
    label_calls = [call for call in session.calls if call[1].endswith("/labels")]
    assert len(label_calls) == 1
    method, _url, body = label_calls[0]
    assert method == "PUT"
    assert set(body["labels"]) == {
        "kind/enhancement",
        "area/docker",
        "priority:high",
        "good first issue",
    }


def test_main_low_confidence_never_touches_labels_endpoint_twice(monkeypatch, tmp_path):
    gemini_text = json.dumps({"kind": "bug", "area": "docker", "confidence": 0.2})
    exit_code, session = _run_main_with_fake_session(
        monkeypatch,
        tmp_path,
        gemini_text,
        current_labels=["priority:high"],
        title="Container does not restart after Uptime Kuma reports DOWN",
    )

    assert exit_code == 0
    label_calls = [call for call in session.calls if call[1].endswith("/labels")]
    assert len(label_calls) == 1
    method, _url, body = label_calls[0]
    assert method == "PUT"
    assert set(body["labels"]) == {"priority:high", "status/needs-triage"}


def test_main_insufficient_info_posts_comment_not_label_mutation_twice(monkeypatch, tmp_path):
    exit_code, session = _run_main_with_fake_session(
        monkeypatch, tmp_path, gemini_text="", current_labels=[], title="help"
    )

    assert exit_code == 0
    label_calls = [call for call in session.calls if call[1].endswith("/labels")]
    assert len(label_calls) == 1
    assert label_calls[0][0] == "PUT"
    assert set(label_calls[0][2]["labels"]) == {"status/needs-information"}

    comment_posts = [
        call for call in session.calls if call[0] == "POST" and call[1].endswith("/comments")
    ]
    assert len(comment_posts) == 1
    assert triage.NEEDS_INFO_MARKER in comment_posts[0][2]["body"]


def test_main_dry_run_performs_no_github_mutations(monkeypatch, tmp_path):
    gemini_text = json.dumps({"kind": "enhancement", "area": "docker", "confidence": 0.9})

    exit_code, session = _run_main_with_fake_session(
        monkeypatch,
        tmp_path,
        gemini_text,
        current_labels=["kind/bug", "area/restart"],
        title="Add support for restart backoff / cooldown period",
        dry_run=True,
    )

    assert exit_code == 0
    # The only network call allowed in dry-run is classification itself;
    # nothing may touch the GitHub labels/comments endpoints.
    github_calls = [call for call in session.calls if "api.github.com" in call[1]]
    assert github_calls == []
