"""
Pydantic request/response models shared across the API routers.

Split out of ``app/api/api.py`` (issue #321) so route modules can depend on
these without importing the whole API module.
"""

from typing import Any

from pydantic import BaseModel

from app.config.config_manager import (
    AutoHealConfig,  # noqa: TC001 (Pydantic needs this at runtime to build the model schema)
)


class ContainerSelectionRequest(BaseModel):
    container_ids: list[str]
    enabled: bool


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: str
    state: dict[str, Any]
    labels: dict[str, str]
    health: dict[str, Any] | None
    restart_count: int
    monitored: bool
    quarantined: bool
    uptime_kuma_status: int | None = None  # 0=down, 1=up, 2=pending, 3=maintenance, None=not mapped/disabled
    uptime_kuma_monitor_name: str | None = None


class SystemStatus(BaseModel):
    monitoring_active: bool
    docker_connected: bool
    total_containers: int
    monitored_containers: int
    quarantined_containers: int
    maintenance_mode: bool
    maintenance_start_time: str | None
    config: AutoHealConfig
