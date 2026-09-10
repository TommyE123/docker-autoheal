# Maintenance Mode

Maintenance mode lets you pause all auto-healing while keeping the dashboard and API
available — useful while you're doing manual container work and don't want Auto-Heal
"fixing" what you're deliberately stopping or restarting.

## What it does

- The monitoring loop keeps running and the dashboard stays usable, but every container
  check is skipped — no restarts, no quarantines, no auto-unquarantines.
- Manual actions (restart, unquarantine) via the UI or API still work normally.
- State persists across restarts of the Auto-Heal container and across page refreshes —
  it's stored in `/data/maintenance.json`, not just in the browser.

## Using it

**Enable:** click **Enter Maintenance Mode** on the Dashboard. A modal overlay appears
with a live elapsed-time timer, and the background UI is grayed out.

**Disable:** click **Exit Maintenance Mode** in the modal (or **Exit Maintenance** on the
dashboard). Auto-healing resumes immediately.

**Via the API:**

```bash
curl -X POST http://localhost:3131/api/maintenance/enable
curl -X POST http://localhost:3131/api/maintenance/disable
curl http://localhost:3131/api/maintenance/status
```

## See also

- [Usage](usage.md)
- [Health checks](health-checks.md)
