# Code Review Guidance

This document defines repository-specific review guidance for `docker-autoheal`.

Review the actual changes in the PR and focus on issues that could affect correctness, reliability, security, maintainability, observability, or production behaviour.

Do not manufacture findings. If no actionable issue exists, state that clearly.

---

## Review Status

Every review must begin with one of the following statuses.

### 🟢 GREEN — READY

No actionable issues found.

The PR is safe to proceed from a code review perspective.

### 🟠 AMBER — CHANGES RECOMMENDED

No blocking issue was found, but worthwhile actionable improvements remain.

### 🔴 RED — CHANGES REQUIRED

A genuine correctness, security, reliability, or regression issue must be resolved before the PR is ready.

The status is a summary of the review outcome, not a score. Do not invent findings simply to avoid a GREEN review.

---

## Per-Finding Reporting Format

Every individual finding also gets its own tag, separate from the overall review status above:

- 🔴 **RED** — must be fixed before merge (blocking)
- 🟠 **AMBER** — worth fixing, not necessarily blocking
- 🟢 **GREEN** — something the PR gets right, or a minor/non-blocking observation worth noting

Only 🔴 RED and 🟠 AMBER findings are actionable. A 🟢 GREEN finding does not affect the overall review status — a review can carry GREEN call-outs and still conclude an overall GREEN — READY status, since GREEN findings are not actionable.

Report at most 5 🟠 AMBER findings per review; prefer fewer, high-confidence findings over an exhaustive list.

For each 🔴/🟠 finding, give:

- exact `file:line`
- what is wrong
- why it matters
- the smallest correct fix
- whether this PR introduced it or it is pre-existing
- whether a regression test is required

Inspect the surrounding repository, not just the changed lines. Do not treat the PR description or a passing test suite as proof of correctness.

End every review with exactly one verdict:

- ✅ **APPROVE** — safe to merge
- ⚠️ **APPROVE WITH MINOR CHANGES** — no blocking (RED) issue
- ❌ **CHANGES REQUIRED** — at least one RED (blocking) issue found

Review only — do not push commits to the PR.

---

## Evidence Threshold

Only raise a finding when the issue can be reasonably demonstrated from the changed code and represents a realistic failure scenario, and is introduced or materially worsened by the PR. Avoid speculation — point to the specific code path that produces the problem. A GREEN review is preferred over a weak, speculative, or low-confidence finding.

---

## Docker and Container Behaviour

`docker-autoheal` directly interacts with Docker and may restart or stop production containers.

Pay particular attention to:

- Docker SDK and API usage.
- Error handling around Docker operations.
- Container lifecycle management.
- Restart, stop, quarantine, and unquarantine behaviour.
- Health check evaluation and failure handling.
- Behaviour when Docker is unavailable.
- Behaviour when Docker returns unexpected responses.
- Race conditions between monitoring and container state changes.
- Logic that could affect the wrong container.
- Situations that could create restart loops or prevent recovery.

Findings in this area may have significant production impact, so ensure they are supported by a clearly explained failure path.

---

## Metrics, Logging, Notifications and Observability

Pay attention to changes affecting:

- Prometheus metrics.
- Health reporting.
- Failure events.
- Notifications.
- Logging.
- Status reporting.

Flag cases where observable behaviour no longer reflects actual application state.

---

## CI, Release and Deployment

Review workflow and deployment changes for:

- Incorrect CI/CD behaviour.
- Excessive permissions.
- Missing permissions.
- Secret exposure.
- Unsafe dependency or action changes.
- Docker image changes.
- Release automation regressions.
- Configuration that could trigger unintended deployments.
- Changes that require operational action but do not make that requirement clear.

---

## Tests

Tests should provide meaningful confidence for the behaviour being changed.

Look for:

- Missing regression coverage for an important bug fix.
- Tests that pass without verifying the claimed behaviour.
- Tests that only verify implementation details where observable behaviour matters.
- Missing coverage for important error paths introduced by the change.

Do not request new tests for purely mechanical or low-risk changes where additional coverage provides little value.

---

## Documentation

Flag documentation only when the PR introduces behaviour that makes existing documentation inaccurate or misleading.

Pay particular attention to:

- Configuration.
- Defaults.
- Health check behaviour.
- Restart behaviour.
- Quarantine behaviour.
- Metrics.
- Deployment requirements.
- Operational procedures.

Do not request documentation updates purely because documentation could be expanded.

---

## Scope and Noise

Review the changes made by the PR, not the repository as a whole.

Do not:

- Report unrelated cleanup opportunities.
- Report issues already fully covered by automated tooling.
- Report hypothetical problems without a credible failure scenario.
- Duplicate findings.

Prefer a small number of high-confidence findings over a large number of speculative ones.

---

## When No Issues Are Found

A GREEN review is a valid outcome.

If no actionable issue exists, state that clearly rather than inventing minor concerns.
