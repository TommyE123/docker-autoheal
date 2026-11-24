"""Pydantic models for the AutoHeal configuration.

Kept free of side effects: importing this module must not touch the data
directory or create the global ConfigManager. init_defaults relies on that.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MonitorConfig(BaseModel):
    """Monitor configuration settings"""

    interval_seconds: int = Field(default=30, ge=1, description="Monitoring interval in seconds")
    label_key: str = Field(default="autoheal", description="Label key to filter containers")
    label_value: str = Field(default="true", description="Label value to filter containers")
    include_all: bool = Field(
        default=False, description="Monitor all containers regardless of labels"
    )


class BackoffConfig(BaseModel):
    """Restart backoff configuration"""

    enabled: bool = Field(default=True, description="Enable exponential backoff")
    initial_seconds: int = Field(default=10, ge=1, description="Initial backoff delay in seconds")
    multiplier: float = Field(default=2.0, ge=1.0, description="Backoff multiplier")
    max_seconds: int = Field(default=300, ge=1, description="Maximum backoff delay in seconds")


class RestartConfig(BaseModel):
    """Restart policy configuration"""

    # An unrecognised mode silently disables restarts, so reject it. Keep the rejected
    # value out of the ValidationError text that the API and the load path log.
    model_config = ConfigDict(hide_input_in_errors=True)

    mode: Literal["on-failure", "health", "both"] = Field(
        default="on-failure", description="Restart mode: on-failure, health, or both"
    )
    cooldown_seconds: int = Field(default=60, ge=0, description="Cooldown between restarts")
    max_restarts: int = Field(default=3, ge=1, description="Maximum restarts within window")
    max_restarts_window_seconds: int = Field(
        default=600, ge=1, description="Time window for max restarts"
    )
    backoff: BackoffConfig = Field(default_factory=BackoffConfig)
    respect_manual_stop: bool = Field(
        default=True, description="Respect manual container stops (exit code 0)"
    )


class ContainersConfig(BaseModel):
    """Container selection configuration"""

    selected: list[str] = Field(
        default_factory=list, description="Explicitly selected container IDs/names"
    )
    excluded: list[str] = Field(
        default_factory=list, description="Explicitly excluded container IDs/names"
    )
    restart_counts: dict[str, int] = Field(
        default_factory=dict, description="Restart counts by recovery id"
    )
    restart_history: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Restart timestamps (epoch seconds) by recovery id, used for the "
        "max_restarts_window_seconds rolling window",
    )


class FiltersConfig(BaseModel):
    """Filtering rules for containers"""

    whitelist_names: list[str] = Field(
        default_factory=list, description="Container name patterns to whitelist"
    )
    blacklist_names: list[str] = Field(
        default_factory=list, description="Container name patterns to blacklist"
    )
    whitelist_labels: list[dict[str, str]] = Field(
        default_factory=list, description="Label filters to whitelist"
    )
    blacklist_labels: list[dict[str, str]] = Field(
        default_factory=list, description="Label filters to blacklist"
    )


class UIConfig(BaseModel):
    """UI configuration settings"""

    enable: bool = Field(default=True, description="Enable web UI")
    listen_address: str = Field(default="0.0.0.0", description="UI listen address")  # noqa: S104 - the container must listen on all interfaces
    listen_port: int = Field(default=3131, ge=1, le=65535, description="UI listen port")
    allow_export_json: bool = Field(default=True, description="Allow configuration export")
    allow_import_json: bool = Field(default=True, description="Allow configuration import")
    max_log_entries: int = Field(
        default=50, ge=1, description="Maximum log entries to keep in memory"
    )


class AlertsConfig(BaseModel):
    """Alerting configuration"""

    enabled: bool = Field(default=True, description="Enable alerts")
    webhook: str | None = Field(default=None, description="Webhook URL for alerts")
    notify_on_quarantine: bool = Field(
        default=True, description="Send alert when container is quarantined"
    )


class ObservabilityConfig(BaseModel):
    """Observability and metrics configuration"""

    prometheus_enabled: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(default=9090, ge=1, le=65535, description="Metrics endpoint port")
    log_format: str = Field(default="json", description="Log format: json or text")
    log_level: str = Field(
        default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )


class UptimeKumaConfig(BaseModel):
    """Uptime-Kuma integration configuration"""

    enabled: bool = Field(default=False, description="Enable Uptime-Kuma integration")
    server_url: str = Field(
        default="", description="Uptime-Kuma server URL (e.g., http://localhost:3001)"
    )
    username: str = Field(
        default="", description="Uptime-Kuma username (optional for API key auth)"
    )
    api_token: str = Field(default="", description="Uptime-Kuma API token or password")
    auto_restart_on_down: bool = Field(
        default=True, description="Auto-restart container when monitor is DOWN"
    )


class UptimeKumaMapping(BaseModel):
    """Container to Uptime-Kuma monitor mapping"""

    container_id: str = Field(description="Container stable ID (stable across recreations)")
    monitor_friendly_name: str = Field(description="Uptime-Kuma monitor friendly name")
    auto_mapped: bool = Field(default=False, description="Whether this was auto-mapped")


class NotificationService(BaseModel):
    """Notification service configuration"""

    # Rejected values can be credentials (passwords, tokens); keep them out of the
    # ValidationError text that the API logs and returns.
    model_config = ConfigDict(hide_input_in_errors=True)

    name: str = Field(description="Service name (for identification)")
    type: str = Field(
        description="Service type: webhook, discord, slack, telegram, ntfy, gotify, pushover"
    )
    enabled: bool = Field(default=True, description="Enable this notification service")

    # Common fields
    url: str | None = Field(default=None, description="Webhook URL (webhook, discord, slack)")
    headers: dict[str, str] | None = Field(default=None, description="Custom headers for webhook")
    username: str | None = Field(default=None, description="Username (discord, ntfy)")
    password: str | None = Field(default=None, description="Password (ntfy)")

    # Telegram
    bot_token: str | None = Field(default=None, description="Telegram bot token")
    chat_id: str | None = Field(default=None, description="Telegram chat ID")

    # Ntfy
    topic: str | None = Field(default=None, description="Ntfy topic")
    server_url: str | None = Field(
        default=None, description="Ntfy server URL (default: https://ntfy.sh)"
    )
    access_token: str | None = Field(
        default=None,
        description="Ntfy access token (takes precedence over username/password)",
    )

    # Gotify
    app_token: str | None = Field(default=None, description="Gotify app token")

    # Pushover
    user_key: str | None = Field(default=None, description="Pushover user key")
    api_token: str | None = Field(default=None, description="Pushover API token")


class NotificationsConfig(BaseModel):
    """Notifications configuration"""

    model_config = ConfigDict(hide_input_in_errors=True)

    enabled: bool = Field(default=False, description="Enable notification system")
    services: list[NotificationService] = Field(
        default_factory=list, description="List of notification services"
    )
    event_filters: list[str] = Field(
        default_factory=lambda: [
            "restart",
            "quarantine",
            "auto_unquarantine",
            "auto_monitor",
        ],
        description="Event types to send notifications for (empty = all events)",
    )


class AutoHealConfig(BaseModel):
    """Main auto-heal configuration"""

    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    containers: ContainersConfig = Field(default_factory=ContainersConfig)
    restart: RestartConfig = Field(default_factory=RestartConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    uptime_kuma: UptimeKumaConfig = Field(default_factory=UptimeKumaConfig)
    uptime_kuma_mappings: list[UptimeKumaMapping] = Field(default_factory=list)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
