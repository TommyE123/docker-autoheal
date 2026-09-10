# Publishing to Docker Hub

## Automated (recommended)

`.github/workflows/docker-publish.yml` builds and pushes the image automatically:

- **On a version tag push** (`v*.*.*`, e.g. `v1.2.0`) — builds for `linux/amd64` and
  `linux/arm64`, and pushes tags for the exact version, `{major}.{minor}`, `{major}`, and
  `latest`.
- **Manually** via `workflow_dispatch`, with an optional `tag` input (defaults to
  `latest`).

It also pushes the contents of [`DOCKER_HUB_README.md`](../../DOCKER_HUB_README.md) as
the repository description on Docker Hub, using
[`peter-evans/dockerhub-description`](https://github.com/peter-evans/dockerhub-description).
Keep that file accurate and user-facing — it's the first thing someone sees on Docker Hub
before they've cloned the repository, so it should stand on its own (it doesn't have the
luxury of relative links into `docs/`, so key information is inlined rather than just
linked).

**Required repository secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.

To cut a release:

```bash
git tag v1.2.0
git push origin v1.2.0
```

GitHub Actions builds and pushes automatically — no local Docker Hub login needed.

## Manual publishing

For ad-hoc builds/pushes without going through CI:

```bash
docker login

docker build -t <your-username>/docker-autoheal:latest .
docker tag <your-username>/docker-autoheal:latest <your-username>/docker-autoheal:v1.2.0

docker push <your-username>/docker-autoheal:latest
docker push <your-username>/docker-autoheal:v1.2.0
```

The repository also includes Windows helper scripts for this (`publish.bat`,
`publish.ps1`, `publish-interactive.bat`) — useful if you're publishing from a Windows
machine outside CI, but not required for the automated flow above.

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
docker pull <your-username>/docker-autoheal:latest
docker run -d --name test-autoheal \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -p 3131:3131 <your-username>/docker-autoheal:latest
curl http://localhost:3131/health
docker rm -f test-autoheal
```

## See also

- [Release Process](release-process.md)
- [Dependency Management](dependency-management.md)
