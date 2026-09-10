# Documentation Index

New to Docker Auto-Heal? Start with the [root README](../README.md) — it has a quick
start and links into everything below.

## Users

How to install, configure, and use Docker Auto-Heal.

- [Installation](user/installation.md)
- [Configuration](user/configuration.md)
- [Usage](user/usage.md) — the web UI and REST API
- [Labels](user/labels.md) — enabling auto-healing on your containers
- [Health checks](user/health-checks.md)
- [Monitoring & metrics](user/monitoring-and-metrics.md) — Prometheus, health endpoint, logs
- [Notifications](user/notifications.md)
- [Maintenance mode](user/maintenance-mode.md)
- [Troubleshooting](user/troubleshooting.md)

## Developers

How to set up a development environment and understand the codebase.

- [Development setup](developer/development-setup.md)
- [Architecture](developer/architecture.md)
- [Project structure](developer/project-structure.md)
- [Frontend development](developer/frontend.md)
- [Testing](developer/testing.md)

See also [CONTRIBUTING.md](../CONTRIBUTING.md) for the contribution workflow.

## Maintainers

Repository maintenance: dependencies, publishing, and releases.

- [Dependency management](maintainer/dependency-management.md)
- [Publishing](maintainer/publishing.md)
- [Release process](maintainer/release-process.md)

## Historical

Superseded documents, kept for context. These do **not** describe current behavior —
see the linked current docs instead.

- [Project restructuring](historical/project-restructuring.md) — the flat-files → `app/`
  package migration (completed)
- [Notifications changelog](historical/notifications-changelog.md) — how the notification
  system was built up over releases
- [Restart count investigation](historical/restart-count-investigation.md) — a debugging
  trace of where the UI's restart count comes from
