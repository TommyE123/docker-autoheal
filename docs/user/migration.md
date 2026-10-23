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

## See also

- [Installation](installation.md)
- [Configuration](configuration.md)
