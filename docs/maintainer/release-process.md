# Release Process

## Versioning

The project uses semantic version tags (`vMAJOR.MINOR.PATCH`), e.g. `v1.2.0`.

## Cutting a release

1. Confirm `main` is green: [Unit Tests workflow](https://github.com/TommyE123/docker-autoheal/actions/workflows/tests.yml)
   passing on the latest commit.
2. Tag and push:

   ```bash
   git tag v1.2.0
   git push origin v1.2.0
   ```

3. `.github/workflows/docker-publish.yml` builds and pushes the Docker image
   automatically (see [Publishing](publishing.md)) and updates the Docker Hub
   description.
4. Create a GitHub release for the tag, summarizing what changed. There is currently no
   automated changelog generation — write release notes by hand from the merged PRs since
   the last tag.

## What's automated vs. manual

| Step | Automated? |
|---|---|
| Unit tests on every push/PR | Yes (`tests.yml`) |
| Docker image build + push on version tag | Yes (`docker-publish.yml`) |
| Docker Hub description update | Yes (part of `docker-publish.yml`) |
| Dependency updates | Yes, via Renovate (see [Dependency Management](dependency-management.md)) |
| GitHub release notes | No — written manually |
| Changelog file | No — this project does not currently maintain a running `CHANGELOG.md` |

## See also

- [Publishing](publishing.md)
- [Dependency Management](dependency-management.md)
