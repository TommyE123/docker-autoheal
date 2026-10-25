"""
Unit tests for optional API-key authentication (``app/api/auth.py``).

Requests go through the real ASGI app with a tiny in-process caller (see
``test_api_routing.py`` for why there is no ``TestClient``). ``configure_api_auth``
is driven through the environment so the real startup path is exercised.
"""

import json
import logging
from typing import TYPE_CHECKING, Any

import pytest
from starlette.requests import Request

from app.api import auth
from app.api.api import _schema_url, app

if TYPE_CHECKING:
    from collections.abc import MutableMapping

KEY = "test-key-not-a-real-secret"
PROTECTED = ["/api/maintenance/status", "/api/status", "/api/events"]
PROTECTED_WITH_ROOT = [*PROTECTED, "/api", "/api/"]
# The docs are open (a browser cannot send the key header when you open a page).
DOCS = ["/api/swagger", "/api/redoc", "/api/openapi.json"]
# Swagger UI's setting that turns Try it out off for every method.
TRY_IT_OUT_OFF = b'"supportedSubmitMethods": []'


async def _request(
    path: str, headers: dict[str, str] | None = None, root_path: str = ""
) -> tuple[int, bytes, dict]:
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": root_path,
        "headers": [(b"host", b"testserver")]
        + [(k.lower().encode(), v.encode("utf-8")) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "app": app,
    }
    status = 0
    response_headers: dict[str, str] = {}
    body = b""

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal status, response_headers, body
        if message["type"] == "http.response.start":
            status = message["status"]
            response_headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            body += message.get("body", b"")

    await app(scope, receive, send)
    return status, body, response_headers


@pytest.fixture(autouse=True)
def _reset_auth(monkeypatch):
    monkeypatch.delenv(auth.API_KEY_ENV, raising=False)
    monkeypatch.delenv(auth.API_KEY_FILE_ENV, raising=False)
    monkeypatch.setattr(auth._state, "key", None)


@pytest.fixture
def auth_enabled(monkeypatch):
    monkeypatch.setenv(auth.API_KEY_ENV, KEY)
    assert auth.configure_api_auth() is True


@pytest.mark.asyncio
class TestAuthDisabled:
    async def test_not_configured_leaves_auth_disabled(self):
        assert auth.configure_api_auth() is False

    @pytest.mark.parametrize("path", PROTECTED)
    async def test_api_is_open(self, path):
        status, _, _ = await _request(path)

        assert status == 200

    @pytest.mark.parametrize("path", DOCS)
    async def test_docs_are_served_without_a_key(self, path):
        status, _, _ = await _request(path)

        assert status == 200

    async def test_swagger_is_a_read_only_reference_without_a_key(self):
        # No key means nothing protects the calls, so Try it out is switched off.
        _, body, _ = await _request("/api/swagger")

        assert TRY_IT_OUT_OFF in body

    async def test_health_is_open(self):
        status, _, _ = await _request("/health")

        assert status == 200


