# Changelog - Notification System (historical)

> **Historical document.** A feature-by-feature changelog written while the notification
> system was being built. For how notifications work *today*, see
> [Notifications](../user/notifications.md). Kept here for historical context on how the
> feature evolved.

## [v1.3.0]

### Added - Auto-Unquarantine Feature

When a container is quarantined (exceeded max restarts), the system continuously
monitors it. If the container becomes healthy again, it is automatically removed from
quarantine: the restart counter is cleared, an `auto_unquarantine` event is logged, and a
notification is sent (if enabled).

Health verification checks: the container is running, its Docker native health check (if
configured) reports "healthy", and any custom health checks pass.

## [v1.2.0]

### Added - Notification System

- Multi-service notification support: generic webhook, Discord, Slack, Telegram, ntfy,
  Gotify, Pushover.
- Event-based notifications for restarts, quarantines, health check failures,
  auto-monitoring events, and unquarantines.
- Configurable per-event-type filtering; an empty filter means "notify on all events".
- A "Notifications" page in the web UI: enable/disable, manage services, edit event
  filters, and send test notifications.
- Priority levels (low/normal/high) affecting how notifications appear in supporting
  services.
- Async, queue-based delivery so notification failures never block monitoring.

### Notes at the time

- Notifications were (and remain) opt-in, disabled by default.
- Configuration is stored in `data/config.json`.
- This was a purely additive change with no breaking changes to existing installations.
