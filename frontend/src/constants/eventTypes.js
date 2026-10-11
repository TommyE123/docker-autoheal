// Single frontend source of truth for event types emitted by the backend.
export const EVENT_TYPES = [
  { value: 'restart', label: 'Container Restart' },
  { value: 'quarantine', label: 'Container Quarantine' },
  { value: 'unquarantine', label: 'Unquarantine' },
  { value: 'auto_unquarantine', label: 'Auto Unquarantine' },
  { value: 'health_check_failed', label: 'Health Check Failed' },
  { value: 'auto_monitor', label: 'Auto Monitor' }
];
