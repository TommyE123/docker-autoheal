# Publishing to Docker Hub & GHCR

## Automated (recommended)

`.github/workflows/docker-publish.yml` ("Publish to Docker Hub & GHCR") builds and
pushes the image to **both** Docker Hub (`docker.io/tommye123/docker-autoheal`) and
GitHub Container Registry (`ghcr.io/tommye123/docker-autoheal`) automatically:

- **On a version tag push** (`v*.*.*`, e.g. `v1.2.0`) — builds for `linux/amd64` and
  `linux/arm64`, and pushes tags for the exact version, `{major}.{minor}`, `{major}`, and
  `latest` to both registries.
- **Manually** via `workflow_dispatch`, with an optional `tag` input (defaults to
  `latest`).

It also pushes the contents of [`DOCKER_HUB_README.md`](../../DOCKER_HUB_README.md) as
the repository description on Docker Hub, using
[`peter-evans/dockerhub-description`](https://github.com/peter-evans/dockerhub-description)
(GHCR has no equivalent repository-description step). Keep that file accurate and
user-facing — it's the first thing someone sees on Docker Hub before they've cloned the
repository, so it should stand on its own (it doesn't have the luxury of relative links
into `docs/`, so key information is inlined rather than just linked).

**Required repository secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`. GHCR push uses
the workflow's own `GITHUB_TOKEN` (with `packages: write` permission) — no extra secret
needed. Newly published GHCR packages default to **private**; someone with admin access
needs to switch the package to public in its GitHub package settings before
`docker pull ghcr.io/...` works for everyone (see the note in `DOCKER_HUB_README.md`).

To cut a release:

```bash
git tag v1.2.0
git push origin v1.2.0
```

GitHub Actions builds and pushes to both registries automatically — no local registry
login needed.

## Manual publishing

For ad-hoc builds/pushes without going through CI:

```bash
docker login
docker login ghcr.io   # only if also pushing to GHCR

docker build -t <your-username>/docker-autoheal:latest .
docker tag <your-username>/docker-autoheal:latest <your-username>/docker-autoheal:v1.2.0

docker push <your-username>/docker-autoheal:latest
docker push <your-username>/docker-autoheal:v1.2.0
```

The repository also includes Windows helper scripts for this (`publish.bat`,
`publish.ps1`, `publish-interactive.bat`) — useful if you're publishing from a Windows
machine outside CI, but not required for the automated flow above, and they predate the
GHCR mirror (Docker Hub only).

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
