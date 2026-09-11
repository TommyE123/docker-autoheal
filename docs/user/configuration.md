# Configuration

Docker Auto-Heal has **no environment-variable configuration**. All settings live in
`/data/config.json` and can be changed through the web UI, the REST API, or by editing
the file directly (the service reloads it on restart). Sensible defaults are written to
`/data/config.json` the first time the service starts.

> If you've seen older documentation or blog posts referencing environment variables like
> `AUTOHEAL_INTERVAL` or `AUTOHEAL_LOG_LEVEL` — those do not exist in the current
> application. Use the web UI's **Configuration** tab or the `/api/config` endpoints
> instead.

## Changing configuration

**Via the web UI (recommended):** open `http://<host>:3131`, go to **Configuration**, and
use the Monitor Settings / Restart Policy / Filters / Observability sections. Changes save
immediately.

**Via the API:**

```bash
# Read current configuration
curl http://localhost:3131/api/config

# Update just the monitor settings
curl -X PUT http://localhost:3131/api/config/monitor \
  -H "Content-Type: application/json" \
  -d '{"interval_seconds": 15, "label_key": "autoheal", "label_value": "true", "include_all": false}'
```

**Export/import:** the Configuration tab has Export (downloads the current config as
JSON) and Import (uploads a JSON file to replace it) — useful for backups or moving
configuration between environments.

## Configuration reference

### `monitor`

| Field | Default | Description |
|---|---|---|
| `interval_seconds` | `30` | How often (in seconds) containers are checked |
| `label_key` | `autoheal` | Label key used to select containers for monitoring |
| `label_value` | `true` | Label value that marks a container for monitoring |
| `include_all` | `false` | If `true`, monitor every container regardless of labels |

### `restart`

| Field | Default | Description |
|---|---|---|
| `mode` | `on-failure` | `on-failure` (restart on non-zero exit), `health` (restart on failing health check), or `both` |
| `cooldown_seconds` | `60` | Minimum time between restart attempts for the same container |
| `max_restarts` | `3` | Restarts allowed within the window below before quarantine |
| `max_restarts_window_seconds` | `600` | Time window the restart threshold is measured over |
| `respect_manual_stop` | `true` | Don't restart a container that exited cleanly (exit code 0) |
| `backoff.enabled` | `true` | Apply exponential backoff between restart attempts |
| `backoff.initial_seconds` | `10` | Delay before the first backed-off restart |
| `backoff.multiplier` | `2.0` | Multiplier applied to the delay after each restart |

### `filters`

Whitelist/blacklist containers by name pattern (glob-style, e.g. `web-*`) or by label
key/value pairs, independent of the `autoheal` label:

| Field | Description |
|---|---|
| `whitelist_names` | Only monitor containers whose name matches one of these patterns |
| `blacklist_names` | Never monitor containers whose name matches one of these patterns |
| `whitelist_labels` | Only monitor containers matching at least one of these label filters |
| `blacklist_labels` | Never monitor containers matching one of these label filters |

Blacklists are checked before whitelists; explicit selection/exclusion (via the UI or
`autoheal` label) takes priority over both.

### `ui`

| Field | Default | Description |
|---|---|---|
| `listen_address` | `0.0.0.0` | Address the web UI/API binds to |
| `listen_port` | `3131` | Port the web UI/API binds to |
| `max_log_entries` | `50` | Maximum number of events kept in the in-memory/persisted event log |
| `allow_export_json` / `allow_import_json` | `true` | Enable/disable config export and import from the UI |

### `alerts`

| Field | Default | Description |
|---|---|---|
| `enabled` | `true` | Enable the legacy webhook alert (separate from the [notification system](notifications.md)) |
| `webhook` | *(none)* | Webhook URL that receives a JSON payload when a container is quarantined |
| `notify_on_quarantine` | `true` | Send the webhook alert on quarantine events |

### `observability`

| Field | Default | Description |
|---|---|---|
| `prometheus_enabled` | `true` | Expose the Prometheus `/metrics` endpoint |
| `metrics_port` | `9090` | Port the metrics server listens on |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `log_format` | `json` | Log format (informational; current logging output is plain text regardless of this setting) |

### `uptime_kuma` (optional integration)

Docker Auto-Heal can optionally treat an [Uptime Kuma](https://github.com/louislam/uptime-kuma)
monitor's status as an additional health signal. Configure it from **Configuration →
Uptime Kuma** in the UI, or via `/api/uptime-kuma/*`:

| Field | Default | Description |
|---|---|---|
| `enabled` | `false` | Enable the integration |
| `server_url` | *(none)* | Uptime Kuma server URL, e.g. `http://localhost:3001` |
| `username` / `api_token` | *(none)* | Credentials (API key or username/password) |
| `auto_restart_on_down` | `true` | Restart the mapped container when its Uptime Kuma monitor reports DOWN |

Containers are mapped to Uptime Kuma monitors by matching name, or manually via
**Configuration → Uptime Kuma → Mappings**.

## Container selection and restart counts

`containers.selected` / `containers.excluded` and `containers.restart_counts` are managed
automatically by the application (via the UI, labels, and the monitoring engine) — you
normally don't need to edit them directly. Restart counts persist across container
recreation using a *stable identifier* (see [Labels](labels.md#stable-container-identity)),
not Docker's own container ID.

## See also

- [Labels](labels.md)
- [Health checks](health-checks.md)
- [Notifications](notifications.md)
- [Monitoring & metrics](monitoring-and-metrics.md)
