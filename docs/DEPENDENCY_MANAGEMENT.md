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
  Renovate's extraction correctly lists `frontend/package-lock.json` as the `lockFiles` entry for
  `frontend/package.json` (checked with `--dry-run=extract`), which is what makes it update the
  lockfile in step whenever it bumps a `package.json` entry.
- **GitHub Actions**: pinned to the full immutable commit SHA of the exact release each action was
  already using, with a `# vX.Y.Z` comment for the human-readable version
  (`actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0`), matching the convention
  used by the reference repository named in issue #7 (`GhostWriters/docker-packt-cli`). Nothing was
  upgraded - every SHA is the commit the action's existing version tag already pointed to.
  `renovate.json` extends the `helpers:pinGitHubActionDigests` preset so Renovate both proactively
  pins any future unpinned action the same way and keeps the SHA and version comment synchronised
  on every update - this is native behaviour of Renovate's `github-actions` manager (verified with
  a local `--dry-run=extract`: Renovate correctly reads each pinned `currentValue`/`currentDigest`
  pair back out of the workflow files).
- **Docker images**:
  - `Dockerfile` and `Dockerfile.simple`'s base images (`python:3.11-slim`, `node:18-alpine`) are
    pinned to their current tag **and** the SHA256 digest that tag currently resolves to, in the
    form `image:tag@sha256:digest`. The tag stays as the human-readable version indicator; the
    digest makes the build reproducible and tamper-evident. Neither image's version was changed.
    Tag and digest staying synchronised on every future update (never a stale digest against a
    newer tag) is native behaviour of the `dockerfile` manager - its replace template always
    writes `{{depName}}:{{newValue}}@{{newDigest}}` as one atomic edit (checked directly in the
    installed `renovate` package's source, not assumed); the `docker-compose` manager reuses that
    exact same extraction/replace code for Compose image references, so the two behave identically.
  - `docker-compose.yml`'s `autoheal` service intentionally keeps `tommye123/docker-autoheal:latest`
    unpinned (see the comment next to it) - it's this project's own published image, not a
    dependency, and it's meant to give users who copy the compose file our newest release, not a
    frozen one.
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
- **Security updates**: GitHub-detected vulnerability alerts (Dependabot alert data) are enabled by
  default under `config:recommended` - confirmed by reading the option's default (`enabled: true`,
  inherited from Renovate's generic default) directly out of the installed `renovate` package, not
  assumed. `renovate.json` doesn't touch `vulnerabilityAlerts` at all, so that default stands. A
  vulnerability-fix PR is still just a patch/minor/major update with a `[SECURITY]` marker; it goes
  through the exact same `matchUpdateTypes` automerge rule as any other update above, deliberately -
  no separate `vulnerabilityAlerts.automerge` config was added, because the generic rule already
  produces exactly the wanted policy: a patch/minor security fix automerges once CI passes, and a
  security fix that needs a major bump still gets a normal, manually-reviewed PR like any other
  major update.

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
- **npm lockfile and Node 18.** `frontend/package-lock.json` was verified end-to-end with the real
  `node:18-alpine`-equivalent version (Node 18.20.8, the final 18.x release, matching what
  `node:18-alpine` resolves to): `npm ci` and `npm run build` both succeed and produce byte-identical
  build output to a Node 22 build. `npm ci` does print `EBADENGINE` warnings (not errors) for nine
  transitive packages that declare `engines.node >= 20` - all of them pulled in by
  `vite-plugin-pwa`'s `workbox-build` (service-worker generation tooling) and one branch of ESLint's
  toolchain. `vite.config.js` doesn't actually register `vite-plugin-pwa` as a Vite plugin (it's a
  devDependency with nothing wiring it up - pre-existing, not introduced by this change), so that
  code path never runs during `npm run build`, which is why the build is clean under Node 18 despite
  the warnings. Worth knowing if `vite-plugin-pwa` is ever wired up in the future: at that point
  `workbox-build`'s Node 20 requirement would become a real constraint on the Dockerfile's Node 18
  build stage, and either the base image or the PWA tooling would need to move.
