"""
Unit tests for ``UptimeKumaClient``.

The client always opens a fresh ``aiohttp.ClientSession`` per call rather than
keeping one on the instance, so the aiohttp layer is faked by monkeypatching
``aiohttp.ClientSession`` in the client module to return a canned fake session
(mirroring the approach in ``test_notification_manager.py``). No real network
or WebSocket access is used.

Note: parsing tests here use metrics text with ``monitor_name`` as the first
label, matching what the current parsing regex actually looks for. Issue #26
tracks a separate bug where real Uptime-Kuma output places other labels (e.g.
``monitor_id``) before ``monitor_name``, which the current regex misses; a
regression test for that belongs to #26/its fix, not here.
"""

import pytest
from aiohttp import BasicAuth

from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient

METRICS_TEXT = (
    'monitor_status{monitor_name="Web",monitor_type="http"} 1\n'
    'monitor_status{monitor_name="API",monitor_type="http"} 0\n'
    'app_version{version="1.23.0"} 1\n'
)


class _FakeResponse:
    def __init__(self, status: int = 200, text: str = ""):
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeGet:
    """Async context manager returned by ``session.get()``."""

    def __init__(self, response=None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    def __init__(self, response=None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.get_calls: list[dict] = []

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return _FakeGet(self._response, self._exc)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _patch_session(monkeypatch, response=None, exc: Exception | None = None) -> _FakeSession:
    session = _FakeSession(response=response, exc=exc)
    monkeypatch.setattr(
        "app.uptime_kuma.uptime_kuma_client.aiohttp.ClientSession",
        lambda *a, **k: session,
    )
    return session


class TestInit:
    def test_api_key_auth_uses_empty_username(self):
        client = UptimeKumaClient("http://kuma.example", "secret-token")

        assert isinstance(client.auth, BasicAuth)
        assert client.auth.login == ""
        assert client.auth.password == "secret-token"

    def test_user_auth_uses_given_username(self):
        client = UptimeKumaClient("http://kuma.example", "hunter2", "admin")

        assert client.auth.login == "admin"
        assert client.auth.password == "hunter2"

    def test_server_url_trailing_slash_is_stripped(self):
        client = UptimeKumaClient("http://kuma.example/", "token")

        assert client.server_url == "http://kuma.example"


@pytest.mark.asyncio
class TestConnect:
    async def test_returns_true_when_monitor_status_present(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.connect() is True

    async def test_returns_true_when_only_app_version_present(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, 'app_version{version="1.0"} 1\n'))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.connect() is True

    async def test_returns_false_when_response_has_no_metrics_markers(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, "not metrics data"))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.connect() is False

    async def test_returns_false_on_non_200_status(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(401, ""))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.connect() is False

    async def test_returns_false_on_connection_error(self, monkeypatch):
        _patch_session(monkeypatch, exc=ConnectionError("refused"))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.connect() is False


@pytest.mark.asyncio
class TestGetAllMonitors:
    async def test_parses_monitors_from_metrics_response(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")

        monitors = await client.get_all_monitors()

        names_to_status = {m["friendly_name"]: m["status"] for m in monitors}
        assert names_to_status == {"Web": 1, "API": 0}

    async def test_returns_empty_list_on_non_200_status(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(500, ""))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_all_monitors() == []

    async def test_returns_empty_list_on_request_failure(self, monkeypatch):
        _patch_session(monkeypatch, exc=TimeoutError("timed out"))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_all_monitors() == []

    async def test_returns_empty_list_when_no_monitor_lines_match(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, "some_other_metric 1\n"))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_all_monitors() == []


class TestParseMonitorsFromMetrics:
    """Direct tests of the parsing logic, independent of the HTTP layer."""

    def test_generates_stable_id_for_same_name(self):
        client = UptimeKumaClient("http://kuma.example", "token")

        first = client._parse_monitors_from_metrics(METRICS_TEXT)
        second = client._parse_monitors_from_metrics(METRICS_TEXT)

        first_web = next(m for m in first if m["friendly_name"] == "Web")
        second_web = next(m for m in second if m["friendly_name"] == "Web")
        assert first_web["id"] == second_web["id"]

    def test_duplicate_monitor_names_collapse_to_one_entry(self):
        client = UptimeKumaClient("http://kuma.example", "token")
        text = (
            'monitor_status{monitor_name="Web"} 1\n'
            'monitor_status{monitor_name="Web"} 0\n'
        )

        monitors = client._parse_monitors_from_metrics(text)

        assert len(monitors) == 1
        # Later occurrence wins since entries are keyed by name in a dict.
        assert monitors[0]["status"] == 0


@pytest.mark.asyncio
class TestGetMonitorStatus:
    async def test_returns_status_for_matching_id(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")
        monitors = await client.get_all_monitors()
        web_id = next(m["id"] for m in monitors if m["friendly_name"] == "Web")

        assert await client.get_monitor_status(web_id) == 1

    async def test_returns_none_for_unknown_id(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status(999999999) is None


@pytest.mark.asyncio
class TestGetMonitorStatusByName:
    async def test_returns_status_for_known_monitor(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status_by_name("API") == 0

    async def test_returns_none_for_unknown_monitor(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status_by_name("Nonexistent") is None

    async def test_returns_none_on_non_200_status(self, monkeypatch):
        _patch_session(monkeypatch, response=_FakeResponse(503, ""))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status_by_name("Web") is None

    async def test_returns_none_on_request_failure(self, monkeypatch):
        _patch_session(monkeypatch, exc=OSError("network unreachable"))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status_by_name("Web") is None

    async def test_monitor_name_with_regex_special_characters_is_escaped(self, monkeypatch):
        text = 'monitor_status{monitor_name="DB (prod)"} 1\n'
        _patch_session(monkeypatch, response=_FakeResponse(200, text))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status_by_name("DB (prod)") == 1
