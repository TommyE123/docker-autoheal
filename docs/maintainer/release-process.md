# Release Process

## Versioning

Semantic version tags (`vMAJOR.MINOR.PATCH`, e.g. `v2.0.3`), grouped into release
**series** by an additional bare `vMAJOR` marker tag (e.g. `v2`) that marks which series
is currently active on `main`.

## Releases happen automatically on every merge to `main`

There is no manual "cut a release" step. `.github/workflows/docker-release.yml` runs on
every push to `main` and automatically:

1. Finds the active series from the highest `vN` marker tag reachable from the commit.
2. Computes the next patch version in that series and creates the Git tag.
3. Builds and pushes the Docker image (Docker Hub + GHCR) for that tag and `latest`.
4. Creates a GitHub release with auto-generated notes.

See [Publishing](publishing.md) for the full mechanics, including how to start a new
release series (major/minor bump) rather than an automatic patch bump.

**Practical implication:** merging a PR to `main` ships it — CI (`tests.yml`) passing is
the only gate before that happens, so make sure a PR is actually ready before merging,
not just before opening.

## Starting a new series

```bash
git tag v3          # marks v3.x.x as the active series
git push origin v3
```

The next push to `main` after that will release `v3.0.0`.

## What's automated vs. manual

| Step                                                                                              | Automated?                                                                                       |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| Unit tests on every push/PR                                                                       | Yes (`tests.yml`)                                                                                |
| MegaLinter on every PR to `main`                                                                  | Yes (`mega-linter.yml`)                                                                          |
| Docker image build (verification only, no release) on every PR                                    | Yes (`docker-build.yml`)                                                                         |
| Docker image build + push (Docker Hub + GHCR) + Git tag + GitHub release, on every push to `main` | Yes (`docker-release.yml`)                                                                       |
| Docker Hub description update                                                                     | Yes (part of `docker-release.yml`)                                                               |
| Dependency updates                                                                                | Yes, via Renovate (see [Dependency Management](dependency-management.md))                        |
| Starting a new major/minor release series                                                         | No — push the `vN` marker tag manually                                                           |
| GitHub release notes                                                                              | Yes — auto-generated from merged PRs (`gh release create --generate-notes`)                      |
| Changelog file                                                                                    | No — this project does not maintain a running `CHANGELOG.md`; GitHub Releases serve that purpose |

## See also

- [Publishing](publishing.md)
- [Dependency Management](dependency-management.md)
