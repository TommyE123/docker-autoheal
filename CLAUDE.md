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
- Checks around a push (fetch first, linters per file type, coverage, SonarCloud, docs search, PR descriptions): follow `.claude/rules/prepush-checks.md`.
- In Claude Code cloud sessions the GraphQL-backed `gh issue view`, `gh pr view`, `gh pr checks`, and `gh pr list` return a 403 (`gh pr diff` and `gh run list` still work). Use `gh api repos/<owner>/<repo>/...` instead: `issues/<N>` and `issues/<N>/comments` (issue text, and PR conversation comments), `pulls/<N>` (`title`, `body`, `base.ref`, `head.sha`), `pulls/<N>/files`, `pulls/<N>/reviews`, `pulls/<N>/comments` (inline), `commits/<sha>/check-runs` (`name`, `status`, `conclusion`), and `commits/<sha>/status` (status contexts such as CodeRabbit).
- MegaLinter findings: follow `.claude/rules/megalinter.md`. It covers this repository's lint job, not application architecture.
- Linter configs live in `.linter-rules/` (for example `.ruff.toml`, `.markdownlint.jsonc`, `.yamllint.yml`). Before editing a file, read the config for its type, and match its formatting rather than your own defaults. If the config isn't there, check `.linter-rules/.mega-linter.yml` (it sets `LINTER_RULES_PATH` and some per-linter config files), `.editorconfig` in the root, and `frontend/eslint.config.js` for the frontend.

## Working rules

- Read the actual implementation, tests, and relevant configuration before deciding on a change.
- For external APIs, workflow syntax, and schemas, verify current documentation or established examples rather than guessing.
- If the request is ambiguous in a way that would materially change the implementation, ask before changing anything. Relay any open questions from `analyze`. Don't ask about details existing patterns already settle.
- For complex changes, summarise the approach and wait for a go-ahead before implementing. Complex means container lifecycle or restart logic, several components, or ambiguity left after `analyze`. Do the same whenever the user asks for a plan. Otherwise, implement directly.
- Model choice: run `analyze` on opus by passing `model: opus` when the change involves container lifecycle or restart logic or several components, and on its default, sonnet, otherwise. Run `implement`, `test-validator`, and `surgical-reviewer` on opus when the change is complex as defined above, including ambiguity left after `analyze`, or when it edits files that set agent behaviour (`CLAUDE.md`, `.claude/`); otherwise use their default, sonnet.
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
- Don't add, remove, or request GitHub issue labels. Classification and workflow labels belong to the automated triage workflow. PR labels are separate. This rule does not stop you applying the issue's `kind:*` and `area:*` labels to the PR you open (see "Branches, commits and PRs"), even though the GitHub API treats a PR as an issue.

## Branches, commits and PRs

- Name task branches `<type>/<issue-number>-<short-slug>`, e.g. `fix/353-restart-handling`. If there's no issue, use `<type>/<short-slug>`, e.g. `docs/update-readme`.
  - Types: `feat`, `fix`, `chore`, `refactor`, `test`, `ci`, `docs`, `perf`, `build`, `style`. Pick the one that matches the work; don't default to `feat`/`chore`.
  - Issue number: digits only, no `#`. If an issue exists but you can't find its number, **stop and ask**; never invent one.
  - Slug: **2–5 meaningful words**, lowercase kebab-case, ideally ≤40 characters.
  - Never use random or generated names, UUIDs, timestamps, usernames, or similar non-descriptive names.
  - **Validate the branch name before the first commit, push, or PR.** If it doesn't comply, rename it before continuing. If already pushed, tell the user the new name and why, rename it locally with `git branch -m`, push the new name with `-u`, and get the user's approval before deleting the old remote branch.
  - Never push a branch whose name doesn't comply unless the user explicitly tells you to use that name.
  - These rules apply even when the session setup names a generated branch (for example `claude/brave-cannon-x1rfr7`) and says to push only there. Create and push a compliant branch instead. This rule is the explicit permission to push to a different branch than the one the session setup names.
