> **Historical document.** A debugging investigation that traced where the "restarts"
> number shown in the UI actually comes from. The conclusion is still accurate today and
> is now stated directly (without the investigation narrative) in
> [Architecture: stable container identity](../developer/architecture.md#stable-container-identity)
> and [Troubleshooting: restart count looks wrong](../user/troubleshooting.md#restart-count-looks-wrong--doesnt-match-docker).
> Kept here as the original, more detailed trace for anyone who wants the full code path.

# Investigation: where does `container.restart_count` come from? (historical)

**Question:** Is the "Restarts" number shown per-container in the UI Docker's own
`RestartCount`, or something Auto-Heal tracks itself?

**Answer:** It's Auto-Heal's own tracked count, stored in `config.json`, keyed by the
container's stable identifier — not Docker's native counter.

## Trace

1. UI: `ContainersPage.jsx` renders `container.restart_count`.
2. That comes from the API response of `GET /api/containers`
   (`frontend/src/services/api.js`).
3. In `app/api/api.py`, the endpoint calls
   `config_manager.get_total_restart_count(stable_id)` and puts the result directly into
   the response's `restart_count` field.
4. `ConfigManager.get_total_restart_count()` (`app/config/config_manager.py`) returns
   `self._config.containers.restart_counts.get(container_id, 0)` — a value read from
   `config.json`.

Docker's own value (`docker_client_wrapper.py`, reading
`attrs["State"]["RestartCount"]`) *is* fetched elsewhere in the code, but it is not the
value shown in the container list — it's overwritten with the locally tracked count
before the response is built.

## Why this matters

Docker's native `RestartCount` resets when a container is recreated and only counts
restarts driven by Docker's own `restart:` policy. Auto-Heal's tracked count persists
across recreation (because it's keyed by the stable identifier, not the container ID) and
only counts restarts *Auto-Heal itself* performed — which is the number that's actually
useful for understanding auto-healing activity.
