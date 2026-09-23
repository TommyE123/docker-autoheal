# Repository conventions for Claude Code agents

## Before making changes

- Inspect the existing implementation, config and tests before proposing a change; prefer an existing repository pattern over inventing a new one.
- For GitHub Actions, APIs, schemas or config formats, check current official docs or established examples rather than guessing syntax.
- Check existing issues, PRs and workflows before creating or changing them.
- If the request is ambiguous or an important implementation detail is unclear, clarify the relevant point with the user before making changes. Do not guess when different interpretations could materially change the outcome.
- Once the requirements are clear, make a concise plan, then implement the requested change.
- After implementation, run the tests and validation appropriate to the change (as governed by `.claude/rules/testing.md`), review the final diff, and address any issues introduced by the change before declaring the work complete.

## Keep changes focused

- Do exactly what the issue/request requires. Don't bundle unrelated dependency bumps, refactors, lint fixes, documentation changes, or "while you're here" improvements into the same change.
- If the requested change makes existing documentation inaccurate, incomplete or misleading, update the affected documentation as part of the same change. Do not expand this into unrelated documentation cleanup.
- Do not fix unrelated pre-existing test, lint, CI, or tooling failures unless the task explicitly includes them.
- Don't add new infrastructure when an existing GitHub/CI capability already solves the problem.
- Once the requested change is implemented, validated and reviewed, stop. Do not continue making additional improvements, cleanup or refactoring unless requested.

## Tests for behaviour changes

- Behaviour changes need tests where practical; a bug fix needs a regression test that demonstrates the problem.
- Never weaken, remove or bypass a test (or raise a coverage threshold) just to get CI green — fix the cause instead.

How much validation to run, and when to skip a rerun, is governed by `.claude/rules/testing.md`. It loads automatically as a project rule, along with the other files in `.claude/rules/`.

## Comments

Keep comments minimal: only for non-obvious reasoning the code can't convey on its own, never a restatement of what the next line does.

## Before declaring work complete

- Run the tests and linting relevant to the files you changed, as governed by `.claude/rules/testing.md`, and check the final diff for unrelated changes.
- Never report work, investigation, validation, reproduction, or review that was not actually performed.
- Report only validation that was actually performed.

## GitHub workflow

- Prefer a native GitHub Actions feature over a custom script/API call when one already provides the behaviour.
- Do not fix unrelated pre-existing GitHub Actions failures unless the task explicitly includes them.

## Pull request titles (required)

