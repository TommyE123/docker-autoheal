# Migration

Most upgrades need no manual step: upgrading to a new image version is the normal Docker
Compose/`docker run` upgrade flow (pull the new image, recreate the container). Configuration,
restart history, and quarantine state persist across upgrades because they live in the mounted
`/data` volume, not in the container itself.

The one exception in the current release is the health check, described below. If a specific
release ever requires a manual migration step (for example, a breaking configuration-format
change), it will be called out in that release's notes.

## Health check moved into the image

The image now defines its own `HEALTHCHECK` and no longer ships `curl`. Earlier versions of
this guide's Compose example added a `healthcheck:` block that calls `curl`. If you copied it,
delete that block, then run `docker compose up -d` to recreate the container so the image's
health check applies. A Compose `healthcheck:` overrides the
image's, so a copied `curl` probe would fail with `exec: "curl": executable file not found` and
the container would show `unhealthy`. If you want your own probe, use one the image can run,
for example:

```yaml
healthcheck:
  test:
    - CMD
    - python
    - -c
    - "import urllib.request as r; r.build_opener(r.ProxyHandler({})).open('http://localhost:3131/health', timeout=5)"
```

An older internal restructuring of the codebase (flat files → the current `app/` package layout)
is recorded in [Project restructuring](../historical/project-restructuring.md). It has no bearing on
how you run or upgrade Docker Autoheal today.

## API documentation URLs

The interactive API documentation moved from `/docs`, `/redoc` and `/openapi.json` to
`/api/swagger`, `/api/redoc` and `/api/openapi.json`. The old paths are removed without a
redirect, so update bookmarks, scripts and any reverse-proxy rules that referenced them. The
pages are a developer tool, so the web UI menu no longer links to them.

## See also

- [Installation](installation.md)
- [Configuration](configuration.md)
