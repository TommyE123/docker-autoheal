"""
Container selection for Docker Auto-Heal Service
Decides, from configuration and container information alone, whether a container is monitored
"""

import fnmatch
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config.config_manager import AutoHealConfig, FiltersConfig

logger = logging.getLogger(__name__)


def _listed(config_names: list[str], info: dict, stable_id: str | None) -> bool:
    """Whether a container is named in a selected or excluded list, by any of its identities"""
    labels = info.get("labels", {})
    compose_service = labels.get("com.docker.compose.service")
    return bool(
        stable_id in config_names
        or info.get("full_id") in config_names
        or info.get("id") in config_names
        or info.get("name") in config_names
        or (compose_service and compose_service in config_names)
    )


def _has_monitor_label(config: AutoHealConfig, labels: dict) -> bool:
    """Whether the container passes the label gate that applies when include_all is off"""
    if config.monitor.include_all:
        return True
    label_key = config.monitor.label_key
    return label_key in labels and labels[label_key] == config.monitor.label_value


def _matches_any_name(patterns: list[str], name: str | None) -> bool:
    return name is not None and any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _matches_any_label(label_filters: list[dict], labels: dict) -> bool:
    return any(
        labels.get(key) == value
        for label_filter in label_filters
        for key, value in label_filter.items()
    )


def _passes_filters(filters: FiltersConfig, name: str | None, labels: dict) -> bool:
    """Whether the container clears the blacklists and, where set, the whitelists"""
    if _matches_any_name(filters.blacklist_names, name):
        return False
    if _matches_any_label(filters.blacklist_labels, labels):
        return False
    names_ok = not filters.whitelist_names or _matches_any_name(filters.whitelist_names, name)
    labels_ok = not filters.whitelist_labels or _matches_any_label(filters.whitelist_labels, labels)
    return names_ok and labels_ok


def should_monitor(config: AutoHealConfig, info: dict, stable_id: str | None) -> bool:
    """
    Determine if a container should be monitored for auto-healing

    Args:
        config: Current configuration
        info: Container information dict
        stable_id: The container's stable identifier (see ``get_stable_identifier``)

    Returns:
        True if the container should be monitored, False otherwise
    """
    labels = info.get("labels", {})
    name = info.get("name")

    if _listed(config.containers.excluded, info, stable_id):
        return False

    if _listed(config.containers.selected, info, stable_id):
        logger.debug(
            "Container %s (stable_id: %s) explicitly selected for monitoring", name, stable_id
        )
        return True

    return _has_monitor_label(config, labels) and _passes_filters(config.filters, name, labels)
