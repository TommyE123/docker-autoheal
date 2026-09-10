# Notifications

Docker Auto-Heal can send a notification whenever it restarts, quarantines, or
auto-unquarantines a container, or a health check fails. Notifications are **disabled by
default** and delivered asynchronously (via a background queue), so a slow or unreachable
notification endpoint never blocks monitoring.

## Supported services

| Service | Notes |
|---|---|
| Generic webhook | JSON POST to any URL, with optional custom headers |
| Discord | Rich embeds |
| Slack | Formatted blocks |
| Telegram | Via a bot token + chat ID |
| ntfy | Push notifications, self-hosted or [ntfy.sh](https://ntfy.sh) |
| Gotify | Self-hosted push server |
| Pushover | Cross-platform push |

## Setting up a notification service

From the **Notifications** tab in the web UI:

1. Toggle notifications on.
2. Add a service, choose its type, and fill in the type-specific fields (webhook URL,
   bot token, API key, etc.).
3. Use **Test** to send a sample notification before saving.
4. Choose which event types should trigger notifications.

Or via the API:

```bash
curl -X POST http://localhost:3131/api/notifications/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "team-discord",
    "type": "discord",
    "enabled": true,
    "url": "https://discord.com/api/webhooks/..."
  }'
```

| Endpoint | Purpose |
|---|---|
| `GET /api/notifications/config` | Current notification configuration |
| `PUT /api/notifications/config` | Update enabled state / event filters / services in bulk |
| `POST /api/notifications/services` | Add a service |
| `PUT /api/notifications/services/{name}` | Update a service |
| `DELETE /api/notifications/services/{name}` | Remove a service |
| `POST /api/notifications/test/{name}` | Send a test notification |

## Event filtering

By default, notifications are sent for these event types:
`restart`, `quarantine`, `health_check_failed`, `auto_unquarantine`.

An empty event filter list means "notify on every event type" (this also includes
`auto_monitor`, sent when a container is automatically added to monitoring because it
started with the `autoheal=true` label). Adjust the filter from the Notifications tab or
via `PUT /api/notifications/config`.

## Multiple services

You can configure any number of services at once — a notification firing sends to every
enabled, non-filtered-out service.

## See also

- [Health checks](health-checks.md) — what triggers a restart or quarantine
- [Configuration](configuration.md#alerts) — the separate, simpler webhook-only
  `alerts.webhook` setting (fires only on quarantine)
