# Repository conventions for Claude Code agents

## Before making changes

- Inspect the existing implementation, config and tests before proposing a change; prefer an existing repository pattern over inventing a new one.
- For GitHub Actions, APIs, schemas or config formats, check current official docs or established examples rather than guessing syntax.

## Keep changes focused

- Do exactly what the issue/request requires. Don't bundle unrelated dependency bumps, refactors, lint fixes, or "while you're here" improvements into the same change.
- Don't add new infrastructure when an existing GitHub/CI capability already solves the problem.

## Tests for behaviour changes

- Behaviour changes need tests where practical; a bug fix needs a regression test that demonstrates the problem.
- Never weaken, remove or bypass a test (or raise a coverage threshold) just to get CI green — fix the cause instead.
- See `.claude/rules/testing.md` for how much validation to run and when to skip it.

## Comments

Keep comments minimal: only for non-obvious reasoning the code can't convey on its own, never a restatement of what the next line does.

## Before declaring work complete

- Run the relevant tests and linting for the files you changed, and check the final diff for unrelated changes.
- Report only what you actually ran — don't claim a check passed if it wasn't run.

## GitHub workflow

- Check existing issues, PRs and workflows before creating or changing them.
- Prefer a native GitHub Actions feature over a custom script/API call when one already provides the behaviour.

## Pull request titles (required)

Every PR title must follow [Conventional Commits](https://www.conventionalcommits.org/) format, enforced by `.github/workflows/semantic-pr-title.yml` (`validate-title` check):

```
<type>: <description>
```

- `type` must be one of: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- `description` is lowercase, concise, and describes the change (not the issue).
- Optional scope is allowed (`type(scope): description`) but not required.

Examples already in use in this repo:
- `fix: correct Dockerfile EXPOSE port for the Web UI (8080 -> 3131)`
- `docs: reorganise and rewrite project documentation`
- `chore: migrate to multi-registry publishing (GHCR + Docker Hub)`
- `ci: add welcome workflow for first-time contributors`

Set the title correctly when you open the PR — don't rely on a later retitle. This applies to every PR you open yourself, including dependency/config-only changes (use `chore:` for those unless another type fits better, e.g. `ci:` for GitHub Actions workflow changes).

Renovate-authored PRs are covered separately by `renovate.json`'s `semanticCommits` setting, not by this file — Renovate doesn't read `CLAUDE.md`.

## Pull requests need a linked issue

If a PR changes application behavior or adds real scope (new feature, bug fix, refactor with user-visible effect, new CI/tooling capability), file a GitHub issue for it first — or confirm one already exists — and link the PR to it (`Closes #N` in the PR body). This keeps a traceable record of *why* a change happened, not just what changed.

Exceptions (no issue required):
- Renovate-authored PRs (automated, never have an issue by design).
- Purely mechanical docs-only, config-only, or CI-only tweaks with no behavior change (e.g. fixing a PR title, a typo, a lint config value).

When in doubt, file the issue — it's cheap, and it's what nearly every substantive change in this repo already does.

## Session titles (Claude Code app)

When your task is driven by a specific GitHub issue, title your Claude Code session `Issue #N: <issue title>` (matching the issue's own title) so it's identifiable in the session list at a glance. If the task isn't tied to a single filed issue, a short descriptive title is fine.

## Requesting a CodeRabbit review (required before merge)

Every substantive PR gets a CodeRabbit review before Tom merges it. When a substantive PR reaches the CodeRabbit review stage, you MUST explicitly invoke the `coderabbit-review` skill (`.claude/skills/coderabbit-review/SKILL.md`) and follow its instructions exactly. Do not perform an ad-hoc CodeRabbit review instead, and do not rely solely on semantic skill auto-discovery — this procedure carries repository-specific institutional knowledge that ad-hoc review would lose.

## Requesting a Sourcery review (optional)

Sourcery is an optional second opinion, independent of CodeRabbit, and a scarce resource. If you use it, follow the `sourcery-review` skill (`.claude/skills/sourcery-review/SKILL.md`).

## Merging

Do not merge PRs you open or work on. Tom (@TommyE123) is the final gatekeeper for merging — get the PR green and mergeable, then stop and let him review.

Renovate dependency updates are also subject to manual review and merge; Renovate must not automatically merge dependency updates.

## Avoid duplicate issues

Before filing a new issue, search existing open and closed issues for one that already covers the same problem or overlaps significantly with it. If you find a close match, extend or comment on it instead of creating a near-duplicate — this has already happened once (issue #26 and a planned issue #6 both touching Uptime Kuma test coverage).

## Superpowers

Superpowers is not a dependency of this repository — do not add it to `.claude/settings.json`, require it, reference its skill names as repository dependencies, or build a local copy or fallback for it. If Superpowers happens to be available in a given environment, it may be used for suitable heavyweight work (complex feature development, design/brainstorming, substantial planning, TDD-heavy work, systematic debugging), but this repository's own guidance must remain sufficient without it. Don't invoke a heavyweight workflow for small maintenance/configuration/documentation changes merely because it's available.
