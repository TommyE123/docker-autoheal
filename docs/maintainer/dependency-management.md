# Dependency management

Dependencies are kept up to date by [Renovate](https://docs.renovatebot.com/), configured in
[`renovate.json`](../../renovate.json) at the repository root.

This document explains what Renovate manages, how versions are pinned, and how dependency
updates are reviewed and merged.

## What Renovate manages

| Ecosystem                       | Files                                                 | Renovate manager                    |
|---------------------------------|-------------------------------------------------------|-------------------------------------|
| Python runtime dependencies     | `requirements.txt`                                    | `pip_requirements`                  |
| Python dev/test dependencies    | `requirements-dev.txt`                                | `pip_requirements`                  |
| npm dependencies + lockfile     | `frontend/package.json`, `frontend/package-lock.json` | `npm`                               |
| Docker base images              | `Dockerfile`, `Dockerfile.simple`                     | `dockerfile`                        |
| Docker Compose images           | `docker-compose*.yml`                                 | `docker-compose`                    |
| GitHub Actions                  | `.github/workflows/*.yml`                             | `github-actions`                    |
| Dockerfile apt package versions | `Dockerfile`, `Dockerfile.simple`                     | `customManagers:dockerfileVersions` |

The standard `config:recommended` preset provides the managers for the main dependency
ecosystems above. A custom Renovate manager is also enabled for pinned versions of apt
packages in the Dockerfiles.

Currently, `curl` is pinned in the Dockerfiles so that its version can be tracked and updated
by Renovate. This allows the Dockerfile dependency to receive a normal Renovate PR rather than
floating to whatever version happens to be available from the Debian package repository at
build time.

## Version pinning policy

* **Python**: exact versions (`==`) are used throughout both `requirements.txt` and
  `requirements-dev.txt`.

  The packages that previously used `~=` (`pydantic`, `aiohttp`) were switched
  to `==` at their already-installed versions rather than being upgraded. Every subsequent
  version change therefore becomes a visible, reviewable Renovate PR instead of silently
  floating to a newer patch release at build time.

* **npm**: `frontend/package.json` keeps its existing `^`-range versions, and
  `frontend/package-lock.json` records the exact resolved versions installed.

  The frontend Docker build uses `npm ci` rather than `npm install`, so builds install the
  versions recorded in the lockfile.

  Renovate manages both the `package.json` dependency ranges and the associated lockfile,
  allowing dependency updates to be reviewed as normal pull requests.

* **GitHub Actions**: actions are pinned to the full immutable commit SHA of the release being
  used, with a `# vX.Y.Z` comment retaining the human-readable version.

  For example:

  `actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0`

  `renovate.json` extends `helpers:pinGitHubActionDigests`, so Renovate can maintain these
  immutable SHA pins and keep their version comments synchronised.

* **Docker images**:

  * `Dockerfile` and `Dockerfile.simple` base images are pinned to both their human-readable
    tag and the SHA256 digest that tag resolves to, using the form
    `image:tag@sha256:digest`.

    The tag identifies the intended version while the digest makes the image reference
    immutable. Renovate keeps the tag and digest synchronised when creating updates.

  * `docker-compose.yml` intentionally keeps
    `tommye123/docker-autoheal:latest` unpinned. This is the project's own published image,
    not a third-party dependency, and the example compose configuration is intended to deploy
    the newest published release when copied by users.

    Renovate is explicitly configured not to manage this image.

  * `docker-compose.test.yml` and `docker-compose.example.yml` are manual/demo compose files.
    Their existing image references are not hand-maintained by this project, but Renovate can
    still detect them. The Docker `pinDigests` rule means Renovate may create normal digest-pin
    PRs for applicable Docker image references.

* **Dockerfile apt packages**: versions are explicitly pinned where required by the Dockerfile
  linting policy. Renovate's `customManagers:dockerfileVersions` manager tracks these pins and
  can create update PRs when newer package versions are available.

## Dependency update policy

Renovate is responsible for **detecting and proposing** dependency updates. It may:

* detect new dependency versions
* create dependency-update pull requests
* update existing dependency-update pull requests
* rebase dependency branches when they fall behind `main`
* maintain Docker image digest pins
* maintain GitHub Actions digest pins
* maintain other configured version and digest pins

Renovate does **not** automatically merge dependency updates.

All dependency-update pull requests require manual review and merge.

This deliberately conservative policy currently applies to:

* patch updates
* minor updates
* major updates
* Docker digest updates
* GitHub Actions digest updates
* `pin` updates
* `pinDigest` updates
* security updates

A future change may introduce narrowly scoped automerge rules for demonstrably low-risk
updates once test coverage and CI confidence justify doing so. Such a change should be made
explicitly rather than relying on a blanket semver-based automerge rule.

### Rebasing

`rebaseWhen: "behind-base-branch"` is enabled.

This allows Renovate to keep dependency-update branches current with `main` when the base branch
moves. Keeping branches current means dependency PRs can be tested against the latest project
state rather than remaining based on an increasingly stale commit.

### Semantic commits

Renovate uses semantic commit conventions with the `chore` commit type for dependency updates.

This keeps automated dependency-update commits consistent with the repository's commit naming
conventions.

## Digest pinning

Digest pinning remains enabled even though automerge is disabled.

Two important Renovate behaviours are retained:

* GitHub Actions are pinned to immutable commit SHAs through
  `helpers:pinGitHubActionDigests`.
* Docker image references can be pinned to immutable SHA256 digests through the
  `pinDigests` rule.

Digest updates are still normal pull requests and require manual review.

Pinning and automerge are intentionally separate concerns: Renovate can maintain secure,
immutable references without being allowed to merge the resulting changes automatically.

## Security updates

Security updates are also subject to the manual-review policy.

A security fix may result in a patch, minor, or major dependency update, but Renovate does not
automatically merge any of these updates.

Security-related dependency PRs therefore receive the same CI validation and human review as
other dependency updates.

This is intentional: security fixes are important, but automatically merging them can still
introduce compatibility or behavioural changes.

## Why some things are left alone

* **The project's own Docker image** — `tommye123/docker-autoheal:latest` is intentionally
  excluded from Renovate dependency management because it is produced by this repository rather
  than being a third-party dependency.

* **Demo/test Compose files** — `docker-compose.test.yml` and
  `docker-compose.example.yml` are kept as project-controlled examples rather than being
  manually rewritten simply to satisfy dependency pinning. Renovate can still propose digest
  pinning where appropriate.

* **Node 18** — the frontend build currently uses the Node 18 Alpine image. This is retained
  until there is a deliberate decision to change the frontend build/runtime baseline.

* **Pre-1.0 and build tooling dependencies** — these remain manual-review updates. A patch or
  minor version does not automatically mean a dependency is behaviourally risk-free.

## Current policy summary

The intended workflow is:

```text
Renovate detects an update
        |
        v
Renovate opens or updates a PR
        |
        v
GitHub Actions runs
        |
        v
CI passes
        |
        v
Maintainer reviews the changes
        |
        v
Maintainer approves and merges
```

Renovate may maintain the PR and keep it rebased, but the final merge decision remains with a
maintainer.

`platformAutomerge` is disabled in `renovate.json`, so Renovate does not request GitHub's native
auto-merge for dependency-update PRs.

This policy is intentionally conservative while the project's test coverage, integration
testing and CI confidence continue to improve.
