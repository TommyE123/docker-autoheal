# Publishing to Docker Hub & GHCR

## Automated (this is how every release actually happens)

A versioned release is published only when a [Release Please](https://github.com/googleapis/release-please)
release PR is merged - **not** on every ordinary merge to `main`. (Every merge does refresh the
`beta` image; see step 5.)
`.github/workflows/release-please.yml` ("Release Please") runs on every push to `main` and:

1. Runs the `release-please` job. On an ordinary application PR merging to `main`, this only
   creates or updates a standing Release PR (its title, description and `version.txt` bump
   reflect every Conventional Commit merged since the last release; `skip-changelog: true` means
   no `CHANGELOG.md` entry is written) and does **not** publish anything.
2. When the Release PR itself is merged, that merge is a normal push to `main` like any other,
   and `release-please` recognises it: it creates the Git tag and GitHub Release for the
   calculated version, and its `release_created` output becomes `true`.
3. The `docker-release` job runs only when `release_created == 'true'`. It builds the image for
   `linux/amd64` and `linux/arm64` and pushes it to **both** Docker Hub
   (`docker.io/tommye123/docker-autoheal`) and GitHub Container Registry
   (`ghcr.io/tommye123/docker-autoheal`), tagged with `release-please`'s own `tag_name` output
   and `latest`. The version is never recalculated here - it comes directly from Release Please.
4. Updates the Docker Hub repository description from
   [`docs/maintainer/docker-hub-readme.md`](./docker-hub-readme.md).
5. Runs the `beta-build` job on every push to `main`, including release merges, as long as the
   `release-please` job succeeded (if it fails or is cancelled, `beta-build` is skipped and
   `beta` stays on an older commit). It builds `linux/amd64` and `linux/arm64` and pushes
   a `beta` image to Docker Hub and GHCR, plus a per-commit `beta-<shortsha>` tag to GHCR only.
   A rerun can overwrite that tag, so use the image digest to refer to one exact image.
   `beta` is mutable and tracks the current `main`. After each push, old
   `beta-<shortsha>` GHCR tags are cleaned up, keeping the newest 20. This image is not a
   release and has no version tag or `latest`.

In other words: **merging an ordinary Conventional Commit PR never publishes a release** — it
only updates the Release PR. A human decides when to actually release by merging that PR.

**Required repository secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, and
`RELEASE_PLEASE_TOKEN`, a personal access token the `release-please` job uses to open and
update the Release PR (see below). GHCR push uses the workflow's own `GITHUB_TOKEN` — no
extra secret needed. Newly published GHCR packages default
to **private**; someone with admin access needs to switch the package to public in its GitHub
package settings before `docker pull ghcr.io/...` works for everyone (see the note in
`docs/maintainer/docker-hub-readme.md`).

## PR-time build verification

`.github/workflows/docker-build.yml` ("Docker Build") runs on every pull request to
`main`, including the Release PR itself. Release Please authenticates with the
`RELEASE_PLEASE_TOKEN` personal access token rather than the default `GITHUB_TOKEN`. GitHub
does not let `GITHUB_TOKEN`-authored PRs trigger other workflows, so the Release PR would
never get its required checks; with the token it behaves like any other PR. The workflow builds
the image for both platforms (the production checks run on the amd64 build and the arm64
build is started under emulation) but does **not** push anywhere, for any pull request. This is
separate from, and has no effect on, the release process above.

## Manual publishing

For ad-hoc builds/pushes without going through CI (e.g. to test a change locally before
it reaches `main`):

```bash
docker login
docker login ghcr.io   # only if also pushing to GHCR

docker build -t <your-username>/docker-autoheal:latest .
docker tag <your-username>/docker-autoheal:latest <your-username>/docker-autoheal:v1.2.3

docker push <your-username>/docker-autoheal:latest
docker push <your-username>/docker-autoheal:v1.2.3
```

### Multi-platform manual build

```bash
docker buildx create --name multiarch --use
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t <your-username>/docker-autoheal:latest \
  --push .
```

## Verifying a publish

```bash
docker pull tommye123/docker-autoheal:latest
# or: docker pull ghcr.io/tommye123/docker-autoheal:latest

docker run -d --name test-autoheal \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -p 3131:3131 tommye123/docker-autoheal:latest
curl http://localhost:3131/health
docker rm -f test-autoheal
```

## See also

- [Release Process](release-process.md)
- [Dependency Management](dependency-management.md)
