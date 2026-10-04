# Autoheal Repository Guide

## Project

Autoheal monitors Docker containers, checks their health, and can restart or quarantine them. The FastAPI backend lives in `app/` (monitoring in `app/monitor/`, Docker access in `app/docker_client/`, API in `app/api/`); the React/Vite UI lives in `frontend/src/`. Deployment uses `Dockerfile` and the Compose files. Changes to container lifecycle and recovery need particular care.

## Commands

- Install Python dev dependencies: `pip install -r requirements-dev.txt`.
- Unit tests: `pytest`, or a focused path under `app/tests/unit/`.
- Coverage, when relevant: `pytest --cov=app --cov-report=term-missing`.
- Integration tests in `app/tests/integration/` need a Docker daemon and sometimes a running service. Plain `pytest` does not collect them. See `docs/developer/testing.md`.
- Frontend, from `frontend/`: `npm run test`, `npm run lint`, and `npm run build`, as relevant to the change.
- Validation scope: follow `.claude/rules/testing.md`. CI is authoritative for repository-wide checks.
- MegaLinter findings: follow `.claude/rules/megalinter.md`. It covers this repository's lint job, not application architecture.

## Working rules

- Read the actual implementation, tests, and relevant configuration before deciding on a change.
- For external APIs, workflow syntax, and schemas, verify current documentation or established examples rather than guessing.
- If the request is ambiguous in a way that would materially change the implementation, ask before changing anything. Relay any open questions from `analyze`. Don't ask about details existing patterns already settle.
- For complex changes, summarise the approach and wait for a go-ahead before implementing. Complex means container lifecycle or restart logic, several components, or ambiguity left after `analyze`. Do the same whenever the user asks for a plan. Otherwise, implement directly.
- Work within the requested scope and follow existing patterns.
- Prefer existing mechanisms over new infrastructure. Use the `simplification-review` skill before adding tooling, automation, dependencies, or infrastructure.
- Add regression tests for behaviour fixes where practical.
- Update documentation when a change makes it inaccurate.
- Don't fix unrelated failures, and never weaken validation to make CI green.
- Review the final diff before reporting.
- Never report work, investigation, reproduction, validation, or review that was not actually performed.
- If repository instructions conflict, follow the more restrictive one, continue the task, and report the conflict.

## Issues and labels

- Search existing issues before proposing a new one, and ask before creating a missing one.
- Don't add, remove, or request GitHub issue labels. Classification and workflow labels belong to the automated triage workflow. PR labels are separate.

## Branches, commits and PRs

- Name task branches `<type>/<issue-number>-<short-slug>`, e.g. `fix/353-restart-handling`. If there's no issue, use `<type>/<short-slug>`, e.g. `docs/update-readme`.
  - Types: `feat`, `fix`, `chore`, `refactor`, `test`, `ci`, `docs`, `perf`, `build`, `style`. Pick the one that matches the work; don't default to `feat`/`chore`.
  - Issue number: digits only, no `#`. If an issue exists but you can't find its number, **stop and ask**; never invent one.
  - Slug: **2–5 meaningful words**, lowercase kebab-case, ideally ≤40 characters.
  - Never use random or generated names, UUIDs, timestamps, usernames, or similar non-descriptive names.
  - **Validate the branch name before committing or opening a PR.** If it doesn't comply, rename it before continuing. If already pushed, follow the existing safe branch-rename guidance.
- Commit, push, and open a PR on a feature branch unless the user says not to. Respect local-only, no-commit, no-push, and no-PR requests.
- Never push to a protected branch, force-push, or bypass hooks. Don't overwrite unrelated local changes.
- When branch currency matters, merge `origin/main` as directed by `.claude/rules/branch-currency.md`. Don't update merely because `main` moved.
- PR titles use Conventional Commits (`<type>: <description>`). The title check enforces this.
- PRs that change application behaviour or add real scope need a linked issue (`Closes #N`). Mechanical docs, config, or CI-only tweaks and Renovate PRs are exempt.
- Never merge a PR. The repository owner is the final gatekeeper.

## Review gate

- A PR is substantive if it changes, or could affect, any of these: application code, Docker/Compose behaviour, tests, CI/CD, build or release logic, workflows or automation, or security/dependency config. Docs, comments, formatting, or metadata only is not substantive. If in doubt, treat it as substantive.
- After locally validating and pushing a substantive PR targeting `main`, run the `coderabbit-review` skill before reporting the PR ready for the owner's merge decision. It is an independent gate, not a step in a sequence with the agents.
- `REVIEW.md` defines the evidence standard for local reviews. GitHub automatic CodeRabbit reviews stay disabled; chat replies are enabled.

## Governance

- Treat changes to `CLAUDE.md`, `.claude/`, and other agent-governance files as their own scope, not incidental application cleanup.
- Don't weaken governance to make a task easier.
- Keep `.claude/settings.json` consistent with this file.

<!-- settings.json guardrails are pattern-based and partial; branch protection on main is the authoritative control. -->

## Session titles

Claude can't set a session title itself, so propose one in this format:

- `I: #N - <issue title>`
- `I: #N PR: #N - <issue title>`, once a PR exists
- `PR: #N - <PR title>`, when there is no linked issue

## Agents and skills

The agents (`analyze`, `implement`, `pr-monitor`, `surgical-reviewer`, `test-validator`) and skills are optional tools chosen per task, not a mandatory sequence.
