# Autoheal Repository Guide

## Project

Autoheal monitors Docker containers, checks their health, and can restart or quarantine them. The FastAPI backend lives in `app/` (monitoring in `app/monitor/`, Docker access in `app/docker_client/`, API in `app/api/`); the React/Vite UI lives in `frontend/src/`. Deployment uses `Dockerfile` and the Compose files. Changes to container lifecycle and recovery need particular care.

## Development

- Install Python development dependencies with `pip install -r requirements-dev.txt`; run unit tests with `pytest` or a focused path under `app/tests/unit/`.
- Run `pytest --cov=app --cov-report=term-missing` when coverage is relevant. Integration tests in `app/tests/integration/` require a Docker daemon and sometimes a running service; plain `pytest` does not collect them. See `docs/developer/testing.md`.
- From `frontend/`, use `npm run test`, `npm run lint`, and `npm run build` as relevant to UI changes.
- Follow `.claude/rules/testing.md` for the appropriate validation scope. CI is authoritative for repository-wide checks. `.claude/rules/megalinter.md` covers findings from this repository's MegaLinter lint job; it is not application architecture guidance.

## Working Rules

- Read the actual implementation, tests, and relevant configuration before deciding on a change. For external APIs, workflow syntax, and schemas, verify current documentation or established examples rather than guessing.
- Work within the requested scope, follow existing patterns, prefer existing mechanisms over new infrastructure, and update documentation when a change makes it inaccurate. Add regression tests for behaviour fixes where practical. Do not fix unrelated failures or weaken validation to make CI green.
- Review the final diff and report only validation actually performed. Never merge a PR; the repository owner is the final gatekeeper.
- PR titles must use Conventional Commits (`<type>: <description>`); the title check enforces this. PRs that change application behaviour or add real scope need a linked issue (`Closes #N`). Search existing issues first and ask before creating a missing one. Mechanical docs/config/CI-only tweaks and Renovate PRs are exempt.
- Commit, push, and open a PR on a feature branch when appropriate unless the user says not to. Never push to a protected branch, force-push, or bypass hooks. Do not overwrite unrelated local changes. When branch currency matters, merge `origin/main` as directed by `.claude/rules/branch-currency.md`; do not update merely because `main` moved.
- For a new task branch, prefer `<type>/<issue-number>-<short-slug>` when there is an issue (for example, `fix/353-restart-handling`), or `<type>/<short-slug>` otherwise; keep existing branches as they are, especially once pushed.
- After locally validating and pushing a substantive PR targeting `main`, use the `coderabbit-review` skill before reporting the PR ready for the owner's merge decision; the skill waits for green CI and resolves PR-introduced MegaLinter findings before requesting review. It is an independent review gate, not a step in a required sequence with the agents below. Respect local-only, no-commit, no-push, and no-PR requests.
- Do not add, remove, or request GitHub issue labels: classification and workflow labels belong to the automated triage workflow. PR labels are separate.
- Treat changes to `CLAUDE.md`, `.claude/`, and other agent-governance files as their own scope, not as incidental application cleanup. Do not weaken governance to make a task easier.
- Substantive PR definition: changes or could affect application code, Docker/Compose behaviour, tests, CI/CD, build or release logic, workflows or automation, or security/dependency config; docs, comments, formatting or metadata only is not; if in doubt, treat as substantive.
- If repository instructions conflict, follow the more restrictive one, continue the task, and report the conflict.
- `.claude/settings.json` provides permission-layer guardrails for common dangerous git operations, but it is pattern-based and partial; branch protection on `main` is the authoritative control. Keep it consistent with this file.
- Session titles: `I: #N - <issue title>`, `I: #N PR: #N - <issue title>` once a PR exists, or `PR: #N - <PR title>` with no linked issue.
- If the request is ambiguous in a way that would materially change the implementation, ask the user before changing anything; relay any open questions from `analyze`. Don't ask about details that existing patterns already settle.
- For complex changes (container lifecycle or restart logic, several components, or ambiguity left after `analyze`), summarise the approach and wait for a go-ahead before implementing. Also do this whenever the user asks for a plan. Otherwise go straight to implementing.

## Agents And Skills

Use these independently as needed, not as a mandatory sequence:

- `analyze` agent: clarify requirements, affected code, and validation before implementation; read-only.
- `implement` agent: make an agreed, scoped change with tests and validation.
- `pr-monitor` agent: take one read-only snapshot of a PR and its CI, including MegaLinter findings; no polling.
- `surgical-reviewer` agent: read-only review of the actual diff against the issue and `REVIEW.md`.
- `test-validator` agent: select targeted then appropriately broader checks, fixing only in-scope failures.
- `simplification-review` skill: research simpler alternatives before substantial tooling, automation, or infrastructure changes.
- `coderabbit-review` skill: wait briefly for green PR checks, request CodeRabbit by PR comment, fix in-scope findings, and reply with fixes before a follow-up review. Stop on a timeout or rate limit and resume when asked; never merge.

`REVIEW.md` defines the evidence standard for local reviews. A substantive PR targeting `main` needs a completed CodeRabbit review before the owner merges it. GitHub automatic CodeRabbit reviews remain disabled; chat replies are enabled.
