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

## Core Review Principles

Prioritise:

1. Correctness
2. Reliability
3. Production safety
4. Security
5. Observability
6. Maintainability

Focus on the changed code and its direct impact.

Do not:

- Report stylistic preferences unless they create a real problem.
- Perform a general audit of the repository.
- Report unrelated pre-existing issues.
- Speculate about hypothetical failures without a credible failure path.
- Inflate severity.

A GREEN review is preferred over a weak, speculative, or low-confidence finding.

---

## Evidence Threshold

Only raise a finding when the issue can be reasonably demonstrated from the changed code and represents a realistic failure scenario.

Findings should be limited to issues introduced or materially worsened by the PR.

Every finding should identify:

- What is wrong.
- Where it occurs.
- Why it matters.
- How the PR introduced or worsened the issue.
- The smallest reasonable fix.
- Whether a regression test would be useful.

Avoid speculation. Point to the specific code path that produces the problem.

---

## Correctness and Reliability

Look for:

- Incorrect behaviour or broken logic.
- Behavioural regressions.
- Error paths that leave the application in an incorrect state.
- Race conditions and unsafe assumptions.
- Resource leaks or cleanup failures.
- Production failures not obvious from the happy path.
- Configuration changes that alter behaviour unexpectedly.

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

## Application Behaviour

Review API, service, configuration, and application changes for:

- Behavioural regressions.
- Invalid input handling.
- Error handling.
- State consistency.
- Background task behaviour.
- Configuration compatibility.
- Unexpected deployment or operational impact.

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
