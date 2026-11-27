"""
Shared logging level handling for the observability configuration

Both the startup/hot-reload path in ``app.main`` and the ``/api/config/observability``
route apply the configured level the same way, so the mapping and the uvicorn adjustments
live here rather than in either caller.
"""

import logging

# Names accepted from configuration. ``logging.getLevelNamesMapping()`` (Python 3.11+) also
# returns ``NOTSET``, which would mean "log everything" rather than the INFO fallback used for
# unrecognised names, so it is excluded here to keep that fallback.
_LEVEL_NAMES = {
    name: level for name, level in logging.getLevelNamesMapping().items() if name != "NOTSET"
}


def resolve_log_level(level_name: str) -> int:
    """The numeric level for a configured name, or INFO if the name is not recognised"""
    return _LEVEL_NAMES.get(level_name.upper(), logging.INFO)


def apply_log_level(level_name: str) -> int:
    """Set the root logger to the configured level, hold uvicorn and urllib3 at WARNING, and
    return the level"""
    level = resolve_log_level(level_name)

    # Set root logger level
    logging.getLogger().setLevel(level)

    # Disable uvicorn access logs completely (set to WARNING to suppress INFO logs)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)

    # urllib3 (under requests and the Docker SDK) logs each request line at DEBUG, and a webhook
    # URL's path and query can hold a token.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return level
