# Type annotation policy

Ruff's `ANN` rules are enabled in `.linter-rules/.ruff.toml`. This page records the
policy behind that configuration (issue #341, Phase 8 of the Ruff programme) and the
findings that are deliberately not remediated.

## Baseline (before Phase 8)

Measured with `ruff check . --select ANN` (Ruff 0.16.8, target `py314`, preview off,
Dockerfile `python:3.14-slim`; `ANN` was not previously enabled). The type checker is
pyright in `standard` mode (`pyrightconfig.json`, scope `app/`); it reported no errors
before or after this phase.

| Scope                         | Findings |
|-------------------------------|----------|
| `app/` excluding `app/tests/` | 101      |
| `app/tests/`                  | 2,455    |
| Total                         | 2,556    |

## Policy

- **Scope:** all application code under `app/` is annotated. Tests (`app/tests/`) are
  out of scope and ignore `ANN` through `per-file-ignores`; annotating fixtures and test
  functions adds no value for the tests' consumers.
- **`Any`:** allowed for JSON-shaped payloads, pass-through values and untyped
  third-party boundaries (Docker SDK, aiohttp, config documents). `ANN401` is therefore
  ignored. Prefer a precise type or `object` whenever the real type is known.
- **Forward references:** `from __future__ import annotations` is not adopted. Python
  3.14 evaluates annotations lazily, so type-only imports go in `if TYPE_CHECKING:`
  blocks without quoting.
- **Public API and signatures:** annotations must not change behaviour or signatures.
  Existing annotations are not rewritten.
- **FastAPI route handlers:** FastAPI treats a handler's return annotation as its
  response model, which would change validation and serialisation. Return annotations
  are therefore not added to handlers under `app/api/routes/`, and `ANN201` is ignored
  there. Handlers that return a `Response` subclass are the exception: they are
  annotated because FastAPI does not build a response model for those.
- **`self` / `cls`:** not checked (`ANN101` and `ANN102` no longer exist in Ruff).
- **Third-party boundaries:** `Any`, no stubs or `# type: ignore` added.

## Retained findings

| Rule        | Where                                                                                                                                         | Reason                                               |
|-------------|-----------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------|
| `ANN` (all) | `app/tests/**`, 2,455 findings                                                                                                                | Out of scope; ignored in `per-file-ignores`.         |
| `ANN201`    | `app/api/routes/**`, 37 handlers                                                                                                              | Annotating would create FastAPI response models.     |
| `ANN401`    | 23 `Any` annotations in `app/` (config manager, notification manager, monitoring engine, `init_defaults`, Docker wrapper, Uptime Kuma routes) | Allowed by the `Any` policy above; ignored globally. |

The `ANN401` row counts 23 `Any` annotations in the current tree: the 19 baseline
findings plus 4 `Any` annotations this phase added (`**kwargs` in
`update_partial_config`, `get_events`' return type and `_stripped`'s parameter and return),
all covered by the `Any` policy.
