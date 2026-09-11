# Repository conventions for Claude Code agents

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

## Merging

Do not merge PRs you open or work on. Tom (@TommyE123) is the final gatekeeper for merging — get the PR green and mergeable, then stop and let him review. This doesn't apply to Renovate's own routine minor/patch/digest updates, which are configured to automerge in `renovate.json` once CI passes; that's an explicit, separate policy decision, not something an agent should replicate for its own PRs.

## Avoid duplicate issues

Before filing a new issue, search existing open and closed issues for one that already covers the same problem or overlaps significantly with it. If you find a close match, extend or comment on it instead of creating a near-duplicate — this has already happened once (issue #26 and a planned issue #6 both touching Uptime Kuma test coverage).
