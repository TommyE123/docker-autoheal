# Release Process

## Versioning

Proper [Semantic Versioning](https://semver.org/) (`vMAJOR.MINOR.PATCH`, e.g. `v2.1.3`),
calculated automatically from Conventional Commit messages — never chosen by hand.

## Releases are calculated automatically from Conventional Commits

There is no manual "cut a release" step. `.github/workflows/docker-release.yml` runs on
every push to `main` and automatically:

1. Calculates (without creating a tag yet) the next version from the Conventional Commit
   messages merged since the last release tag: a `fix:` PR title bumps the patch version,
   `feat:` bumps minor, and a `!` after the type or a `BREAKING CHANGE:` footer bumps
   major. A push with none of those (`docs`, `chore`, `ci`, `test`, `style`, `refactor`,
   ...) releases nothing.
2. Builds and pushes the Docker image (Docker Hub + GHCR) for that version and `latest`.
3. Only once that succeeds, creates the Git tag — a tag is never created for an image
   that failed to build.
4. Creates a GitHub release with auto-generated notes.

See [Publishing](publishing.md) for the full mechanics.

**Practical implication:** merging a `fix`/`feat`/breaking-change PR to `main` ships it —
CI (`tests.yml`) passing is the only gate before that happens, so make sure a PR is
actually ready before merging, not just before opening. The PR title's Conventional
Commit type (already required by `semantic-pr-title.yml`) is what decides whether, and
how, it releases — there's no separate release label or classification step.

## What's automated vs. manual

| Step                                                                                                                                       | Automated?                                                                                       |
|--------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| Unit tests on every push/PR                                                                                                                | Yes (`tests.yml`)                                                                                |
| MegaLinter on every PR to `main`                                                                                                           | Yes (`mega-linter.yml`)                                                                          |
| Docker image build (verification only, no release) on every PR                                                                             | Yes (`docker-build.yml`)                                                                         |
| SemVer calculation from Conventional Commits, Git tag, image build + push (Docker Hub + GHCR), and GitHub release, on every push to `main` | Yes (`docker-release.yml`)                                                                       |
| Docker Hub description update                                                                                                              | Yes (part of `docker-release.yml`), only when a release was produced                             |
| Dependency updates                                                                                                                         | Yes, via Renovate (see [Dependency Management](dependency-management.md))                        |
| Choosing patch vs. minor vs. major                                                                                                         | Yes — derived from each PR's Conventional Commit title, never chosen by hand                     |
| GitHub release notes                                                                                                                       | Yes — auto-generated from merged PRs (`gh release create --generate-notes`)                      |
| Changelog file                                                                                                                             | No — this project does not maintain a running `CHANGELOG.md`; GitHub Releases serve that purpose |

## See also

- [Publishing](publishing.md)
- [Dependency Management](dependency-management.md)
