"""
Configuration management for Docker Auto-Heal Service
Handles in-memory configuration state with JSON export/import support
"""

import contextlib
import json
import logging
import os
import re
import stat
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.config.init_defaults import initialize_defaults

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


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

    mode: str = Field(default="on-failure", description="Restart mode: on-failure, health, or both")
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
        default_factory=dict, description="Restart counts by stable_id"
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


_MAX_TCP_PORT = 65535


class HealthCheckConfig(BaseModel):
    """Custom health check configuration for a container"""

    container_id: str
    check_type: str = Field(description="Type: http, tcp, exec, or docker")
    interval_seconds: int = Field(default=30, ge=1)
    timeout_seconds: int = Field(default=10, ge=1)
    retries: int = Field(default=3, ge=1)
    # For HTTP checks
    http_endpoint: str | None = None
    http_expected_status: int | None = 200
    # For TCP checks
    tcp_port: int | None = None
    # For exec checks
    exec_command: list[str] | None = None

    @model_validator(mode="after")
    def _require_fields_for_check_type(self) -> HealthCheckConfig:
        """Reject checks that can never pass, or that name an unsupported type.

        A check missing the field its type needs, or carrying an unusable value
        for it (port outside 1-65535, blank endpoint, empty or blank exec command),
        fails on every cycle and restarts the container each time, so refuse it up front.
        """
        required: dict[str, tuple[str, ...]] = {
            "http": ("http_endpoint", "http_expected_status"),
            "tcp": ("tcp_port",),
            "exec": ("exec_command",),
            "docker": (),
        }
        if self.check_type not in required:
            raise ValueError(
                f"Unknown check_type {self.check_type!r}; expected one of: {', '.join(required)}"
            )
        missing = [name for name in required[self.check_type] if getattr(self, name) is None]
        if missing:
            raise ValueError(f"check_type {self.check_type!r} requires: {', '.join(missing)}")
        problem = self._unusable_value()
        if problem:
            raise ValueError(problem)
        return self

    def _unusable_value(self) -> str | None:
        """Describe an unusable value for the check's own field, or None if it is usable."""
        command = self.exec_command or []
        if self.check_type == "http" and not (self.http_endpoint or "").strip():
            return "http_endpoint must not be empty"
        if self.check_type == "tcp" and not 1 <= (self.tcp_port or 0) <= _MAX_TCP_PORT:
            return f"tcp_port must be between 1 and {_MAX_TCP_PORT}"
        if self.check_type == "exec" and not (command and command[0].strip()):
            return "exec_command must be a non-empty list starting with a non-blank command"
        return None


