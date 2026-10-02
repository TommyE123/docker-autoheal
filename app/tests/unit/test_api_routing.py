"""
Unit tests for how ``app/api/api.py`` wires the per-domain routers together.

The split in issue #321 moved route registration into an explicit loop in
``app/api/api.py``. Ordering matters there - the UI router's
``/{full_path:path}`` catch-all has to stay last, or it shadows every router
registered after it - but nothing else in the suite exercises registration:
the other API tests call the endpoint coroutines directly. These tests cover
that gap from both ends: the registered route table itself, and real requests
driven through the ASGI app.

Requests are sent with a tiny in-process ASGI caller rather than
``httpx``/``TestClient``, matching ``test_static_file_serving.py``'s reasoning
- the repository deliberately carries no test-only HTTP client dependency.
``config_manager`` is isolated per test by ``conftest.py``, and no route
reached here touches Docker.
"""

from typing import Any

import pytest
from fastapi.routing import APIRoute

from app.api.api import app
from app.api.routes import (
    config,
    containers,
    events,
    health,
    healthchecks,
    maintenance,
    notifications,
    ui,
    uptime_kuma,
)

CATCH_ALL_PATH = "/{full_path:path}"

# The order `app/api/api.py` must register routers in. `ui` last is the load
# bearing part; the rest pins the order the pre-split module had.
EXPECTED_ROUTER_ORDER = [
    health,
    containers,
    maintenance,
    config,
    healthchecks,
    events,
    uptime_kuma,
    notifications,
    ui,
]


def _iter_api_routes(routes) -> list[APIRoute]:
    """
    Flatten the app's route table into the endpoint routes, in match order.

    FastAPI keeps ``include_router``'d routers nested behind an internal
    wrapper rather than splicing their routes into ``app.routes``, so this
    walks into them. Older FastAPI versions splice instead, which this also
    handles.
    """
    flattened: list[APIRoute] = []
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            flattened.extend(_iter_api_routes(included.routes))
        elif isinstance(route, APIRoute):
            flattened.append(route)
    return flattened


def _registered_routes() -> list[tuple[str, str]]:
    """Every registered ``(method, path)`` pair, in route-matching order."""
    return [
        (method, route.path)
        for route in _iter_api_routes(app.routes)
        for method in sorted(route.methods or ())
    ]


async def _request(
    method: str, path: str, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    """Send one request through the ASGI app and return (status, body, headers)."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")]
        + [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "app": app,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    status: int | None = None
    headers: dict[str, str] = {}
    body = b""

    async def send(message: dict[str, Any]) -> None:
        nonlocal status, headers, body
        if message["type"] == "http.response.start":
            status = message["status"]
            headers = {
                key.decode().lower(): value.decode() for key, value in message["headers"]
            }
        elif message["type"] == "http.response.body":
            body += message.get("body", b"")

    await app(scope, receive, send)
    assert status is not None, "app never started a response"
    return status, body, headers


class TestRouterRegistration:
    def test_every_route_module_is_registered(self):
        registered = set(_registered_routes())

        for module in EXPECTED_ROUTER_ORDER:
            module_routes = {
                (method, route.path)
                for route in _iter_api_routes(module.router.routes)
                for method in sorted(route.methods or ())
            }
            assert module_routes, f"{module.__name__} exposes no routes"
            missing = module_routes - registered
            assert not missing, f"{module.__name__} routes not registered: {sorted(missing)}"

    def test_routers_are_registered_in_the_expected_order(self):
        registered = _registered_routes()

        # Position of each module's first route in the registered table.
        first_positions = []
        for module in EXPECTED_ROUTER_ORDER:
            first = next(
                (method, route.path)
                for route in _iter_api_routes(module.router.routes)
                for method in sorted(route.methods or ())
            )
            first_positions.append((module.__name__, registered.index(first)))

        positions = [position for _, position in first_positions]
        assert positions == sorted(positions), (
            f"routers registered out of order: {first_positions}"
        )

    def test_react_router_catch_all_is_registered_last(self):
        registered = _registered_routes()

        assert registered[-1] == ("GET", CATCH_ALL_PATH)
        assert [path for _, path in registered].count(CATCH_ALL_PATH) == 1

    def test_no_duplicate_method_and_path_pairs(self):
        registered = _registered_routes()

        duplicates = {pair for pair in registered if registered.count(pair) > 1}
        assert not duplicates, f"duplicate routes registered: {sorted(duplicates)}"


@pytest.mark.asyncio
class TestRoutingThroughTheAsgiApp:
    async def test_api_route_resolves_through_its_router(self):
        status, body, _ = await _request("GET", "/api/maintenance/status")

        assert status == 200
        assert b'"maintenance_mode":false' in body.replace(b" ", b"")

    async def test_last_registered_router_is_not_shadowed_by_the_catch_all(self):
        # `notifications` is registered immediately before the UI router, so
        # this is the route that breaks first if the catch-all moves earlier.
        status, body, _ = await _request("GET", "/api/notifications/config")

        assert status == 200
        assert b'"services"' in body

    async def test_unknown_api_path_is_404_not_the_react_app(self):
        status, body, _ = await _request("GET", "/api/definitely-not-a-route")

        assert status == 404
        assert b"<html" not in body.lower()

    async def test_method_mismatch_is_405_not_swallowed_by_the_catch_all(self):
        # The catch-all is GET-only, so a wrong method on a real route must
        # still surface as 405 rather than falling through to the React app.
        status, _, _ = await _request("POST", "/api/events")

        assert status == 405

    async def test_client_side_route_serves_the_react_app(self):
        status, _, headers = await _request("GET", "/dashboard")

        assert status == 200
        assert headers["content-type"].startswith("text/html")

    async def test_nested_client_side_route_serves_the_react_app(self):
        status, _, headers = await _request("GET", "/containers/web/details")

        assert status == 200
        assert headers["content-type"].startswith("text/html")

    async def test_missing_static_asset_is_404_not_the_react_app(self):
        status, body, _ = await _request("GET", "/does-not-exist.css")

        assert status == 404
        assert b"<html" not in body.lower()

    async def test_docs_paths_are_not_swallowed_by_the_catch_all(self):
        status, _, headers = await _request("GET", "/openapi.json")

        assert status == 200
        assert headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
class TestNoCrossOriginAccess:
    """
    The UI is served by this same app, so the API must not grant other
    websites cross-origin access (it has no authentication of its own).
    """

    FOREIGN_ORIGIN = "https://attacker.example"

    async def test_preflight_from_a_foreign_origin_is_not_granted(self):
        _, _, headers = await _request(
            "OPTIONS",
            "/api/config",
            {
                "Origin": self.FOREIGN_ORIGIN,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert "access-control-allow-origin" not in headers
        assert "access-control-allow-credentials" not in headers

    async def test_cross_origin_read_is_not_granted(self):
        status, _, headers = await _request(
            "GET", "/api/maintenance/status", {"Origin": self.FOREIGN_ORIGIN}
        )

        # The request is still served (same-origin UI is unaffected); the
        # browser just isn't told it may expose the response to another site.
        assert status == 200
        assert "access-control-allow-origin" not in headers
