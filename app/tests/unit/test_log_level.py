import logging

import pytest

from app.utils.log_level import apply_log_level, resolve_log_level


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("DEBUG", logging.DEBUG),
        ("info", logging.INFO),
        ("Warning", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("critical", logging.CRITICAL),
        ("WARN", logging.WARNING),
        ("FATAL", logging.CRITICAL),
    ],
)
def test_resolve_log_level_maps_known_names(name, expected):
    assert resolve_log_level(name) == expected


@pytest.mark.parametrize("name", ["NOT_A_LEVEL", "NOTSET", ""])
def test_resolve_log_level_falls_back_to_info(name):
    assert resolve_log_level(name) == logging.INFO


def test_apply_log_level_sets_root_and_uvicorn_loggers():
    root = logging.getLogger()
    previous = root.level
    try:
        assert apply_log_level("debug") == logging.DEBUG
        assert root.level == logging.DEBUG
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            assert logging.getLogger(name).level == logging.WARNING
    finally:
        root.setLevel(previous)
