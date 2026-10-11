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
from collections.abc import Iterable  # noqa: TC003 - keeps signatures evaluable at runtime
from typing import NotRequired, TypedDict

logger = logging.getLogger(__name__)


class ContainerNameInfo(TypedDict):
    """The subset of ``DockerClientWrapper.get_container_info()``'s output
    the matcher needs. ``compose_service`` is absent/None for containers not
    managed by Docker Compose."""

    stable_id: str
    name: str
    compose_service: NotRequired[str | None]


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


def _candidate_names(container: ContainerNameInfo) -> list[str]:
    """Names to match this container by, highest precedence first."""
    names = [container["name"]]
    compose_service = container.get("compose_service")
    if compose_service:
        names.append(compose_service)
    return names


def _log_monitors_taken_by_higher_precedence(
    containers: list[ContainerNameInfo],
    names_by_container: list[list[str]],
    monitor_indices_by_norm: dict[str, list[int]],
    monitors: list[MonitorInfo],
    unresolved: Iterable[int],
) -> None:
    """Explain containers left unmapped because their monitor was already taken.

    A container that simply has no monitor of its name is self-explanatory and
    stays silent; one whose name did match a monitor that a higher-precedence
    container consumed is the hard case for an operator to work out.
    """
    for position in unresolved:
        norms = {normalize_name(name) for name in names_by_container[position]}
        claimed = sorted(
            monitors[index]["friendly_name"]
            for norm in norms
            for index in monitor_indices_by_norm.get(norm, [])
        )
        if claimed:
            logger.info(
                "Uptime-Kuma auto-mapping: leaving %s unmapped, monitor(s) %s match its "
                "name but were already taken by a higher-precedence container",
                containers[position]["stable_id"],
                ", ".join(claimed),
            )


def _drop_stable_id_collisions(
    matched_by_container: dict[int, UptimeKumaMatch],
) -> list[UptimeKumaMatch]:
    """Discard matches whose ``stable_id`` was claimed by more than one container.

    Compose replicas of one service share a stable_id, and matching is per
    container, so they can each claim a different monitor. One persisted
    mapping cannot mean two monitors at once.
    """
    matches_per_stable_id: dict[str, int] = {}
    for match in matched_by_container.values():
        container_id = match["container_id"]
        matches_per_stable_id[container_id] = matches_per_stable_id.get(container_id, 0) + 1

    results: list[UptimeKumaMatch] = []
    for position in sorted(matched_by_container):
        match = matched_by_container[position]
        if matches_per_stable_id[match["container_id"]] > 1:
            logger.info(
                "Uptime-Kuma auto-mapping: leaving %s unmapped, several containers share "
                "that stable ID and matched different monitors - ambiguous",
                match["container_id"],
            )
            continue
        results.append(match)
    return results


def match_uptime_kuma_monitors(
    containers: Iterable[ContainerNameInfo],
    monitors: Iterable[MonitorInfo],
) -> list[UptimeKumaMatch]:
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

    Uniqueness is finally re-checked at the ``stable_id``, because that is the
    key the mapping is persisted under and Compose replicas of one service all
    share it. If two containers resolve to the same ``stable_id`` and each
    claimed a different monitor, both are dropped rather than persisted as two
    conflicting mappings for one key.

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
    monitor_indices_by_norm: dict[str, list[int]] = {}
    for index, monitor in enumerate(monitors):
        norm = normalize_name(monitor["friendly_name"])
        monitor_indices_by_norm.setdefault(norm, []).append(index)

    available: set[int] = set(range(len(monitors)))
    unresolved: list[int] = list(range(len(containers)))
    matched_by_container: dict[int, UptimeKumaMatch] = {}

    # Every container resolves its Docker name before any container falls back
    # to its Compose service name, so an unrelated stack's service can't
    # invalidate a match the container name alone already identified.
    names_by_container = [_candidate_names(container) for container in containers]
    tier_count = max((len(names) for names in names_by_container), default=0)

    for tier in range(tier_count):
        candidates: dict[int, set[int]] = {}
        for position in unresolved:
            names = names_by_container[position]
            indices: set[int] = set()
            if tier < len(names):
                norm = normalize_name(names[tier])
                indices = {
                    index for index in monitor_indices_by_norm.get(norm, []) if index in available
                }
            candidates[position] = indices

        counts: dict[int, int] = {}
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

    _log_monitors_taken_by_higher_precedence(
        containers, names_by_container, monitor_indices_by_norm, monitors, unresolved
    )
    return _drop_stable_id_collisions(matched_by_container)