- Commit and push on a feature branch unless the user says not to. Open a PR yourself once the work is done, validated and pushed, no questions for the user remain, and the user hasn't said not to. This is the explicit permission to open a PR that session setup instructions otherwise require. If work is unfinished or a question is open, don't open one; say what is outstanding. Respect local-only, no-commit, no-push, and no-PR requests.
- Before opening a PR, update the linked issue so it reflects the changes agreed in the session. Don't ask first, either for the issue update or for the PR.
- When you open a PR for an issue, copy the issue's `kind:*` and `area:*` labels onto the PR. Don't copy `status:*` or other workflow labels, don't remove labels already on the PR (for example `release:*`), and never change the issue's own labels. Read the issue's labels with `issue_read` (`get_labels`). Read the PR's current labels with `issue_read` (`get`) or `pull_request_read` (`get`), not `get_labels`, which doesn't resolve PR numbers. Then set them with `issue_write` (`update`) on the PR number, which replaces the whole label set, so include the PR's current labels. Without the GitHub MCP tools, add them with `gh api -X POST repos/<owner>/<repo>/issues/<PR>/labels -f 'labels[]=<name>'`, which adds without replacing.
- Never push to a protected branch, force-push, or bypass hooks. Don't overwrite unrelated local changes.
- When branch currency matters, merge `origin/main` as directed by `.claude/rules/branch-currency.md`. Don't update merely because `main` moved.
- PR titles use Conventional Commits (`<type>: <description>`). The title check enforces this.
- PRs that change application behaviour or add real scope need a linked issue (`Closes #N`). Mechanical docs, config, or CI-only tweaks and Renovate PRs are exempt.
- Never merge a PR. The repository owner is the final gatekeeper.

## Review gate

- A PR is substantive if it changes, or could affect, any of these: application code, Docker/Compose behaviour, tests, CI/CD, build or release logic, workflows or automation, security/dependency config, or agent-governance files (`CLAUDE.md`, `.claude/` instructions, skills, agents, hooks, and their configuration). Docs, comments, formatting, or metadata only is not substantive, except for agent-governance files, which are substantive even when the diff is only documentation or configuration. If in doubt, treat it as substantive.
- Never request a CodeRabbit full review or follow-up review (`@coderabbitai full review` or `@coderabbitai review`) unless the user tells you to. When the user does, run the `coderabbit-review` skill. For a substantive PR targeting `main`, say that no CodeRabbit review has been run and let the user decide. It is an independent gate, not a step in a sequence with the agents.
- A PR is only ready for the owner when CI is green on the current head, including tests, MegaLinter, `codecov/project`, and `codecov/patch`, and SonarCloud reports no new issues (read the SonarCloud check summary, or the `/dashboard?id=TommyE123_docker-autoheal&pullRequest=<N>` page it links). Fix issues the PR introduced. Code coverage and mutation score must not drop unless the user agrees, even though the mutation workflow calls itself informational. When Mutation Testing runs on the PR, compare its score with the baseline in `.github/badges/mutation.json`. A drop is blocking: strengthen the tests rather than excuse it. Mutation testing only runs for Python and tooling changes; if it didn't run, say so. A check that is still pending, or skipped without a verified reason, is not green. Don't change workflows, thresholds, or Sonar settings to get these passing.
- When a CodeRabbit review completes with requested changes, either make each change or disagree with it, and reply in the finding's thread saying what you did. Fix nits where you agree the code has the defect, in the lines the PR changed, rather than leaving them. Don't request another review.
- For a substantive PR, after local validation and before the first push, run `git fetch origin main`, then run the `surgical-reviewer` agent on the local diff against `origin/main`, without asking. If the fetch fails, stop and report that the review baseline couldn't be refreshed; don't claim the review used the latest `main`. Fix findings you agree with, and give your reasons for those you don't. Report that it ran, which commit it covered, and what it found. If you skipped it, say so and why. Before any later push, rerun it on the unpushed commits only when they change behaviour, add real scope, or touch an area it already flagged; skip it for small fixes. It does not replace CodeRabbit.
- `REVIEW.md` defines the evidence standard for local reviews. GitHub automatic CodeRabbit reviews stay disabled; chat replies are enabled.

## Governance

- Treat changes to `CLAUDE.md`, `.claude/`, and other agent-governance files as their own scope, not incidental application cleanup.
- Don't weaken governance to make a task easier.
- Keep `.claude/settings.json` consistent with this file.

<!-- settings.json guardrails are pattern-based and partial; branch protection on main is the authoritative control. -->

## Session titles

Set the session title with the `set_session_title` tool (claude-code-remote MCP server, called with `session_id` omitted or set to the current session). If the tool isn't available, propose the title in chat instead. Use this format:

- `I: #N - <issue title>`, when working from an issue
- `I: #N PR: #N - <issue title>`, once a PR exists for that issue
- `PR: #N - <PR title>`, when there is no linked issue

Set the title as soon as the issue or PR number is known. Update it right after opening a PR, so the PR number is added the same turn the PR is created, and again whenever the issue or PR title changes. Never invent an issue or PR number. If the number is unknown, ask instead.

## Agents and skills

The agents (`analyze`, `implement`, `pr-monitor`, `surgical-reviewer`, `test-validator`) and skills are optional tools chosen per task, not a mandatory sequence, except the pre-push `surgical-reviewer` run required under Review gate.
