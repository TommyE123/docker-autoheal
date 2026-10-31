# Dependency management

Dependencies are kept up to date by [Renovate](https://docs.renovatebot.com/), configured in
[`renovate.json`](../../renovate.json) at the repository root.

This document explains what Renovate manages, how versions are pinned, and how dependency
updates are reviewed and merged.

## What Renovate manages

| Ecosystem                       | Files                                                           | Renovate manager                    |
|---------------------------------|-----------------------------------------------------------------|-------------------------------------|
| Python runtime dependencies     | `requirements.txt`                                              | `pip_requirements`                  |
| Python test dependencies        | `requirements-dev.txt`                                          | `pip_requirements`                  |
| npm dependencies + lockfile     | `frontend/package.json`, `frontend/package-lock.json`           | `npm`                               |
| Dev Container npm lint tools    | `.devcontainer/package.json`, `.devcontainer/package-lock.json` | `npm`                               |
| Dev Container CLI tools         | `mise.toml`, `mise.lock`                                        | `mise`                              |
| Dev Container base image        | `.devcontainer/Dockerfile`                                      | `dockerfile`                        |
| Docker base images              | `Dockerfile`                                                    | `dockerfile`                        |
| Docker Compose images           | `docker-compose.yml`                                            | `docker-compose`                    |
| GitHub Actions                  | `.github/workflows/*.yml`                                       | `github-actions`                    |
| Dockerfile apt package versions | `Dockerfile`                                                    | `customManagers:dockerfileVersions` |

The standard `config:recommended` preset provides the managers for the main dependency
ecosystems above, including `mise` for the developer CLI tools pinned in `mise.toml`
(`actionlint`, `hadolint`, `osv-scanner`, `trivy`, `trufflehog`, `betterleaks`,
`editorconfig-checker`, `ruff`, `shellcheck`, `shfmt`, `semgrep`, `yamllint`, `zizmor`
and `djlint`). A custom Renovate manager is also enabled for
pinned versions of apt packages in the Dockerfiles.

Two Dev Container pins need manual attention:

* **`mise.lock` and `.mise/locks/`.** A Renovate update to `mise.toml` must come with a
  regenerated lock. If the PR changes `mise.toml` alone, `mise install --locked` fails and
  the Dev Container workflow goes red; run
  `mise lock --platform linux-x64,linux-arm64` on the branch and commit the result.
  `.mise/locks/` contains generated sidecars (`pyproject.toml` and `uv.lock`) managed by
  mise, with their digests recorded in `mise.lock`. Renovate ignores that directory
  (`ignorePaths` in `renovate.json`) so its Python/uv managers don't modify generated files
  independently of the corresponding `mise.lock` state.
* **Dev Container features.** Renovate's `devcontainer` manager updates the feature
  versions in `.devcontainer/devcontainer.json` but not the digests pinned in
  `.devcontainer/devcontainer-lock.json`. Refresh those periodically with
  `devcontainer upgrade --workspace-folder .` from the Dev Containers CLI.

Currently, `curl` is pinned in the Dockerfiles so that its version can be tracked and updated
by Renovate. This allows the Dockerfile dependency to receive a normal Renovate PR rather than
floating to whatever version happens to be available from the Debian package repository at
build time.

## Version pinning policy

* **Python**: exact versions (`==`) are used throughout `requirements.txt`
  and `requirements-dev.txt`. Developer CLI tools in `mise.toml` are pinned exactly too.

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

  * The `Dockerfile` base images are pinned to both their human-readable
    tag and the SHA256 digest that tag resolves to, using the form
    `image:tag@sha256:digest`.

    The tag identifies the intended version while the digest makes the image reference
    immutable. Renovate keeps the tag and digest synchronised when creating updates.

  * `docker-compose.yml` intentionally keeps
    `tommye123/docker-autoheal:latest` unpinned. This is the project's own published image,
    not a third-party dependency, and the example compose configuration is intended to deploy
    the newest published release when copied by users.

    Renovate is explicitly configured not to manage this image.

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

For regular dependency updates, Renovate waits at least seven days after a release before
proposing it. `internalChecksFilter: "strict"` makes Renovate skip releases that have not
cleared this window instead of selecting a newer, still-pending release. Security updates
bypass the minimum release age so that vulnerability fixes are not delayed.

Renovate automatically merges only **eligible patch updates**, and only once every required
GitHub status check has passed. An update is eligible when:

* it is a patch update (`matchUpdateTypes: ["patch"]`), including patch updates of `0.x`
  dependencies.

Minor, major, digest, pin and security updates that are not also eligible patch updates
still require manual review and merge. Automerge is disabled globally and re-enabled only by
the narrower rule in `renovate.json`.

All other dependency-update pull requests require manual review and merge.

Manual review and merge applies to:

* minor updates
* major updates
* Docker digest updates
* GitHub Actions digest updates
* `pin` updates
* `pinDigest` updates
* security updates that are not eligible patch updates

Automerge is not blanket semver-based: it is limited to the explicit patch rule described
above. Broadening it to other update types should be a separate, deliberate change.

### Frontend toolchain grouping

Vite, Vitest and their plugins have interdependent peer dependency ranges, so updating one
package alone can fail lockfile generation. `renovate.json` extends `group:vite` and
`group:vitestMonorepo` for the recommended Vite and Vitest groupings. A package rule also
groups **major** updates to `vite`, `@vitejs/plugin-react`, `vitest` and
`@vitest/coverage-v8` in `frontend/package.json` into a single pull request. Patch and minor
updates are not part of that group, and unrelated frontend dependencies such as React or
ESLint are not grouped with it. Manual review and merge, the seven-day minimum release age and
disabled automerge apply to the group as usual.

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

Digest pinning remains enabled and is independent of automerge, which applies only to eligible
patch updates.

Two important Renovate behaviours are retained:

* GitHub Actions are pinned to immutable commit SHAs through
  `helpers:pinGitHubActionDigests`.
* Docker image references can be pinned to immutable SHA256 digests through the
  `pinDigests` rule.

Digest updates are still normal pull requests and require manual review.

Pinning and automerge are intentionally separate concerns: Renovate can maintain secure,
immutable references without being allowed to merge the resulting changes automatically.

## Security updates

Security updates are subject to the same policy as other updates.

A security fix that is an eligible patch update may be automerged once required checks pass.
A minor or major security fix is not automerged and requires manual review.

Security-related dependency PRs therefore receive the same CI validation as other dependency
updates, and human review unless they are eligible patch updates.

Manual review of non-patch security fixes is intentional: security fixes are important, but
automatically merging them can still introduce compatibility or behavioural changes.

## Why some things are left alone

* **The project's own Docker image** — `tommye123/docker-autoheal:latest` is intentionally
  excluded from Renovate dependency management because it is produced by this repository rather
  than being a third-party dependency.

* **Node 26** — the frontend build currently uses the Node 26 Alpine image. This is retained
  until there is a deliberate decision to change the frontend build/runtime baseline.

* **Pre-1.0 and build tooling dependencies** — `0.x` patch updates are automerged like other
  eligible patch updates. Build tooling is automerged
  only when its update is a patch. A patch or minor version does not automatically mean a
  dependency is behaviourally risk-free.

* **`checkov` as a Dev Container tool** — it is deliberately absent from
  `mise.toml`. Installing it alongside `semgrep` hangs
  `osv-scanner`'s pip transitive-dependency resolver indefinitely (each resolves fine alone in
  ~12–13s; together `osv-scanner` never returns, even with a 600s timeout). `semgrep` is the
  one kept because it catches app-level issues nothing else in the local stack checks for,
  whereas checkov's actual findings in this repo (Dockerfile non-root user, Actions
  permissions) are already covered by Trivy and zizmor. Checkov still runs in CI through
  MegaLinter's bundled `REPOSITORY_CHECKOV` linter, so CI coverage is unaffected.

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
Eligible patch update?  --yes-->  Renovate automerges once required checks pass
        |
        no
        v
Maintainer reviews the changes
        |
        v
Maintainer approves and merges
```

Renovate may maintain the PR and keep it rebased. Non-eligible updates remain under the
maintainer's final merge decision.

`platformAutomerge` is kept `false` in `renovate.json`, so Renovate performs automerge itself
rather than requesting GitHub's native auto-merge. Renovate merges an eligible PR only when its
branch's status checks are green.

### Required repository settings

Automerge of eligible patch updates depends on these GitHub settings. They are not stored in
the repository and must be verified in the repository's settings:

* Branch protection on `main` requires the mandatory CI status checks, so a PR cannot merge
  until they pass. Do not weaken this to make automerge work.
* Branch protection must not require an approving review for the bot's PR to merge. If it does,
  Renovate cannot complete automerge and those patch PRs wait for a maintainer.
* The Renovate app must be allowed to push and merge in this repository.

### Limitations

* Automerge only runs when Renovate next processes the PR, so a merge may lag a green check.
* Each PR waits for the seven-day minimum release age before Renovate proposes it.
* Patch updates that fail CI or depend on an unmerged PR are not merged.

This policy is intentionally narrow while the project's test coverage, integration testing and
CI confidence continue to improve.