@pytest.mark.asyncio
@pytest.mark.usefixtures("auth_enabled")
class TestAuthEnabled:
    async def test_bare_api_path_requires_key(self):
        status, _, _ = await _request("/api")

        assert status == 401

    async def test_look_alike_paths_are_not_api_paths(self):
        # /apix is not under /api, so it is the public UI shell like any other page.
        status, _, headers = await _request("/apix")

        assert status == 200
        assert headers["content-type"].startswith("text/html")

    @pytest.mark.parametrize("path", PROTECTED_WITH_ROOT)
    async def test_root_path_prefix_does_not_bypass_auth(self, path):
        # Routing strips root_path before matching, so the check must too.
        status, _, _ = await _request(f"/autoheal{path}", root_path="/autoheal")

        assert status == 401

    async def test_root_path_with_valid_key_is_accepted(self):
        status, _, _ = await _request(
            "/autoheal/api/maintenance/status", {"X-API-Key": KEY}, root_path="/autoheal"
        )

        assert status == 200

    @pytest.mark.parametrize("path", PROTECTED)
    async def test_missing_key_is_401(self, path):
        status, _, headers = await _request(path)

        assert status == 401
        assert headers["www-authenticate"] == "X-API-Key"

    @pytest.mark.parametrize("path", PROTECTED)
    async def test_wrong_key_is_401(self, path):
        status, _, _ = await _request(path, {"X-API-Key": "wrong"})

        assert status == 401

    @pytest.mark.parametrize("path", DOCS)
    async def test_docs_load_without_the_key_header(self, path):
        # A browser cannot add a header when you open a page, so the docs are not key-gated.
        status, _, _ = await _request(path)

        assert status == 200

    @pytest.mark.parametrize("path", DOCS)
    async def test_docs_load_under_a_root_path_too(self, path):
        status, _, _ = await _request(f"/autoheal{path}", root_path="/autoheal")

        assert status == 200

    @pytest.mark.parametrize("page", ["/api/swagger", "/api/redoc"])
    async def test_docs_fetch_the_schema_through_the_proxy_prefix(self, page):
        # Behind a prefix-adding reverse proxy the browser must request the schema
        # under that prefix, not at the site root.
        _, body, _ = await _request(f"/autoheal{page}", root_path="/autoheal")

        assert b"/autoheal/api/openapi.json" in body

    @pytest.mark.parametrize(
        ("root_path", "expected"),
        [("", "/api/openapi.json"), ("/", "/api/openapi.json"), ("/a/", "/a/api/openapi.json")],
    )
    def test_schema_url_has_no_doubled_slash(self, root_path, expected):
        assert (
            _schema_url(Request({"type": "http", "root_path": root_path, "headers": []}))
            == expected
        )

    async def test_docs_fetch_the_schema_from_the_root_without_a_prefix(self):
        _, body, _ = await _request("/api/swagger")

        assert b"/api/openapi.json" in body
        assert b"/autoheal" not in body

    async def test_swagger_offers_try_it_out_when_a_key_is_set(self):
        _, body, _ = await _request("/api/swagger")

        assert TRY_IT_OUT_OFF not in body

    async def test_a_trailing_slash_docs_path_is_not_exempt(self):
        status, _, _ = await _request("/api/swagger/")

        assert status == 401

    async def test_non_ascii_key_is_401_not_an_error(self):
        status, _, _ = await _request("/api/maintenance/status", {"X-API-Key": "kéy"})

        assert status == 401

    @pytest.mark.parametrize("path", PROTECTED)
    async def test_valid_key_is_accepted(self, path):
        status, _, _ = await _request(path, {"X-API-Key": KEY})

        assert status == 200

    async def test_unknown_api_path_requires_key(self):
        status, _, _ = await _request("/api/definitely-not-a-route")

        assert status == 401

    async def test_health_is_open(self):
        status, _, _ = await _request("/health")

        assert status == 200

    async def test_ui_shell_stays_public_so_it_can_prompt(self):
        status, _, headers = await _request("/containers")

        assert status == 200
        assert headers["content-type"].startswith("text/html")

    async def test_openapi_schema_declares_the_api_key_scheme_for_swagger_authorize(self):
        # Swagger UI's Authorize button is built from this scheme; every operation needs it.
        _, body, _ = await _request("/api/openapi.json")
        schema = json.loads(body)

        assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
        assert all(
            operation.get("security")
            for path_item in schema["paths"].values()
            for operation in path_item.values()
        )
        assert KEY.encode() not in body


