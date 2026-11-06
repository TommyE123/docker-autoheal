"""Restart success-rate helper used by the recovery summary."""

from __future__ import annotations


def success_rate(successes: int, attempts: int) -> float:
    """Return the restart success rate as a percentage from 0.0 to 100.0.

    Returns 0.0 when there have been no attempts, so a container that has
    never been restarted reports 0.0 instead of raising.
    """
    return successes / attempts * 100.0
