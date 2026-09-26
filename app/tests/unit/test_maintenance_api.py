"""
Unit tests for the maintenance mode endpoints in
``app/api/routes/maintenance.py``.

Endpoint functions are called directly (matching ``test_events_api.py``)
rather than through an HTTP client - ``config_manager`` is isolated per test
(see ``conftest.py``).
"""

import pytest

from app.api.routes.maintenance import (
    disable_maintenance_mode,
    enable_maintenance_mode,
    get_maintenance_status,
)
from app.config.config_manager import config_manager


@pytest.mark.asyncio
class TestMaintenanceMode:
    async def test_enable_reports_start_time(self):
        result = await enable_maintenance_mode()

        assert result["maintenance_mode"] is True
        assert result["maintenance_start_time"] is not None
        assert config_manager.is_maintenance_mode() is True

    async def test_disable_clears_maintenance_mode(self):
        config_manager.enable_maintenance_mode()

        result = await disable_maintenance_mode()

        assert result["maintenance_mode"] is False
        assert config_manager.is_maintenance_mode() is False

    async def test_status_reflects_current_state(self):
        assert (await get_maintenance_status())["maintenance_mode"] is False

        config_manager.enable_maintenance_mode()

        status = await get_maintenance_status()
        assert status["maintenance_mode"] is True
        assert status["maintenance_start_time"] is not None
