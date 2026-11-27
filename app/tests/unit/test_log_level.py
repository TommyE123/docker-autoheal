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


QUIETED_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error", "urllib3")
LOGGER_NAMES = ("", *QUIETED_LOGGERS)


@pytest.fixture
def restore_logger_levels():
    previous = {name: logging.getLogger(name).level for name in LOGGER_NAMES}
    yield
    for name, level in previous.items():
        logging.getLogger(name).setLevel(level)


@pytest.mark.usefixtures("restore_logger_levels")
def test_apply_log_level_sets_root_and_quiets_library_loggers():
    assert apply_log_level("debug") == logging.DEBUG
    assert logging.getLogger().level == logging.DEBUG
    for name in QUIETED_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


@pytest.mark.usefixtures("restore_logger_levels")
def test_debug_level_does_not_log_webhook_request_lines(caplog):
    """urllib3's DEBUG request line carries the webhook path and query, so it must not reach logs"""
    apply_log_level("DEBUG")
    caplog.set_level(logging.NOTSET)  # capture whatever the loggers themselves let through

    logging.getLogger("urllib3.connectionpool").debug('https://hooks.invalid:443 "POST /h/TOKEN"')

    assert "TOKEN" not in caplog.text
