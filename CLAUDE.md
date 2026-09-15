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

## Release classification label (required)

Every PR into `main` must carry exactly one release label, enforced by
`.github/workflows/release-validation.yml` (`validate-release` check):

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

Automatic reviews are off in `.coderabbit.yaml` (`reviews.auto_review.enabled: false`), so CodeRabbit reviews a PR only when it is explicitly asked. Every PR gets a CodeRabbit review before Tom merges it.

**Ask only once the PR is green.** Wait until every check on the PR head has passed (`unit-tests`, `MegaLinter`, `Build Docker image`, `validate-title`, `codecov/patch`, `codecov/project`, plus any other check the PR triggers) and the branch has no merge conflict. Asking while CI is red spends the review on findings CI has already reported.

**Always use `@coderabbitai full review`, never `@coderabbitai review`.** `review` is incremental: with automatic reviews disabled it can reply "CodeRabbit is an incremental review system and does not re-review already reviewed commits" and do nothing, which has already happened on PR #105. `full review` reviews the whole PR from scratch.

Free-form instructions in the same comment as the command are honoured (`chat.auto_reply: true`), so put them directly under the command. Post the template below as a single PR comment, filling in **Context**, **In scope** and **Out of scope** and leaving the rest verbatim — the fixed **How to report** and **Verdict** sections are what make reviews comparable across PRs, so don't reword them per PR:

```markdown
@coderabbitai full review

**Context**
- PR #<N>: <title>
- Issue: Closes #<M>   <!-- or: none — <which linked-issue exception applies> -->
- Change type: <bug fix | feature | test-only | refactor | docs | ci/config | dependency>
- All checks green on <short-sha>.
- <1-3 lines: what changed and why. For a re-review, say what changed since the last round.>

**In scope**
- <the specific behaviour, file or path to verify — one bullet each>
- <any related PR/issue CodeRabbit must inspect before concluding, and why>

**Out of scope**
- Pre-existing MegaLinter findings (bandit `assert_used` in tests, mypy/pyright optional-access warnings) unless this PR introduced or worsened them.
- Codecov percentages as evidence of correctness.
- Style-only preferences and unrelated cleanup.

**How to report**
Inspect the surrounding repository, not just the changed lines. Do not treat the PR
description or a passing test suite as proof of correctness. Do not manufacture
findings — if the PR is correct, say so plainly.

Classify every finding as exactly one of:
- 🔴 **BLOCKER** — must be fixed before merge
- 🟠 **IMPORTANT** — significant correctness or regression risk
- 🟡 **MINOR** — worthwhile but not merge-blocking
- 🟢 **GOOD** — something the PR gets right, worth calling out

For each 🔴/🟠/🟡 finding give: exact `file:line`, what is wrong, why it matters, the
smallest correct fix, whether this PR introduced it or it is pre-existing, and whether
a regression test is required.

**Verdict**
End with exactly one of:
- ✅ **APPROVE** — safe to merge
- ⚠️ **APPROVE WITH MINOR CHANGES** — no blocking issue
- ❌ **CHANGES REQUIRED** — blocking issue found

Review only — do not push commits to this PR.
```

Keep **In scope** to the handful of things that actually need judgement; it is the only part that should grow, and a scope list longer than about ten bullets means the PR is too broad. After pushing review fixes, wait for green again and post a fresh `full review` comment whose Context says what changed since the last round.

## Merging

Do not merge PRs you open or work on. Tom (@TommyE123) is the final gatekeeper for merging — get the PR green and mergeable, then stop and let him review.

Renovate dependency updates are also subject to manual review and merge; Renovate must not automatically merge dependency updates.

## Avoid duplicate issues

Before filing a new issue, search existing open and closed issues for one that already covers the same problem or overlaps significantly with it. If you find a close match, extend or comment on it instead of creating a near-duplicate — this has already happened once (issue #26 and a planned issue #6 both touching Uptime Kuma test coverage).