Every PR title must follow [Conventional Commits](https://www.conventionalcommits.org/) format, enforced by `.github/workflows/semantic-pr-title.yml` (`validate-title` check):

```text
<type>: <description>
```

- `type` must be one of: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- `description` should be concise and describe the change, not the issue.
- Optional scope is allowed (`type(scope): description`) but not required.

Examples already in use in this repo:

- `fix: correct Dockerfile EXPOSE port for the Web UI (8080 -> 3131)`
- `docs: reorganise and rewrite project documentation`
- `chore: migrate to multi-registry publishing (GHCR + Docker Hub)`
- `ci: add welcome workflow for first-time contributors`

Set the title correctly when you open the PR — don't rely on a later retitle. This applies to every PR you open yourself, including dependency/config-only changes (use `chore:` for those unless another type fits better, e.g. `ci:` for GitHub Actions workflow changes).

Renovate-authored PRs are covered separately by `renovate.json`'s `semanticCommits` setting, not by this file — Renovate doesn't read `CLAUDE.md`.

## Pull requests need a linked issue

If a proposed change affects application behaviour or adds real scope (for example: a new feature, bug fix, refactor with user-visible effect, or new CI/tooling capability), check whether a suitable GitHub issue already exists.

If no suitable issue exists, do not assume one should be created automatically. Raise this with the user or maintainer and confirm whether a new issue should be filed before proceeding with substantive implementation work.

When an issue exists, link the PR to it (`Closes #N` in the PR body). This keeps a traceable record of why a change happened, not just what changed.

Exceptions (no issue required):

- Renovate-authored PRs (automated and issue-less by design).
- Purely mechanical docs-only, config-only, or CI-only tweaks with no behaviour change (for example fixing a PR title, a typo, or a lint config value).

When in doubt, ask whether an issue should be created rather than creating one automatically.

## Session titles (Claude Code app)

Claude cannot set a session title itself. When the user asks for one, or when it is useful to suggest one, propose a title in the format below so work is easily identifiable in the Claude Code session list.

When a task is driven by a GitHub issue, use:

`I: #N - <issue title>`

If a pull request is subsequently created or its number is already known:

`I: #N PR: #N - <issue title>`

If a PR is known but there is no linked issue, use:

`PR: #N - <PR title>`

If the task is not tied to a GitHub issue or PR, suggest a short descriptive session title.

## Agent governance

- Repository-specific instructions take precedence over generic assumptions, general AI coding practices, or personal preferences.
- Where two repository instructions appear to conflict, follow the more restrictive one, continue with the task, and report the conflict. Do not stop work solely because instructions appear contradictory.
- Do not modify `CLAUDE.md`, `.claude/rules/`, `.claude/skills/`, or other agent-governance files as part of ordinary implementation work unless the task explicitly requires a change to agent behaviour.
- Do not weaken, remove, or bypass an existing agent instruction to make a task easier.
- If a task explicitly requires a change to agent behaviour, treat the governance change as the primary scope of that task and do not make unrelated implementation changes alongside it.

## Requesting a CodeRabbit review (required before merge)

Every substantive PR targeting `main` must receive a CodeRabbit review before the repository owner merges it. When a substantive PR reaches the CodeRabbit review stage, you MUST invoke the `coderabbit-review` skill and follow it exactly — do not perform an ad hoc review or rely solely on automatic skill discovery. The skill (`.claude/skills/coderabbit-review/SKILL.md`) owns the complete workflow: when to request the initial full review, assessing and fixing findings, disputed findings, branch currency, CI handling, and targeted follow-ups. The first request must be a full review; every subsequent request must be a targeted follow-up, never another full review.

A substantive PR is one that changes or could affect application code, infrastructure or Docker behaviour, tests, CI/CD, build or release logic, workflows or automation, or security and dependency configuration. PRs containing only documentation, comments, formatting or metadata changes do not normally require a CodeRabbit review. If in doubt, treat the PR as substantive. The skill carries the full version of this definition.

## Requesting a Sourcery review (secondary)

Sourcery is a secondary automated reviewer that reviews eligible PRs automatically ahead of the mandatory CodeRabbit stage; a missing Sourcery review is not a reason to block the PR. When a Sourcery review exists, you MUST invoke the `sourcery-review` skill and follow it exactly — do not perform an ad hoc review, rely solely on automatic skill discovery, or manually trigger an initial Sourcery review. The skill (`.claude/skills/sourcery-review/SKILL.md`) owns the complete workflow: detecting and assessing reviews, valid and disputed findings, branch currency, and CI handling.

Sourcery findings are advisory and do not replace the required CodeRabbit review or authorise a merge. Material changes made after a Sourcery review remain subject to the mandatory CodeRabbit review process.

## MegaLinter failures

When a PR fails MegaLinter checks, fix all findings introduced or worsened by the PR, run appropriate targeted validation, and do not modify `.mega-linter.yml` to suppress or weaken checks.

Leave pre-existing, unrelated findings untouched.

See `.claude/rules/megalinter.md` for detailed guidance and do-not-game rules.

## Committing, pushing and pull requests

**The default is that committing, pushing and opening a PR are authorised.** Assume this at the start of every session. Claude may create a branch, commit, push that branch, open a PR, and keep pushing to it as many times as the work requires — the initial change, review fixes, CI-triggered follow-ups and branch updates are all part of the same task. Do not ask for permission each time, and do not ask for permission the first time.

**The default is off only when the user turns it off.** If at any point in a session the user says not to commit, not to push, not to open a PR, or asks for a review, an investigation, or a local change only, then that applies for the remainder of the session unless the user lifts it. In that case, report the result and stop instead of committing or pushing.

Two limits are permanent and are never affected by the default:

- Never push directly to `main` or any other protected branch. Work on a branch and open a PR.
- Never merge (see "Merging" below).

Do not leave completed, validated work uncommitted merely because a generic hook or reminder reports uncommitted changes. A hook or reminder is not the user turning the default off.

`.claude/settings.json` backs this policy at the permission layer: it pre-approves ordinary `git add`/`commit`/`push` and `gh pr create`, denies `gh pr merge`, force pushes, `--no-verify` and the common forms of pushing to `main`, and prompts before `git reset --hard`. That coverage is pattern-based and therefore partial — it cannot match every spelling of a command, and the repository's "Protect Main" ruleset, not these rules, is the primary protection for `main`. Instructions in this file guide what Claude attempts; the settings file decides what Claude Code permits. Keep the two consistent when changing either.

## Merging

Do not merge PRs you open or work on. The repository owner is the final gatekeeper for merging — get the PR green and mergeable, then stop and let the repository owner review.

Renovate dependency updates are also subject to manual review and merge; Renovate must not automatically merge dependency updates.

## Avoid duplicate issues

Before filing or requesting a new issue, search existing open and closed issues for one that already covers the same problem or overlaps significantly with it.

If you find a close match, extend or comment on the existing issue instead of creating a near-duplicate.

## Issue labels are not yours to set

GitHub issue classification (`kind/*` and `area/*`) is owned by the automated Gemini triage workflow (`.github/workflows/issue-triage.md`), and workflow state (`status/*`) is owned by that same workflow.

Do not add, remove, modify, assign, infer, correct, or request GitHub issue labels yourself, including when creating an issue, editing an issue, triaging an issue, fixing an issue, or otherwise interacting with issue labels.

You may read and report existing issue labels when relevant, but label ownership remains with the automated workflows.

You may still create issues when the repository workflow requires one (see "Pull requests need a linked issue" above) — just leave label selection to the triage workflow.

This rule is specific to issue labels. It does not change or restrict how PR labels are handled, including the PR labels owned by the release process — those continue to work as before.

The ownership model:

```text
GitHub issue classification → Gemini
GitHub issue workflow state  → GitHub Actions
PR release labels            → existing release process
```
