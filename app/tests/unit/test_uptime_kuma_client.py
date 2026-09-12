"""
Unit tests for ``UptimeKumaClient``.

The client always opens a fresh ``aiohttp.ClientSession`` per call rather than
keeping one on the instance, so the aiohttp layer is faked by monkeypatching
``aiohttp.ClientSession`` in the client module to return a canned fake session
(mirroring the approach in ``test_notification_manager.py``). No real network
or WebSocket access is used.

Real Uptime-Kuma ``/metrics`` output emits ``monitor_id`` (and any custom
tags) before ``monitor_name`` in the label set. ``TestParseMonitorsFromMetrics``
covers that ordering (issue #26) alongside ``METRICS_TEXT``'s simpler,
name-first layout.
"""

import base64

import pytest

from app.uptime_kuma.uptime_kuma_client import UptimeKumaClient


def _decode_basic_auth_header(header: str) -> tuple[str, str]:
    scheme, _, encoded = header.partition(" ")
    assert scheme == "Basic"
    login, _, password = base64.b64decode(encoded).decode().partition(":")
    return login, password


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

        login, password = _decode_basic_auth_header(client.auth_header)
        assert login == ""
        assert password == "secret-token"

    def test_user_auth_uses_given_username(self):
        client = UptimeKumaClient("http://kuma.example", "hunter2", "admin")

        login, password = _decode_basic_auth_header(client.auth_header)
        assert login == "admin"
        assert password == "hunter2"

    def test_server_url_trailing_slash_is_stripped(self):
        client = UptimeKumaClient("http://kuma.example/", "token")

        assert client.server_url == "http://kuma.example"


@pytest.mark.asyncio
class TestConnect:
    async def test_sends_authorization_header_instead_of_auth_kwarg(self, monkeypatch):
        session = _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "hunter2", "admin")

        await client.connect()

        call = session.get_calls[0]
        assert call["headers"] == {"Authorization": client.auth_header}
        assert "auth" not in call

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
    async def test_sends_authorization_header_instead_of_auth_kwarg(self, monkeypatch):
        session = _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")

        await client.get_all_monitors()

        call = session.get_calls[0]
        assert call["headers"] == {"Authorization": client.auth_header}
        assert "auth" not in call

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

    async def test_parses_monitors_with_monitor_id_label_before_name(self, monkeypatch):
        """Regression test for #26 through the get_all_monitors() path used by
        the Uptime-Kuma monitor refresh loop."""
        text = (
            'monitor_status{monitor_id="5",monitor_name="My Website",'
            'monitor_type="http",monitor_url="https://example.com/",'
            'monitor_hostname="",monitor_port=""} 1\n'
            'monitor_status{monitor_id="6",monitor_name="Database",'
            'monitor_type="tcp",monitor_url="",monitor_hostname="db.local",'
            'monitor_port="5432"} 0\n'
        )
        _patch_session(monkeypatch, response=_FakeResponse(200, text))
        client = UptimeKumaClient("http://kuma.example", "token")

        monitors = await client.get_all_monitors()

        names_to_status = {m["friendly_name"]: m["status"] for m in monitors}
        assert names_to_status == {"My Website": 1, "Database": 0}


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

    def test_monitor_id_label_before_monitor_name_is_parsed(self):
        """Regression test for #26: real Uptime-Kuma output puts monitor_id
        (and any custom tags) before monitor_name in the label set."""
        client = UptimeKumaClient("http://kuma.example", "token")
        text = (
            'monitor_status{monitor_id="5",monitor_name="My Website",'
            'monitor_type="http",monitor_url="https://example.com/",'
            'monitor_hostname="",monitor_port=""} 1\n'
            'monitor_status{monitor_id="6",monitor_name="Database",'
            'monitor_type="tcp",monitor_url="",monitor_hostname="db.local",'
            'monitor_port="5432"} 0\n'
        )

        monitors = client._parse_monitors_from_metrics(text)

        by_name = {m["friendly_name"]: m["status"] for m in monitors}
        assert by_name == {"My Website": 1, "Database": 0}

    def test_custom_tags_before_monitor_name_are_parsed(self):
        client = UptimeKumaClient("http://kuma.example", "token")
        text = (
            'monitor_status{env="prod",team="infra",monitor_id="1",'
            'monitor_name="Tagged",monitor_type="http",monitor_url="",'
            'monitor_hostname="",monitor_port=""} 1\n'
        )

        monitors = client._parse_monitors_from_metrics(text)

        assert len(monitors) == 1
        assert monitors[0]["friendly_name"] == "Tagged"
        assert monitors[0]["status"] == 1

    def test_custom_tag_whose_name_ends_in_monitor_name_is_not_a_phantom_monitor(self):
        """A custom tag like custom_monitor_name must not be matched as monitor_name
        just because it contains that substring."""
        client = UptimeKumaClient("http://kuma.example", "token")
        text = 'monitor_status{custom_monitor_name="ghost"} 1\n'

        monitors = client._parse_monitors_from_metrics(text)

        assert monitors == []


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
    async def test_sends_authorization_header_instead_of_auth_kwarg(self, monkeypatch):
        session = _patch_session(monkeypatch, response=_FakeResponse(200, METRICS_TEXT))
        client = UptimeKumaClient("http://kuma.example", "token")

        await client.get_monitor_status_by_name("API")

        call = session.get_calls[0]
        assert call["headers"] == {"Authorization": client.auth_header}
        assert "auth" not in call

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

    async def test_returns_status_when_monitor_id_precedes_name(self, monkeypatch):
        """Regression test for #26."""
        text = (
            'monitor_status{monitor_id="5",monitor_name="My Website",'
            'monitor_type="http"} 1\n'
        )
        _patch_session(monkeypatch, response=_FakeResponse(200, text))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status_by_name("My Website") == 1

    async def test_custom_tag_whose_name_ends_in_monitor_name_is_not_matched(self, monkeypatch):
        """A custom tag like custom_monitor_name must not be matched as monitor_name
        just because it contains that substring."""
        text = 'monitor_status{custom_monitor_name="ghost"} 1\n'
        _patch_session(monkeypatch, response=_FakeResponse(200, text))
        client = UptimeKumaClient("http://kuma.example", "token")

        assert await client.get_monitor_status_by_name("ghost") is None
