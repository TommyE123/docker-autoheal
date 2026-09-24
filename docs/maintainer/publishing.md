# Publishing to Docker Hub & GHCR

## Automated (this is how every release actually happens)

Publishing happens only when a [Release Please](https://github.com/googleapis/release-please)
release PR is merged - **not** on every ordinary merge to `main`.
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
   [`DOCKER_HUB_README.md`](../../DOCKER_HUB_README.md).

In other words: **merging an ordinary Conventional Commit PR never publishes a release** — it
only updates the Release PR. A human decides when to actually release by merging that PR.

**Required repository secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`. GHCR push uses the
workflow's own `GITHUB_TOKEN` — no extra secret needed. Newly published GHCR packages default
to **private**; someone with admin access needs to switch the package to public in its GitHub
package settings before `docker pull ghcr.io/...` works for everyone (see the note in
`DOCKER_HUB_README.md`).

## PR-time build verification

`.github/workflows/docker-build.yml` ("Docker Build") runs on every pull request to
`main`, including the Release PR itself. However, Release Please opens and updates that PR
using the default `GITHUB_TOKEN`, so its `pull_request` runs require a maintainer to manually
approve the workflow run before they execute — they are not automatic like an ordinary
contributor PR's checks. When it does run, it builds the image for both platforms but does
**not** push anywhere unless the PR is from a branch on this repository itself (not a fork), in
which case it pushes a `pr-<number>` / commit-SHA tagged image to GHCR as a build cache/
verification artifact. This is separate from, and has no effect on, the release process above.

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

The repository also includes Windows helper scripts for this (`publish.bat`,
`publish.ps1`, `publish-interactive.bat`) — these predate both the automated release
workflow and the GHCR mirror (Docker Hub only), and are not part of the real release
path.

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
