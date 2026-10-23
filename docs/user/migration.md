# Migration

There is currently no special migration procedure for users — upgrading to a new image
version is the normal Docker Compose/`docker run` upgrade flow (pull the new image, recreate
the container). Configuration, restart history, and quarantine state persist across upgrades
because they live in the mounted `/data` volume, not in the container itself.

If a specific release ever requires a manual migration step (for example, a breaking
configuration-format change), it will be called out in that release's notes.

The only "migration" documented anywhere in this repository is an internal, already-completed
restructuring of the codebase (flat files → the current `app/` package layout) — see
[Project restructuring](../historical/project-restructuring.md) if you're curious, but it has
no bearing on how you run or upgrade Docker Auto-Heal today.

## API documentation URLs and optional API key

The interactive API documentation moved from `/docs`, `/redoc` and `/openapi.json` to
`/api/docs`, `/api/redoc` and `/api/openapi.json`. The old paths are removed without a
redirect, so update bookmarks, scripts and any reverse-proxy rules that referenced them.

API-key authentication was added as an opt-in feature. Nothing changes for existing
installations unless you set `AUTOHEAL_API_KEY` or `AUTOHEAL_API_KEY_FILE`; see
[API authentication](configuration.md#api-authentication).

## See also

- [Installation](installation.md)
- [Configuration](configuration.md)
