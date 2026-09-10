# Dependency management

Dependencies are kept up to date by [Renovate](https://docs.renovatebot.com/), configured in
[`renovate.json`](../renovate.json) at the repository root. This document explains what Renovate
manages, how versions are pinned, and how automerge is gated on CI.

## What Renovate manages

| Ecosystem | Files | Renovate manager |
| --- | --- | --- |
| Python runtime dependencies | `requirements.txt` | `pip_requirements` |
| Python dev/test dependencies | `requirements-dev.txt` | `pip_requirements` |
| npm dependencies + lockfile | `frontend/package.json`, `frontend/package-lock.json` | `npm` |
| Docker base images | `Dockerfile`, `Dockerfile.simple` | `dockerfile` |
| Docker Compose images | `docker-compose*.yml` | `docker-compose` |
| GitHub Actions | `.github/workflows/*.yml` | `github-actions` |

These are all managers enabled by Renovate's `config:recommended` preset out of the box - no
custom regex managers were added. One thing `config:recommended` does *not* cover automatically is
apt packages installed via `apt-get install` in the Dockerfiles (just `curl`, currently); Renovate
has no built-in manager for OS package versions, and neither Dockerfile pins one, so there's
nothing there for it to track.

## Version pinning policy

- **Python**: exact versions (`==`) throughout both `requirements.txt` and `requirements-dev.txt`.
  The three packages that previously used `~=` (`pydantic`, `aiohttp`, `pillow`) were switched to
  `==` at their already-installed version - not upgraded - so every version bump becomes a visible,
  reviewable Renovate PR instead of silently floating to a new patch release at build time.
- **npm**: `frontend/package.json` keeps its existing `^`-range versions (unchanged), and
  `frontend/package-lock.json` (newly generated from those same ranges, not committed before this
  change) pins the exact resolved versions actually installed. `Dockerfile`'s frontend build stage
  uses `npm ci` (not `npm install`) so a build always installs exactly what's in the lockfile.
- **GitHub Actions**: pinned to an explicit release tag (e.g. `actions/checkout@v4.4.0`) rather than
  a floating major tag (`@v4`). This is the exact version each action already resolved to; nothing
  was upgraded.
- **Docker images**:
  - `Dockerfile` and `Dockerfile.simple`'s base images (`python:3.11-slim`, `node:18-alpine`) are
    pinned to their current tag **and** the SHA256 digest that tag currently resolves to, in the
    form `image:tag@sha256:digest`. The tag stays as the human-readable version indicator; the
    digest makes the build reproducible and tamper-evident. Neither image's version was changed.
  - `docker-compose.yml`'s `autoheal` service intentionally keeps `swaya1125/docker-autoheal:latest`
    unpinned and un-managed by Renovate (see the comment next to it, and the `enabled: false`
    package rule in `renovate.json`) - it's this project's own published image, not a dependency,
    and it's meant to give users who copy the compose file our newest release, not a frozen one.
  - `docker-compose.test.yml` and `docker-compose.example.yml` are manual/demo compose files (not
    used by CI or by the published image) and were left exactly as they were. Renovate's
    `docker-compose` manager will still pick up every image reference in them, and
    `renovate.json`'s `pinDigests: true` rule means Renovate will open normal "pin digest" PRs to
    add digests to them going forward, the same as for any other Docker reference it finds.

## Automerge

```
Renovate detects an update
        |
        v
Renovate opens a normal PR
        |
        v
GitHub Actions runs (the "Unit Tests" workflow, and any other required checks)
        |
        v
   checks pass? --- no ---> PR stays open, untouched, for a maintainer to look at
        |
       yes
        |
        v
Renovate automerges the PR
```

- `platformAutomerge: true` makes Renovate use GitHub's native "auto-merge" on the PR, rather than
  merging it itself. GitHub only completes that merge once every required status check on the PR
  is green - so automerge structurally cannot complete while CI is failing or still running,
  and `renovate.json` never sets `requiredStatusChecks` to bypass that.
- Automerge is enabled only for `minor`, `patch`, `digest`, `pin`, and `pinDigest` updates. `major`
  updates always get a normal PR that a maintainer merges by hand, so a major version bump never
  looks like (or merges like) a routine patch update.
- The existing `Unit Tests` workflow (`.github/workflows/tests.yml`, from #1/#2) is unchanged and
  remains the CI gate every Renovate PR runs against.

### GitHub-side prerequisites (outside this PR)

Renovate's config can express this policy, but two repository settings actually enforce it, and
both need to be set up by someone with admin access to the repo - the token available to this PR
couldn't read or change either of them:

1. **Branch protection on `main` must require the `Unit Tests` workflow's jobs as required status
   checks.** Without this, GitHub's native auto-merge has nothing to wait for and could merge a PR
   as soon as it's otherwise mergeable, regardless of whether CI has run. *(Settings → Branches →
   branch protection rule for `main` → "Require status checks to pass before merging" → select the
   `unit-tests (3.11)` and `unit-tests (3.12)` jobs.)*
2. **"Allow auto-merge" must be enabled for the repository.** This is currently **off** (confirmed
   via the API while implementing this). Renovate's `platformAutomerge` PRs will simply never merge
   until this is turned on - which fails safe, but means automerge won't do anything until it's
   enabled. *(Settings → General → Pull Requests → "Allow auto-merge".)*
3. **The Renovate GitHub App** (or an equivalent self-hosted runner) needs to be installed on this
   repository for any of this to run at all - `renovate.json` is inert on its own until something
   executes Renovate against the repo.

## Why some things were left alone

- **`docker-compose.test.yml` / `docker-compose.example.yml`** - manual/demo files, not part of the
  build or CI; their existing image tags were left as-is rather than hand-edited, for the reasons
  above.
- **apt packages in the Dockerfiles** - not managed by Renovate without a custom regex manager,
  which felt like unnecessary complexity for a single `curl` install; flagged here rather than
  worked around.
- **GitHub Actions are pinned to exact release tags, not commit SHAs.** Full SHA-pinning (with a
  trailing `# vX.Y.Z` comment) is a stricter, increasingly common convention - the reference
  repository named in issue #7 (`GhostWriters/docker-packt-cli`) does this for every action - but
  the issue's own wording asks specifically for "explicit major/minor/patch references" for
  Actions, distinct from the digest requirement it states for Docker images. Exact-tag pinning
  satisfies that directly with a much smaller diff and is what Renovate's standard
  `config:recommended` preset manages without extra configuration. If repo-wide SHA-pinning for
  Actions is wanted instead, it's a small follow-up: add the `helpers:pinGitHubActionDigests`
  preset to `renovate.json` and let Renovate open the pinning PRs.
