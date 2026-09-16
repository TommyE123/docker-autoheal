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

```text
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

## Release classification label (required)

Every PR into `main` must carry exactly one release label. This is checked by
`.github/workflows/release-validation.yml` (`validate-release` check), which fails a PR that
carries no label, more than one, or an invalid one. That check is not yet a required status
check in the branch ruleset (a manual, external configuration step — see
`docs/RELEASING.md`), so label your PR correctly regardless of whether the check is
currently merge-blocking:

- `release:none` — docs, CI, tests, refactors with no behaviour change, normal Renovate updates, formatting/linting.
- `release:patch` — bug fix, security fix needing a new image, performance improvement.
- `release:minor` — new backwards-compatible feature, new configuration option, intentional backwards-compatible behaviour change.
- `release:major` — breaking behaviour or configuration change.

Choose the release *type* only — never a version number. The automation calculates the
version from the latest release tag, publishes patch/minor/major releases on merge, and
sweeps accumulated `release:none` changes into one patch release each Friday. See
`docs/RELEASING.md`.

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

When CodeRabbit reports actionable findings that are valid and related to the PR, fix them (ensuring the PR branch is current with main before the final push), run targeted validation, commit and push the changes, document what was fixed in a PR comment, wait for CI to return to green, and request another full review. Repeat as necessary until no further actionable findings remain. See `.claude/skills/coderabbit-review/SKILL.md` for the detailed workflow.

A CodeRabbit full review covers the state of the PR at the time that review is requested. If material changes are made to the PR after the most recent CodeRabbit full review, a fresh `@coderabbitai full review` must be requested once CI/checks are green, regardless of why those changes were made. Material changes include those made to address Sourcery findings, MegaLinter findings, another reviewer's findings, the original task, or other authorised PR work. However, the existing CodeRabbit fix/review cycle already satisfies this requirement — do not request duplicate reviews. Editorial or mechanical changes that cannot affect behaviour or configuration do not require a fresh review unless explicitly requested. For detailed guidance, see `.claude/skills/coderabbit-review/SKILL.md`.

## Requesting a Sourcery review (optional)

Sourcery is an optional second opinion, independent of CodeRabbit, and a scarce resource. If you use it, follow the `sourcery-review` skill (`.claude/skills/sourcery-review/SKILL.md`).

When you fix an actionable Sourcery finding, run targeted validation, ensure the PR branch is current with main before the final push, commit and push the changes, and document what was fixed in a PR comment. Do not automatically request another Sourcery review — re-review is only performed when Tom explicitly asks for it. See `.claude/skills/sourcery-review/SKILL.md` for the detailed workflow.

## MegaLinter failures

When a PR fails MegaLinter checks, fix all findings introduced or worsened by the PR, run appropriate targeted validation, ensure the PR branch is current with main before the final push, commit and push the changes, and do not modify `.mega-linter.yml` to suppress or weaken checks. Leave pre-existing, unrelated findings untouched. See `.claude/rules/megalinter.md` for detailed guidance and do-not-game rules.

## Committing and pushing authorized fixes

When explicitly authorized to fix findings or complete work, commit and push the validated, completed changes. Do not leave authorized, completed fixes uncommitted merely because a generic hook or reminder reports uncommitted changes. The user's explicit task instruction determines whether committing and pushing is authorized; generic reminders must not override that authorization.

Committing and pushing does not authorize Claude to merge the PR — Tom remains the final gatekeeper.

## Merging

Do not merge PRs you open or work on. Tom (@TommyE123) is the final gatekeeper for merging — get the PR green and mergeable, then stop and let him review.

Renovate dependency updates are also subject to manual review and merge; Renovate must not automatically merge dependency updates.

## Avoid duplicate issues

Before filing a new issue, search existing open and closed issues for one that already covers the same problem or overlaps significantly with it. If you find a close match, extend or comment on it instead of creating a near-duplicate — this has already happened once (issue #26 and a planned issue #6 both touching Uptime Kuma test coverage).