class AutoHealEvent(BaseModel):
    """Current auto-heal event log entry with a UTC-aware timestamp."""

    timestamp: datetime
    container_id: str
    container_name: str
    event_type: str  # restart, quarantine, auto_unquarantine, etc.
    restart_count: int
    status: str  # success, failure, quarantined
    message: str

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        """Reject timestamps that are not timezone-aware UTC datetimes."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be UTC")
        return value


class LegacyAutoHealEvent(BaseModel):
    """Persisted event that predates the UTC-aware event model contract.

    The timestamp remains its original JSON text because a naive timestamp
    cannot be safely assigned a timezone after the fact.
    """

    timestamp: str
    container_id: str
    container_name: str
    event_type: str
    restart_count: int
    status: str
    message: str

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_non_utc_legacy_value(cls, value: str) -> str:
        """Only retain values that cannot satisfy the current UTC contract."""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("legacy timestamp must be ISO 8601") from error

        if parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0):
            raise ValueError("UTC timestamps must use AutoHealEvent")
        return value


StoredAutoHealEvent = AutoHealEvent | LegacyAutoHealEvent


# Top-level AutoHealConfig sections that are themselves a single model and can
# be validated independently of one another. uptime_kuma_mappings is handled
# separately below since it is a list rather than a single model.
_CONFIG_SECTION_MODELS: dict[str, type] = {
    "monitor": MonitorConfig,
    "containers": ContainersConfig,
    "restart": RestartConfig,
    "filters": FiltersConfig,
    "ui": UIConfig,
    "alerts": AlertsConfig,
    "observability": ObservabilityConfig,
    "uptime_kuma": UptimeKumaConfig,
    "notifications": NotificationsConfig,
}


def _merge_dicts(current: Any, update: Any) -> Any:
    """Recursively merge ``update`` into ``current`` when both are dicts.

    Omitted keys keep their current values at every level. Any other
    ``update`` value replaces ``current`` outright.
    """
    if not (isinstance(current, dict) and isinstance(update, dict)):
        return update
    return {**current, **{k: _merge_dicts(current.get(k), v) for k, v in update.items()}}


def _atomic_write_json(path: Path, data: Any, **dump_kwargs: Any) -> None:
    """Write ``data`` as JSON to ``path`` without ever exposing a partial file.

    The document is written to a uniquely named temporary file in the same
    directory (so the final rename stays on one filesystem), flushed to disk,
    then moved over ``path`` with ``os.replace``. If anything fails, the
    previous ``path`` is left untouched and the temporary file is removed.
    An existing file keeps its permission bits and, where the process is
    allowed to restore it, its owner and group; a symlinked ``path`` is written
    through to its target. This matches the previous truncate-in-place
    behaviour. Restoring ownership is best effort: it needs privilege (or a
    group the process belongs to), so without it the save still succeeds and
    the file is simply owned by the process that wrote it. ACLs and extended
    attributes are not carried over.
    """
    path = Path(os.path.realpath(path))
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    existing: os.stat_result | None = None
    with contextlib.suppress(FileNotFoundError):
        existing = path.stat()
    try:
        # Exclusive create. A new file keeps the umask default, like "w" did. An
        # existing file may be stricter than that default (for example 0600,
        # since it holds credentials), so its replacement starts owner-only and
        # is widened to the existing mode before any data is written; it is
        # never readable by anyone the original was not.
        fd = os.open(
            temp_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666 if existing is None else 0o600,
        )
        with os.fdopen(fd, "w") as f:
            if existing is not None:
                # Ownership first: chown can clear setuid/setgid bits, so the
                # mode is applied after it. The file stays 0600 until then, so
                # handing it to the original owner never makes it readable by
                # anyone the original was not. Failing to chown (no privilege,
                # or a filesystem that cannot) must not fail the save.
                mode = stat.S_IMODE(existing.st_mode)
                try:
                    os.fchown(fd, existing.st_uid, existing.st_gid)
                except OSError as error:
                    logger.debug("Could not preserve ownership of %s: %s", path, error)
                    # The file may now be in a different group (the process's, or
                    # one inherited from a setgid directory). Giving that group
                    # the original group's permissions would grant it access the
                    # original never did, so drop them unless the groups match.
                    if os.fstat(fd).st_gid != existing.st_gid:
                        mode &= ~0o070
                os.fchmod(fd, mode)
            json.dump(data, f, **dump_kwargs)
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


_CONFIG_FILENAME = "config.json"
_EVENTS_FILENAME = "events.json"
_QUARANTINE_FILENAME = "quarantine.json"
_MAINTENANCE_FILENAME = "maintenance.json"
_ATOMIC_WRITE_TARGETS = (
    _CONFIG_FILENAME,
    _EVENTS_FILENAME,
    _QUARANTINE_FILENAME,
    _MAINTENANCE_FILENAME,
)
_ATOMIC_TEMP_PATTERN = re.compile(
    r"\.(?:" + "|".join(re.escape(name) for name in _ATOMIC_WRITE_TARGETS) + r")\.[0-9a-f]{32}\.tmp"
)


def _remove_orphaned_temp_files(data_dir: Path) -> None:
    """Delete temp files ``_atomic_write_json`` left behind after a hard kill.

    A SIGKILL, OOM kill or power loss between creating the temp file and the
    rename skips the cleanup in ``_atomic_write_json``, leaving a full copy of
    the document (config.json holds credentials) in the data directory. Only
    names matching the helper's exact pattern for the known files are touched,
    and only regular files. Every match is removed: the service is the only
    writer, and this runs before anything is loaded or saved.
    """
    try:
        candidates = sorted(data_dir.iterdir())
    except OSError as error:
        logger.warning("Could not scan %s for orphaned temp files: %s", data_dir, error)
        return

    for candidate in candidates:
        if not _ATOMIC_TEMP_PATTERN.fullmatch(candidate.name):
            continue
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            candidate.unlink()
        except OSError as error:
            logger.warning("Could not remove orphaned temp file %s: %s", candidate, error)
        else:
            logger.warning("Removed orphaned temp file left by an interrupted save: %s", candidate)


class ConfigManager:
    """
    Thread-safe configuration manager with file-based persistence
    All data is automatically saved to /data directory
    """

    # Data directory paths
    DATA_DIR = Path("/data")
    CONFIG_FILE = DATA_DIR / _CONFIG_FILENAME
    EVENTS_FILE = DATA_DIR / _EVENTS_FILENAME
    RESTART_COUNTS_FILE = DATA_DIR / "restart_counts.json"
    QUARANTINE_FILE = DATA_DIR / _QUARANTINE_FILENAME
    MAINTENANCE_FILE = DATA_DIR / _MAINTENANCE_FILENAME

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # Create data directory if it doesn't exist
        self._ensure_data_directory()

        # Drop temp files orphaned by a hard kill mid-save, before loading anything
        _remove_orphaned_temp_files(self.DATA_DIR)

        # Initialize default files if they don't exist
        initialize_defaults(self.DATA_DIR)

        # Load persisted data or initialize with defaults
        self._config = self._load_config()
        self._event_log: list[StoredAutoHealEvent] = self._load_events()
        # Populated by _load_config() from the custom_health_checks section.
        self._custom_health_checks: dict[str, HealthCheckConfig] = getattr(
            self, "_custom_health_checks", {}
        )
        # _container_restart_counts removed - now stored in self._config.containers.restart_counts
        self._quarantined_containers: set = self._load_quarantine()
        self._maintenance_mode: bool = False
        self._maintenance_start_time: datetime | None = None
        self._load_maintenance_mode()

        logger.info("ConfigManager initialized with persistent storage at /data")

    def _ensure_data_directory(self) -> None:
        """Create data directory and subdirectories if they don't exist"""
        try:
            self.DATA_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("Data directory ensured at: %s", self.DATA_DIR)
        except Exception as e:
            logger.error("Failed to create data directory: %s", e)
            # Fallback to current directory if /data is not writable
            self.DATA_DIR = Path("./data")
            self.DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._update_file_paths()
            logger.warning("Using fallback data directory: %s", self.DATA_DIR)

    def _update_file_paths(self) -> None:
        """Update all file paths when data directory changes"""
        self.CONFIG_FILE = self.DATA_DIR / _CONFIG_FILENAME
        self.EVENTS_FILE = self.DATA_DIR / _EVENTS_FILENAME
        self.RESTART_COUNTS_FILE = self.DATA_DIR / "restart_counts.json"
        self.QUARANTINE_FILE = self.DATA_DIR / _QUARANTINE_FILENAME
        self.MAINTENANCE_FILE = self.DATA_DIR / _MAINTENANCE_FILENAME

    def _load_config(self) -> AutoHealConfig:
        """Load configuration from file, containing failures to the section that caused them.

        Malformed JSON has nothing to selectively recover, so it falls back to
        full defaults, same as before. Once the JSON parses, each top-level
        AutoHealConfig section is validated independently: a section that
        fails validation is reset to its own default and logged by name,
        while every other section is kept exactly as loaded from disk. This
        mirrors the per-record recovery _load_events() already does for the
        events log.
        """
        if not self.CONFIG_FILE.exists():
            return AutoHealConfig()

        try:
            with self.CONFIG_FILE.open("r") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(
                "Config file %s is not valid JSON: %s, using defaults",
                self.CONFIG_FILE,
                e,
            )
            return AutoHealConfig()

        if not isinstance(data, dict):
            logger.warning(
                "Config file %s did not contain a JSON object, using defaults",
                self.CONFIG_FILE,
            )
            return AutoHealConfig()

        # Extracting and parsing custom health checks is kept separate from
        # AutoHealConfig section loading below, so a failure in one can never
        # cascade into resetting the other.
        self._custom_health_checks = self._parse_custom_health_checks(
            data.pop("custom_health_checks", {})
        )

        config = self._build_config_from_sections(data)
        logger.info("Configuration loaded from disk")
        return config

    def _parse_custom_health_checks(self, raw: Any) -> dict[str, HealthCheckConfig]:
        """Parse the custom_health_checks block, skipping invalid entries.

        An entry that is invalid (for example a tcp check with no ``tcp_port``,
        or an unknown ``check_type``) is skipped with a warning so it cannot
        discard the other checks. Such an entry never passed, so skipping it
        stops the restart loop it caused; the skipped entry is dropped from
        config.json on the next save. A malformed block defaults to empty.
        """
        try:
            items = list(raw.items())
        except AttributeError as error:
            logger.warning(
                "Failed to load custom_health_checks from disk: %s, using defaults",
                error,
            )
            return {}
        checks: dict[str, HealthCheckConfig] = {}
        for cid, hc in items:
            try:
                checks[cid] = HealthCheckConfig(**hc)
            except (ValidationError, TypeError) as error:
                logger.warning(
                    "Skipping invalid custom health check for %s: %s",
                    cid,
                    error,
                )
        return checks

    def _build_config_from_sections(self, data: dict) -> AutoHealConfig:
        """Build AutoHealConfig one top-level section at a time.

        Each section is validated independently so a single bad section (a
        wrong type, an unrecognized shape, a future field an older version
        can't read) can't discard the rest of a working configuration.
        """
        sections: dict[str, Any] = {}

        for name, model in _CONFIG_SECTION_MODELS.items():
            if name not in data:
                continue
            try:
                sections[name] = model(**data[name])
            except (ValidationError, TypeError) as error:
                logger.warning("Resetting config section '%s' to defaults: %s", name, error)

        if "uptime_kuma_mappings" in data:
            try:
                sections["uptime_kuma_mappings"] = [
                    UptimeKumaMapping(**item) for item in data["uptime_kuma_mappings"]
                ]
            except (ValidationError, TypeError) as error:
                logger.warning(
                    "Resetting config section 'uptime_kuma_mappings' to defaults: %s",
                    error,
                )

        return AutoHealConfig(**sections)

    def _save_config(self) -> None:
        """Save configuration to file"""
        try:
            config_dict = self._config.model_dump()
            config_dict["custom_health_checks"] = {
                cid: hc.model_dump() for cid, hc in self._custom_health_checks.items()
            }
            _atomic_write_json(self.CONFIG_FILE, config_dict, indent=2, default=str)
            logger.debug("Configuration saved to disk")
        except Exception as e:
            logger.error("Failed to save config to disk: %s", e)

    def _load_events(self) -> list[StoredAutoHealEvent]:
        """Load current and legacy events without losing valid history."""
        try:
            if self.EVENTS_FILE.exists():
                with self.EVENTS_FILE.open("r") as f:
                    data = json.load(f)
                    events: list[StoredAutoHealEvent] = []
                    for index, event in enumerate(data):
                        try:
                            events.append(AutoHealEvent(**event))
                        except ValidationError, TypeError:
                            try:
                                events.append(LegacyAutoHealEvent(**event))
                                logger.warning(
                                    "Loaded legacy event %d with a timestamp outside "
                                    "the current contract; "
                                    "preserving its original timestamp text",
                                    index,
                                )
                            except (ValidationError, TypeError) as error:
                                logger.warning(
                                    "Skipping invalid event %d from disk: %s",
                                    index,
                                    error,
                                )
                    logger.info("Loaded %s events from disk", len(events))
                    return events
        except Exception as e:
            logger.warning("Failed to load events from disk: %s", e)
        return []

    def _save_events(self) -> None:
        """Save events to file"""
        try:
            events_data = [event.model_dump(mode="json") for event in self._event_log]
            _atomic_write_json(self.EVENTS_FILE, events_data, indent=2, default=str)
            logger.debug("Saved %s events to disk", len(self._event_log))
        except Exception as e:
            logger.error("Failed to save events to disk: %s", e)

    # Restart counts are now stored in config.json, no separate file needed

    def _load_quarantine(self) -> set:
        """Load quarantine list from file or return empty set"""
        try:
            if self.QUARANTINE_FILE.exists():
                with self.QUARANTINE_FILE.open("r") as f:
                    data = json.load(f)
                    quarantine = set(data)
                    logger.info("Loaded %s quarantined containers from disk", len(quarantine))
                    return quarantine
        except Exception as e:
            logger.warning("Failed to load quarantine list from disk: %s", e)
        return set()

    def _save_quarantine(self) -> None:
        """Save quarantine list to file"""
        try:
            _atomic_write_json(self.QUARANTINE_FILE, list(self._quarantined_containers), indent=2)
            logger.debug(
                "Saved %s quarantined containers to disk",
                len(self._quarantined_containers),
            )
        except Exception as e:
            logger.error("Failed to save quarantine list to disk: %s", e)

    def _load_maintenance_mode(self) -> None:
        """Load maintenance mode state from file"""
        try:
            if self.MAINTENANCE_FILE.exists():
                with self.MAINTENANCE_FILE.open("r") as f:
                    data = json.load(f)
                    enabled = data.get("enabled", False)
                    start_time = data.get("start_time")
                    parsed_start_time = datetime.fromisoformat(start_time) if start_time else None

                    self._maintenance_mode = enabled
                    self._maintenance_start_time = parsed_start_time
                    logger.info("Loaded maintenance mode state: %s", self._maintenance_mode)
        except Exception as e:
            logger.warning("Failed to load maintenance mode from disk: %s", e)

    def _save_maintenance_mode(self) -> None:
        """Save maintenance mode state to file"""
        try:
            data = {
                "enabled": self._maintenance_mode,
                "start_time": self._maintenance_start_time.isoformat()
                if self._maintenance_start_time
                else None,
            }
            _atomic_write_json(self.MAINTENANCE_FILE, data, indent=2)
            logger.debug("Saved maintenance mode state: %s", self._maintenance_mode)
        except Exception as e:
            logger.error("Failed to save maintenance mode to disk: %s", e)

    def get_config(self) -> AutoHealConfig:
        """Get current configuration (thread-safe)"""
        with self._lock:
            return self._config.model_copy(deep=True)

    def _keep_live_restart_state(self, config: AutoHealConfig) -> None:
        """Copy the live restart counts and history into ``config``, discarding its own.

        Callers must hold ``self._lock``. These two fields are runtime state written by
        ``record_restart`` and ``clear_restart_history``; a configuration a caller built
        from an earlier ``get_config()`` may hold an outdated copy of them.
        """
        live = self._config.containers
        config.containers.restart_counts = live.restart_counts
        config.containers.restart_history = live.restart_history

    def update_config(self, config: AutoHealConfig) -> None:
        """Replace the configuration (thread-safe), keeping the live restart state.

        ``containers.restart_counts`` and ``containers.restart_history`` in ``config``
        are ignored: the live values are kept, so a copy taken with ``get_config()``
        before a restart was recorded or cleared cannot undo that change. Use
        ``import_config`` to replace them and ``clear_restart_history`` to clear a
        container's entries.

        Everything else in ``config`` replaces the live values, so a caller that reads,
        awaits and then writes can still overwrite another writer's change. Use
        ``mutate()`` for a read-modify-write.
        """
        with self._lock:
            new_config = config.model_copy(deep=True)
            self._keep_live_restart_state(new_config)
            self._config = new_config
            self._save_config()

    @contextlib.contextmanager
    def mutate(self) -> Iterator[AutoHealConfig]:
        """Read-modify-write the configuration atomically (thread-safe).

        Holds the lock for the whole block and yields a deep copy of the live
        configuration. When the block exits normally a copy of it replaces the live
        configuration and is saved; if it is unchanged nothing is written. Like
        ``update_config`` it does not validate the copy, so one earlier invalid value
        cannot block every later write. If the block raises, the copy is discarded and
        the live configuration and file are left as they were. As with
        ``update_config``, the live ``containers.restart_counts`` and
        ``containers.restart_history`` are kept.

        The block must not ``await``: the lock is a ``threading.RLock``, which cannot
        keep out other coroutines on the event loop's thread, so an ``await`` inside
        reopens the lost-update window this method exists to close. Do the awaited
        work first, then enter ``mutate()`` and re-check against the fresh copy.
        """
        with self._lock:
            working = self._config.model_copy(deep=True)
            yield working
            if working == self._config:
                return
            new_config = working.model_copy(deep=True)
            self._keep_live_restart_state(new_config)
            self._config = new_config
            self._save_config()

    def update_partial_config(self, **kwargs: Any) -> None:
        """Update specific top-level configuration fields.

        Unknown keys are ignored. A dict value is merged into the existing
        section recursively, so omitted fields keep their current values at every
        level; any other value replaces the section. The merged result is validated before it
        replaces the current config, so an invalid value raises
        ``ValidationError`` and leaves the config and file untouched.
        """
        with self._lock:
            config_dict = self._config.model_dump()
            for key, value in kwargs.items():
                if key not in config_dict:
                    continue
                config_dict[key] = _merge_dicts(config_dict[key], value)
            self._config = AutoHealConfig.model_validate(config_dict)
            self._save_config()

    def export_config(self) -> str:
        """Export configuration as JSON string"""
        with self._lock:
            config_dict = self._config.model_dump()
            config_dict["custom_health_checks"] = {
                cid: hc.model_dump() for cid, hc in self._custom_health_checks.items()
            }
            return json.dumps(config_dict, indent=2, default=str)

    def import_config(self, json_str: str) -> None:
        """Import configuration from JSON string"""
        with self._lock:
            config_dict = json.loads(json_str)

            # Extract and store custom health checks separately
            custom_hc = config_dict.pop("custom_health_checks", {})

            # Validate the full payload before assigning anything, so a
            # failure anywhere leaves the live config and custom health
            # checks completely untouched.
            new_config = AutoHealConfig(**config_dict)
            new_custom_health_checks = {
                cid: HealthCheckConfig(**hc) for cid, hc in custom_hc.items()
            }

            self._config = new_config
            self._custom_health_checks = new_custom_health_checks

            # Persist to disk
            self._save_config()

    def add_event(self, event: AutoHealEvent) -> None:
        """Add event to log (thread-safe, with size limit)"""
        with self._lock:
            self._event_log.append(event)
            max_entries = self._config.ui.max_log_entries
            if len(self._event_log) > max_entries:
                self._event_log = self._event_log[-max_entries:]
            self._save_events()

    def get_events(self, limit: int | None = None) -> list[StoredAutoHealEvent]:
        """Get event log (thread-safe)"""
        with self._lock:
            if limit:
                return self._event_log[-limit:]
            return self._event_log.copy()

    def clear_events(self) -> None:
        """Clear all events from log (thread-safe)"""
        with self._lock:
            self._event_log.clear()
            self._save_events()
            logger.info("All events cleared")

    def add_custom_health_check(self, health_check: HealthCheckConfig) -> None:
        """Add custom health check for a container"""
        with self._lock:
            self._custom_health_checks[health_check.container_id] = health_check
            self._save_config()

    def get_custom_health_check(self, container_id: str) -> HealthCheckConfig | None:
        """Get custom health check for a container"""
        with self._lock:
            return self._custom_health_checks.get(container_id)

    def remove_custom_health_check(self, container_id: str) -> None:
        """Remove custom health check for a container"""
        with self._lock:
            self._custom_health_checks.pop(container_id, None)
            self._save_config()

    def get_all_custom_health_checks(self) -> dict[str, HealthCheckConfig]:
        """Get all custom health checks"""
        with self._lock:
            return self._custom_health_checks.copy()

    def record_restart(self, container_id: str, window_seconds: int | None = None) -> None:
        """Record a container restart: bump the lifetime count and timestamp the restart.

        When ``window_seconds`` is given, timestamps that can no longer fall inside that
        window are pruned so the history stays bounded.
        """
        with self._lock:
            counts = self._config.containers.restart_counts
            counts[container_id] = counts.get(container_id, 0) + 1
            now = time.time()
            history = self._config.containers.restart_history.setdefault(container_id, [])
            if window_seconds is not None:
                history[:] = [t for t in history if now - t < window_seconds]
            history.append(now)
            self._save_config()

    def get_restart_count(self, container_id: str, window_seconds: int) -> int:
        """Count restarts in the trailing ``window_seconds``.

        A restart exactly ``window_seconds`` old has expired. Counts persisted before
        timestamps were tracked have no history, so they never count towards the window.
        """
        with self._lock:
            now = time.time()
            history = self._config.containers.restart_history.get(container_id, [])
            return sum(1 for t in history if now - t < window_seconds)

    def get_total_restart_count(self, container_id: str) -> int:
        """Get total restart count (all time) - from config.json"""
        with self._lock:
            return self._config.containers.restart_counts.get(container_id, 0)

    def quarantine_container(self, container_id: str) -> None:
        """Mark container as quarantined"""
        with self._lock:
            self._quarantined_containers.add(container_id)
            self._save_quarantine()

    def unquarantine_container(self, container_id: str) -> None:
        """Remove container from quarantine"""
        with self._lock:
            self._quarantined_containers.discard(container_id)
            self._save_quarantine()

    def is_quarantined(self, container_id: str) -> bool:
        """Check if container is quarantined"""
        with self._lock:
            return container_id in self._quarantined_containers

    def get_quarantined_containers(self) -> set:
        """Get all quarantined containers"""
        with self._lock:
            return self._quarantined_containers.copy()

    def clear_restart_history(self, container_id: str) -> None:
        """Clear restart history for a container"""
        with self._lock:
            counts_had = self._config.containers.restart_counts.pop(container_id, None)
            history_had = self._config.containers.restart_history.pop(container_id, None)
            if counts_had is not None or history_had is not None:
                self._save_config()

    def enable_maintenance_mode(self) -> None:
        """Enable maintenance mode"""
        with self._lock:
            self._maintenance_mode = True
            self._maintenance_start_time = datetime.now(UTC)
            self._save_maintenance_mode()

    def disable_maintenance_mode(self) -> None:
        """Disable maintenance mode"""
        with self._lock:
            self._maintenance_mode = False
            self._maintenance_start_time = None
            self._save_maintenance_mode()

    def is_maintenance_mode(self) -> bool:
        """Check if maintenance mode is enabled"""
        with self._lock:
            return self._maintenance_mode

    def get_maintenance_start_time(self) -> datetime | None:
        """Get maintenance mode start time"""
        with self._lock:
            return self._maintenance_start_time


# Global configuration manager instance
config_manager = ConfigManager()
