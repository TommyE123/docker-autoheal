"""Deterministic matching between Docker containers and Uptime-Kuma monitors.

Safety-critical: AutoHeal uses this mapping to decide which container an
Uptime-Kuma monitor's status applies to. A false positive here could
therefore associate a monitor with the wrong container. The matcher only
ever produces a mapping when a container and a monitor uniquely identify
each other after normalization - no fuzzy/string-distance matching, no
"closest match" fallback, and a Docker container name always outranks a
Compose service name. See issue #141.
"""

import logging
import re
from typing import Dict, Iterable, List, NotRequired, Optional, Set, TypedDict

logger = logging.getLogger(__name__)


class ContainerNameInfo(TypedDict):
    """The subset of ``DockerClientWrapper.get_container_info()``'s output
    the matcher needs. ``compose_service`` is absent/None for containers not
    managed by Docker Compose."""

    stable_id: str
    name: str
    compose_service: NotRequired[Optional[str]]


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


def _candidate_names(container: ContainerNameInfo) -> List[str]:
    """Names to match this container by, highest precedence first."""
    names = [container["name"]]
    compose_service = container.get("compose_service")
    if compose_service:
        names.append(compose_service)
    return names


def match_uptime_kuma_monitors(
    containers: Iterable[ContainerNameInfo],
    monitors: Iterable[MonitorInfo],
) -> List[UptimeKumaMatch]:
    """Match Docker containers to Uptime-Kuma monitors by name, deterministically.

    Name sources are tried in precedence order: the Docker container name
    first, then the Docker Compose service name for any container still
    unmatched. Monitor names are compared using the same normalization
    (case-insensitive, hyphen/underscore/space-insensitive).

    Within a precedence level, a container is only mapped to a monitor when
    the match is unambiguous in both directions: exactly one monitor matches
    the container, and that monitor in turn matches exactly that one
    container. Anything else - no match, a container matching several
    monitors, or a monitor matching several containers - is left unmapped
    rather than guessed, since a wrong auto-mapping could cause AutoHeal to
    act on the wrong container. A monitor considered at one precedence level
    is never offered to a lower one, and a container whose higher-precedence
    name already matched something - even ambiguously - is not retried at a
    lower one, so an ambiguous match cannot be quietly resolved further down.

    Args:
        containers: Container name info, keyed by ``stable_id``/``name`` and
            optionally ``compose_service`` (e.g. as returned by
            ``DockerClientWrapper.get_container_info()``).
        monitors: Uptime-Kuma monitors, each with a ``friendly_name``.

    Returns:
        A list of ``{"container_id": ..., "monitor_friendly_name": ...}``
        dicts in container order, one per unambiguous match.
        ``container_id`` is always the container's ``stable_id``, never a raw
        name, so persisted mappings continue to use stable identifiers.
    """
    containers = list(containers)
    monitors = list(monitors)

    # Indexed by monitor position, not by friendly_name text, so two distinct
    # monitor objects that happen to share an identical friendly_name are
    # never collapsed into a single candidate - each still counts as its own
    # ambiguous alternative rather than a single unambiguous match.
    monitor_indices_by_norm: Dict[str, List[int]] = {}
    for index, monitor in enumerate(monitors):
        norm = normalize_name(monitor["friendly_name"])
        monitor_indices_by_norm.setdefault(norm, []).append(index)

    available: Set[int] = set(range(len(monitors)))
    unresolved: List[int] = list(range(len(containers)))
    matched_by_container: Dict[int, UptimeKumaMatch] = {}

    # Every container resolves its Docker name before any container falls back
    # to its Compose service name, so an unrelated stack's service can't
    # invalidate a match the container name alone already identified.
    names_by_container = [_candidate_names(container) for container in containers]
    tier_count = max((len(names) for names in names_by_container), default=0)

    for tier in range(tier_count):
        candidates: Dict[int, Set[int]] = {}
        for position in unresolved:
            names = names_by_container[position]
            indices: Set[int] = set()
            if tier < len(names):
                norm = normalize_name(names[tier])
                indices = {
                    index for index in monitor_indices_by_norm.get(norm, []) if index in available
                }
            candidates[position] = indices

        counts: Dict[int, int] = {}
        for indices in candidates.values():
            for index in indices:
                counts[index] = counts.get(index, 0) + 1

        unresolved = []
        for position, indices in candidates.items():
            if not indices:
                unresolved.append(position)
                continue

            stable_id = containers[position]["stable_id"]
            if len(indices) > 1:
                candidate_names = sorted(monitors[i]["friendly_name"] for i in indices)
                logger.info(
                    "Uptime-Kuma auto-mapping: leaving %s unmapped, matched %d monitors "
                    "(%s) - ambiguous",
                    stable_id,
                    len(indices),
                    ", ".join(candidate_names),
                )
                continue

            (monitor_index,) = indices
            if counts[monitor_index] != 1:
                logger.info(
                    "Uptime-Kuma auto-mapping: leaving %s unmapped, monitor %r also matches "
                    "another container - ambiguous",
                    stable_id,
                    monitors[monitor_index]["friendly_name"],
                )
                continue

            matched_by_container[position] = {
                "container_id": stable_id,
                "monitor_friendly_name": monitors[monitor_index]["friendly_name"],
            }

        # Consumed either way: a monitor that was ambiguous here must not
        # become someone's unambiguous match at a lower precedence level.
        available -= set(counts)

    return [matched_by_container[position] for position in sorted(matched_by_container)]
