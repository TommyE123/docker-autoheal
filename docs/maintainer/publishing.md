# Publishing to Docker Hub & GHCR

## Automated (this is how every release actually happens)

Publishing is **fully automatic on every push to `main`** — there is no manual tagging
step. `.github/workflows/docker-release.yml` ("Docker Release") runs on every push to
`main` and:

1. Finds the highest `vN` "release series" marker tag reachable from the commit (e.g.
   `v2` selects the `2.x.x` series). If none exists, the workflow fails — a maintainer
   must push a marker tag (`git tag v2 && git push origin v2`) before the first release
   in that series.
2. Computes the next version in that series: `v{N}.0.0` if no `v{N}.x.x` release exists
   yet, otherwise the current highest `v{N}.x.x` tag with its patch number incremented by
   one. There's no way to bump the minor version this way — see below.
3. Builds the image for `linux/amd64` and `linux/arm64` and pushes it to **both** Docker
   Hub (`docker.io/tommye123/docker-autoheal`) and GitHub Container Registry
   (`ghcr.io/tommye123/docker-autoheal`), tagged with the computed version and `latest`.
4. Creates and pushes the new Git tag, and creates a GitHub release for it with
   auto-generated notes (skipped if a release for that tag already exists — this makes
   re-runs after a partial failure safe).
5. Updates the Docker Hub repository description from
   [`DOCKER_HUB_README.md`](../../DOCKER_HUB_README.md).

In other words: **every merge to `main` ships a new patch release** of the active series.
There is no "hold back a release" step short of not merging, and no dry-run mode.

**To bump the minor or major version** (rather than an automatic patch bump), push a new
series marker tag yourself — e.g. `git tag v3 && git push origin v3` starts the `3.x.x`
series at `v3.0.0` on the next push to `main`. There's currently no workflow support for
an in-series minor bump (`v2.1.0` after `v2.0.5`) other than manually pushing that exact
tag before the next `main` push (the workflow only auto-increments the patch number).

**Required repository secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`. GHCR push uses
the workflow's own `GITHUB_TOKEN` — no extra secret needed. Newly published GHCR packages
default to **private**; someone with admin access needs to switch the package to public
in its GitHub package settings before `docker pull ghcr.io/...` works for everyone (see
the note in `DOCKER_HUB_README.md`).

## PR-time build verification

`.github/workflows/docker-build.yml` ("Docker Build") runs on every pull request to
`main`: it builds the image for both platforms but does **not** push anywhere unless the
PR is from a branch on this repository itself (not a fork), in which case it pushes a
`pr-<number>` / commit-SHA tagged image to GHCR as a build cache/verification artifact.
This is separate from, and has no effect on, the release process above.

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
