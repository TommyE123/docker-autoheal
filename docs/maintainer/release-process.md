# Release Process

## Versioning

Proper [Semantic Versioning](https://semver.org/) (`vMAJOR.MINOR.PATCH`, e.g. `v2.1.3`), owned
entirely by [Release Please](https://github.com/googleapis/release-please). Nothing in this
repository calculates a version independently. `release-please-config.json` uses the `simple`
release type, so Release Please tracks and updates the current version directly in
`version.txt`, and maintains `CHANGELOG.md` as part of the same Release PR.

## Release Please, not a "release on every merge"

There is no manual "cut a release" step, and merging an ordinary PR to `main` does **not**
publish anything. `.github/workflows/release-please.yml` runs on every push to `main`:

1. The `release-please` job parses Conventional Commit messages (PR titles, since PRs are
   squash-merged — already required by `semantic-pr-title.yml`) merged since the last release
   and keeps a standing **Release PR** up to date: `fix:` contributes a patch bump, `feat:` a
   minor bump, and a `!` after the type or a `BREAKING CHANGE:` footer a major bump.
2. Merging that Release PR — a normal push to `main` — is what actually creates the release: the
   Git tag, the GitHub Release, the `version.txt` bump, and the `CHANGELOG.md` entry.
3. Only then does the `docker-release` job run, building and publishing the Docker image for
   that exact tag.

See [Publishing](publishing.md) for the full mechanics.

**Practical implication:** a normal PR merge is safe by default — it can never accidentally
publish a production image. Publishing is a deliberate second step: reviewing and merging the
Release PR when you're ready to ship.

## Existing release history

The project's real release history (`v2.0.0` through `v2.0.16`) predates Release Please and is
preserved, not restarted. `release-please-config.json` sets `bootstrap-sha` to the commit
tagged `v2.0.16`, and `.release-please-manifest.json` records `2.0.16` as the current version —
so Release Please's first Release PR only proposes a bump from `2.0.16` onward, using commits
merged after that point. `version.txt` and the initial entries in `CHANGELOG.md` are seeded to
match — `2.0.16` and the real `v2.0.0`–`v2.0.16` release notes, respectively — and Release Please
maintains both going forward.

The repository also has a legacy bare `v2` tag from before this project used per-commit SemVer
tags. Release Please's own tag parser only recognises `vMAJOR.MINOR.PATCH`-shaped tags; a bare
`v2` doesn't match and is ignored automatically — no special exclusion configuration was needed
or added.

## What's automated vs. manual

| Step                                                           | Automated?                                                                |
|----------------------------------------------------------------|---------------------------------------------------------------------------|
| Unit tests on every push/PR                                    | Yes (`tests.yml`)                                                         |
| MegaLinter on every PR to `main`                               | Yes (`mega-linter.yml`)                                                   |
| Docker image build (verification only, no release) on every PR | Yes (`docker-build.yml`)                                                  |
| Production smoke test against the actual PR image              | Yes (`production-smoke-test.yml`, invoked from `docker-build.yml`)        |
| Keeping the Release PR (title, CHANGELOG, version) up to date  | Yes (`release-please.yml`)                                                |
| Choosing patch vs. minor vs. major                             | Yes — derived from Conventional Commit PR titles, never chosen by hand    |
| Deciding *when* to actually release                            | No — a human merges the Release PR when ready                             |
| Git tag + GitHub Release creation                              | Yes, on Release PR merge (`release-please.yml`)                           |
| Docker image build + push (Docker Hub + GHCR) + `latest`       | Yes, gated on an actual release (`release-please.yml`)                    |
| Docker Hub description update                                  | Yes, only when a release was published (part of `release-please.yml`)     |
| Dependency updates                                             | Yes, via Renovate (see [Dependency Management](dependency-management.md)) |
| Changelog file                                                 | Yes — `CHANGELOG.md`, maintained by Release Please                        |
| Version file                                                   | Yes — `version.txt`, maintained by Release Please                         |

## See also

- [Publishing](publishing.md)
- [Dependency Management](dependency-management.md)
