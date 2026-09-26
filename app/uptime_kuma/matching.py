"""Deterministic matching between Docker containers and Uptime-Kuma monitors.

Safety-critical: AutoHeal uses this mapping to decide which container an
Uptime-Kuma monitor's status applies to. A false positive here could
therefore associate a monitor with the wrong container. The matcher only
ever produces a mapping when a container and a monitor uniquely identify
each other after normalization - no fuzzy/string-distance matching, and no
"closest match" fallback. See issue #141.
"""

import logging
import re
from typing import Dict, Iterable, List, Optional, TypedDict

logger = logging.getLogger(__name__)


class ContainerNameInfo(TypedDict, total=False):
    """The subset of ``DockerClientWrapper.get_container_info()``'s output
    the matcher needs. ``compose_service`` is optional (absent/None for
    containers not managed by Docker Compose)."""

    stable_id: str
    name: str
    compose_service: Optional[str]


class MonitorInfo(TypedDict):
    friendly_name: str


class UptimeKumaMatch(TypedDict):
    container_id: str
    monitor_friendly_name: str


def normalize_name(name: str) -> str:
    """Canonicalize a name for deterministic comparison.

    Case, hyphens, underscores and spaces are all treated as equivalent
    separators, so "Steam-Headless", "steam_headless" and "steam headless"
    all normalize to the same value.
    """
    return re.sub(r"[-_\s]+", "-", name.strip().lower()).strip("-")


def match_uptime_kuma_monitors(
    containers: Iterable[ContainerNameInfo],
    monitors: Iterable[MonitorInfo],
) -> List[UptimeKumaMatch]:
    """Match Docker containers to Uptime-Kuma monitors by name, deterministically.

    For each container, the candidate names considered are its Docker
    container name and, when available, its Docker Compose service name.
    Monitor names are matched against those candidates using the same
    normalization (case-insensitive, hyphen/underscore/space-insensitive).

    A container is only mapped to a monitor when the match is completely
    unambiguous in both directions: exactly one monitor matches the
    container's candidate names, and that monitor in turn matches exactly
    that one container. Anything else - no match, a container matching
    several monitors, or a monitor matching several containers - is left
    unmapped rather than guessed, since a wrong auto-mapping could cause
    AutoHeal to act on the wrong container.

    Args:
        containers: Container name info, keyed by ``stable_id``/``name`` and
            optionally ``compose_service`` (e.g. as returned by
            ``DockerClientWrapper.get_container_info()``).
        monitors: Uptime-Kuma monitors, each with a ``friendly_name``.

    Returns:
        A list of ``{"container_id": ..., "monitor_friendly_name": ...}``
        dicts, one per unambiguous match. ``container_id`` is always the
        container's ``stable_id``, never a raw name, so persisted mappings
        continue to use stable identifiers.
    """
    containers = list(containers)
    monitors = list(monitors)

    # Indexed by monitor position, not by friendly_name text, so two distinct
    # monitor objects that happen to share an identical friendly_name are
    # never collapsed into a single candidate - each still counts as its own
    # ambiguous alternative rather than a single unambiguous match.
    monitor_indices_by_norm: Dict[str, List[int]] = {}
    for index, monitor in enumerate(monitors):
        monitor_indices_by_norm.setdefault(normalize_name(monitor["friendly_name"]), []).append(index)

    container_matches: List[set] = []
    for container in containers:
        candidates = {container["name"]}
        compose_service = container.get("compose_service")
        if compose_service:
            candidates.add(compose_service)

        matched_indices: set = set()
        for candidate in candidates:
            matched_indices.update(monitor_indices_by_norm.get(normalize_name(candidate), []))
        container_matches.append(matched_indices)

    monitor_match_counts: Dict[int, int] = {}
    for matched_indices in container_matches:
        for index in matched_indices:
            monitor_match_counts[index] = monitor_match_counts.get(index, 0) + 1

    results: List[UptimeKumaMatch] = []
    for container, matched_indices in zip(containers, container_matches):
        if len(matched_indices) != 1:
            if len(matched_indices) > 1:
                candidate_names = sorted(monitors[i]["friendly_name"] for i in matched_indices)
                logger.debug(
                    "Uptime-Kuma auto-mapping: leaving %s unmapped, matched %d monitors "
                    "(%s) - ambiguous",
                    container["stable_id"],
                    len(matched_indices),
                    ", ".join(candidate_names),
                )
            continue
        (monitor_index,) = matched_indices
        if monitor_match_counts[monitor_index] != 1:
            logger.debug(
                "Uptime-Kuma auto-mapping: leaving %s unmapped, monitor %r also matches "
                "another container - ambiguous",
                container["stable_id"],
                monitors[monitor_index]["friendly_name"],
            )
            continue
        results.append(
            {
                "container_id": container["stable_id"],
                "monitor_friendly_name": monitors[monitor_index]["friendly_name"],
            }
        )
    return results