class TestKeyLoading:
    def test_env_key_is_stripped(self, monkeypatch):
        monkeypatch.setenv(auth.API_KEY_ENV, f"  {KEY}\n")

        assert auth.load_api_key() == KEY

    def test_key_file_is_read_and_stripped(self, monkeypatch, tmp_path):
        key_file = tmp_path / "key"
        key_file.write_text(f"{KEY}\n")
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(key_file))

        assert auth.load_api_key() == KEY

    def test_file_takes_precedence_over_env(self, monkeypatch, tmp_path):
        key_file = tmp_path / "key"
        key_file.write_text("from-file")
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(key_file))
        monkeypatch.setenv(auth.API_KEY_ENV, "from-env")

        assert auth.load_api_key() == "from-file"

    @pytest.mark.asyncio
    async def test_key_from_file_is_enforced(self, monkeypatch, tmp_path):
        key_file = tmp_path / "key"
        key_file.write_text(KEY)
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(key_file))
        auth.configure_api_auth()

        assert (await _request("/api/maintenance/status"))[0] == 401
        assert (await _request("/api/maintenance/status", {"X-API-Key": KEY}))[0] == 200

    def test_missing_file_fails_closed(self, monkeypatch, tmp_path):
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(tmp_path / "absent"))

        with pytest.raises(auth.ApiKeyConfigError, match="could not be read"):
            auth.configure_api_auth()

    def test_unreadable_file_fails_closed(self, monkeypatch, tmp_path):
        # A directory cannot be read as a file, on any platform or user (incl. root).
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(tmp_path))

        with pytest.raises(auth.ApiKeyConfigError):
            auth.configure_api_auth()

    def test_empty_file_fails_closed(self, monkeypatch, tmp_path):
        key_file = tmp_path / "key"
        key_file.write_text("\n")
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(key_file))

        with pytest.raises(auth.ApiKeyConfigError, match="empty"):
            auth.configure_api_auth()

    def test_bad_file_does_not_fall_back_to_env_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(tmp_path / "absent"))
        monkeypatch.setenv(auth.API_KEY_ENV, KEY)

        with pytest.raises(auth.ApiKeyConfigError):
            auth.configure_api_auth()

    def test_empty_env_fails_closed(self, monkeypatch):
        monkeypatch.setenv(auth.API_KEY_ENV, "   ")

        with pytest.raises(auth.ApiKeyConfigError, match="empty"):
            auth.configure_api_auth()

    def test_failed_configure_leaves_previous_state_untouched(self, monkeypatch):
        monkeypatch.setattr(auth._state, "key", b"previous")
        monkeypatch.setenv(auth.API_KEY_ENV, "")

        with pytest.raises(auth.ApiKeyConfigError):
            auth.configure_api_auth()

        assert auth._state.key == b"previous"


class TestKeyIsNeverLogged:
    def test_enabled_and_disabled_messages_exclude_the_key(self, monkeypatch, caplog):
        caplog.set_level(logging.DEBUG)
        auth.configure_api_auth()
        monkeypatch.setenv(auth.API_KEY_ENV, KEY)
        auth.configure_api_auth()

        assert "enabled" in caplog.text
        assert "disabled" in caplog.text
        assert KEY not in caplog.text

    def test_config_errors_exclude_the_key(self, monkeypatch, tmp_path):
        key_file = tmp_path / "key"
        key_file.write_text("")
        monkeypatch.setenv(auth.API_KEY_FILE_ENV, str(key_file))
        monkeypatch.setenv(auth.API_KEY_ENV, KEY)

        with pytest.raises(auth.ApiKeyConfigError) as exc:
            auth.configure_api_auth()

        assert KEY not in str(exc.value)


class TestRoutePath:
    @pytest.mark.parametrize(
        ("path", "root_path", "expected"),
        [
            ("/api/x", "", "/api/x"),
            ("/autoheal/api/x", "/autoheal", "/api/x"),
            ("/autoheal", "/autoheal", ""),
            ("/autoheal/", "/autoheal", "/"),
            # Not a whole segment: routing does not strip it, so neither do we.
            ("/autoheal2/api/x", "/autoheal", "/autoheal2/api/x"),
            # Path that does not carry the root_path is left alone.
            ("/api/x", "/autoheal", "/api/x"),
        ],
    )
    def test_matches_how_routing_strips_root_path(self, path, root_path, expected):
        assert auth._route_path({"path": path, "root_path": root_path}) == expected

    def test_missing_root_path_is_treated_as_empty(self):
        assert auth._route_path({"path": "/api/x"}) == "/api/x"

    @pytest.mark.parametrize(
        ("path", "protected"),
        [
            ("/api", True),
            ("/api/", True),
            ("/api/status", True),
            ("/api/swagger", False),
            ("/api/redoc", False),
            ("/api/openapi.json", False),
            ("/api/swagger/", True),
            ("/apix", False),
            ("/apiary/status", False),
            ("/", False),
            ("/health", False),
            ("", False),
        ],
    )
    def test_protected_paths(self, path, protected):
        assert auth._is_protected(path) is protected
