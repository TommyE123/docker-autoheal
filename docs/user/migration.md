# Migration

There is currently no special migration procedure for users — upgrading to a new image
version is the normal Docker Compose/`docker run` upgrade flow (pull the new image, recreate
the container). Configuration, restart history, and quarantine state persist across upgrades
because they live in the mounted `/data` volume, not in the container itself.

If a specific release ever requires a manual migration step (for example, a breaking
configuration-format change), it will be called out in that release's notes.

## Health check moved into the image

The image now defines its own `HEALTHCHECK` and no longer ships `curl`. Earlier versions of
this guide's Compose example added a `healthcheck:` block that calls `curl`. If you copied it,
delete that block and let the image's health check apply. A Compose `healthcheck:` overrides the
image's, so a copied `curl` probe would fail with `exec: "curl": executable file not found` and
the container would show `unhealthy`. If you want your own probe, use one the image can run,
for example:

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:3131/health', timeout=5)"]
```

The only "migration" documented anywhere in this repository is an internal, already-completed
restructuring of the codebase (flat files → the current `app/` package layout) — see
[Project restructuring](../historical/project-restructuring.md) if you're curious, but it has
no bearing on how you run or upgrade Docker Autoheal today.

## API documentation URLs

The interactive API documentation moved from `/docs`, `/redoc` and `/openapi.json` to
`/api/swagger`, `/api/redoc` and `/api/openapi.json`. The old paths are removed without a
redirect, so update bookmarks, scripts and any reverse-proxy rules that referenced them. The
pages are a developer tool, so the web UI menu no longer links to them.

## See also

- [Installation](installation.md)
- [Configuration](configuration.md)
