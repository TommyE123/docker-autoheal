"""Contract between the backend and the browser demo's simulation.

The demo (frontend/src/demo/) re-implements part of the backend in JavaScript:
the API's routes and response fields, the configuration models' validation (from
their JSON Schemas, plus the health check's own validator), and
the monitoring engine's restart, backoff and quarantine decisions. To stop the
two drifting apart, each test here computes the real backend's answers for a
fixed set of cases and compares them with the stored copy in
frontend/src/demo/contract/. The demo's own test (contract.test.js) checks the
JavaScript against the same stored answers.

So a backend change that the demo doesn't copy fails here first. Refresh the
stored answers (and format them for MegaLinter), then make the demo pass
``npm test`` again::

    UPDATE_DEMO_CONTRACT=1 pytest app/tests/unit/test_demo_contract.py
    cd frontend && npx prettier --write src/demo/contract

To cover a new case, add its input to validation.json or scenarios.json and run
the same command.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import app.config.config_manager as config_module
from app.api.api import app
from app.config.config_manager import (
    AutoHealConfig,
    HealthCheckConfig,
    NotificationService,
    config_manager,
)
from app.docker_client.docker_client_wrapper import recovery_identifier
from app.monitor.monitoring_engine import MonitoringEngine
from app.monitor.recovery import RecoveryPolicy
from app.tests.unit.conftest import FakeContainer, FakeDockerClient

CONTRACT_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "demo" / "contract"
UPDATE = os.environ.get("UPDATE_DEMO_CONTRACT") == "1"
REFRESH_HINT = (
    "The backend no longer matches the demo's stored contract. Run "
    "`UPDATE_DEMO_CONTRACT=1 pytest app/tests/unit/test_demo_contract.py` and "
    "`npx prettier --write src/demo/contract` in frontend/, review the diff, then "
    "update frontend/src/demo/ until `npm test` passes (docs/developer/demo.md)."
)

# Scenario times are seconds after this instant.
T0 = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
CONTAINER_ID = "c" * 64


def _load(name: str) -> dict:
    return json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))


def _check(name: str, actual: dict) -> None:
    """Compare ``actual`` with the stored file, or rewrite it when updating."""
    path = CONTRACT_DIR / name
    if UPDATE:
        path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        return
    assert _load(name) == actual, REFRESH_HINT


def test_api_contract():
    """Every route the demo must answer, and the fields of the response models it builds."""
    schema = app.openapi()
    routes = {
        path: sorted(method.upper() for method in operations)
        for path, operations in schema["paths"].items()
        if path == "/health" or path.startswith("/api/")
    }
    models = {
        name: list(schema["components"]["schemas"][name]["properties"])
        for name in ("ContainerInfo", "SystemStatus")
    }
    _check("api-contract.json", {"routes": routes, "models": models})


def test_schema_contract():
    """The JSON Schemas the demo's mock API validates request data against."""
    defs = {}
    for model in (AutoHealConfig, HealthCheckConfig):
        schema = model.model_json_schema()
        defs.update(schema.pop("$defs", {}))
        defs[model.__name__] = schema
    _check("schemas.json", {"$defs": defs})


MODELS = {
    "AutoHealConfig": AutoHealConfig,
    "HealthCheckConfig": HealthCheckConfig,
    "NotificationService": NotificationService,
}


def _validate(model: str, data) -> dict:
    """The model's normalised value, or its errors as the API reports them."""
    try:
        return {"value": MODELS[model].model_validate(data).model_dump(mode="json")}
    except ValidationError as error:
        return {
            "errors": [
                {"type": err["type"], "loc": list(err["loc"]), "msg": err["msg"]}
                for err in error.errors(include_input=False)
            ]
        }


def test_validation_contract():
    """Validation results for the stored inputs (the demo's mock API must agree)."""
    cases = _load("validation.json")["cases"]
    _check(
        "validation.json",
        {
            "cases": [
                {
                    "model": case["model"],
                    "input": case["input"],
                    "expected": _validate(case["model"], case["input"]),
                }
                for case in cases
            ]
        },
    )


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(T0 + seconds, UTC).isoformat().replace("+00:00", "Z")


def _info(engine: MonitoringEngine, labels: dict, step: dict) -> dict:
    """The container info dict for one observed state (see the demo's info())."""
    # The real identity functions, so a change in how these keys are derived
    # changes the stored quarantine_key too.
    stable_id = engine.get_stable_identifier({"labels": labels, "name": "worker"})
    health = {"status": step["health"]} if step["health"] else None
    return {
        "id": CONTAINER_ID[:12],
        "full_id": CONTAINER_ID,
        "name": "worker",
        "stable_id": stable_id,
        "recovery_id": recovery_identifier(stable_id, labels),
        "status": step["status"],
        "state": {
            "Status": step["status"],
            "ExitCode": step["exit_code"],
            "StartedAt": _iso(step["started_at"]),
        },
        "labels": labels,
        "started_at": _iso(step["started_at"]),
        "exit_code": step["exit_code"],
        "health": health,
    }


async def _run_scenario(scenario: dict, monkeypatch) -> list[dict]:
    """Run each observed state through one real monitoring cycle; record what it did."""
    now = [T0]
    monkeypatch.setattr(config_module, "time", SimpleNamespace(time=lambda: now[0]))
    config_manager.update_config(
        AutoHealConfig(**_deep_merge(AutoHealConfig().model_dump(), scenario["config"]))
    )
    docker = FakeDockerClient()
    container = FakeContainer("worker", CONTAINER_ID)
    docker.add_container(container, {})
    engine = MonitoringEngine(docker)
    engine._recovery = RecoveryPolicy(clock=lambda: datetime.fromtimestamp(now[0], UTC))

    results = []
    for step in scenario["steps"]:
        now[0] = T0 + step["at"]
        info = _info(engine, scenario["labels"], step)
        container.status = step["status"]
        docker._info[CONTAINER_ID] = info
        docker.restart_calls.clear()
        seen = len(config_manager.get_events())
        await engine._check_containers()
        results.append(
            {
                "restarted": bool(docker.restart_calls),
                "events": [
                    {
                        "event_type": event.event_type,
                        "restart_count": event.restart_count,
                        "status": event.status,
                        "message": event.message,
                    }
                    for event in config_manager.get_events()[seen:]
                ],
                "quarantined": config_manager.is_quarantined(info["recovery_id"]),
                "quarantine_key": info["recovery_id"],
            }
        )
    return results


@pytest.mark.asyncio
async def test_scenario_contract(monkeypatch, caplog):
    """Decisions of the real engine for the stored timelines (the demo engine must agree)."""
    scenarios = _load("scenarios.json")["scenarios"]
    actual = []
    for scenario in scenarios:
        # Each scenario starts from a clean slate: no events, restarts or quarantine.
        # update_config keeps the live restart counts, so replace the config itself.
        config_manager._config = AutoHealConfig()
        config_manager._event_log = []
        config_manager._quarantined_containers = set()
        caplog.clear()
        expected = await _run_scenario(scenario, monkeypatch)
        # The engine logs and swallows errors per container. One here means the
        # harness no longer fits the engine, not that the engine did nothing.
        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert not errors, f"{scenario['name']}: {errors}"
        actual.append(
            {**{k: v for k, v in scenario.items() if k != "expected"}, "expected": expected}
        )
    _check("scenarios.json", {"scenarios": actual})
