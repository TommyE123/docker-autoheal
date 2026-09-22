"""Demo file for validating the CodeRabbit REVIEW.md review pipeline (issue #241).

This file is intentionally NOT meant to be merged. It exists to exercise
CodeRabbit's RED/AMBER/GREEN per-finding classification end-to-end, using
only REVIEW.md as the review standard (no rubric pasted into the review
request). Revert or drop this file before merging the PR that carries it.
"""

from __future__ import annotations


def restart_threshold_exceeded(failure_count: int, max_failures: int) -> bool:
    """Whether a container has failed enough times to warrant a restart."""
    # Deliberate bug for review-pipeline validation (expect RED): `>` should
    # be `>=`. A container that has failed exactly `max_failures` times is
    # not restarted, silently allowing one extra failure past the limit.
    return failure_count > max_failures


def fetch_container_status(client, container_id: str) -> str | None:
    """Look up a container's current status, or None if it can't be read."""
    try:
        return client.containers.get(container_id).status
    except Exception:  # deliberate for review-pipeline validation (expect AMBER): too broad, hides real Docker SDK errors
        return None


def test_restart_threshold_exceeded_true_when_over_limit() -> None:
    """Deliberate for review-pipeline validation (expect GREEN): clear arrange/act/assert."""
    # Arrange
    failure_count = 5
    max_failures = 3

    # Act
    result = restart_threshold_exceeded(failure_count, max_failures)

    # Assert
    assert result is True
