"""Deterministic matching between Docker containers and Uptime-Kuma monitors.

Safety-critical: AutoHeal uses this mapping to decide which container an
Uptime-Kuma monitor's status applies to. A false positive here could
therefore associate a monitor with the wrong container. The matcher only
ever produces a mapping when a container and a monitor uniquely identify
each other after normalization - no fuzzy/string-distance matching, and no
"closest match" fallback. See issue #141.
"""

import re
from typing import Dict, Iterable, List, Optional, TypedDict


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

    monitor_names_by_norm: Dict[str, set] = {}
    for monitor in monitors:
        friendly_name = monitor["friendly_name"]
        monitor_names_by_norm.setdefault(normalize_name(friendly_name), set()).add(friendly_name)

    container_matches: List[set] = []
    for container in containers:
        candidates = {container["name"]}
        compose_service = container.get("compose_service")
        if compose_service:
            candidates.add(compose_service)

        matched_names: set = set()
        for candidate in candidates:
            matched_names |= monitor_names_by_norm.get(normalize_name(candidate), set())
        container_matches.append(matched_names)

    monitor_match_counts: Dict[str, int] = {}
    for matched_names in container_matches:
        for name in matched_names:
            monitor_match_counts[name] = monitor_match_counts.get(name, 0) + 1

    results: List[UptimeKumaMatch] = []
    for container, matched_names in zip(containers, container_matches):
        if len(matched_names) != 1:
            continue
        (monitor_friendly_name,) = matched_names
        if monitor_match_counts[monitor_friendly_name] != 1:
            continue
        results.append(
            {
                "container_id": container["stable_id"],
                "monitor_friendly_name": monitor_friendly_name,
            }
        )
    return results
