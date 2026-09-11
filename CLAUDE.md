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

## Session titles (Claude Code app)

When your task is driven by a specific GitHub issue, title your Claude Code session `Issue #N: <issue title>` (matching the issue's own title) so it's identifiable in the session list at a glance. If the task isn't tied to a single filed issue, a short descriptive title is fine.
