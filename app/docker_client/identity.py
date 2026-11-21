"""Keys a container's recovery state can be stored under."""


def recovery_keys(recovery_id: str | None, name: str | None, full_id: str | None) -> list[str]:
    """
    Every key a container's quarantine entry can be filed under, in priority order.

    Quarantine is written under ``recovery_id``. Older releases filed it under the
    container name or the full Docker ID, and those entries are still honoured, so
    reading, showing and clearing a container's quarantine must check every form.
    Missing or empty identifiers are skipped and duplicates are kept once, so a
    plain container whose recovery ID is its name yields that key once.

    Args:
        recovery_id: Recovery identifier (``info["recovery_id"]``)
        name: Container name
        full_id: Full Docker container ID

    Returns:
        The distinct keys, ``recovery_id`` first, then the name, then the full ID
    """
    return list(dict.fromkeys(key for key in (recovery_id, name, full_id) if key))
