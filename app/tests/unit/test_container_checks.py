"""
Unit tests for the monitoring engine's per-cycle container checks.

These exercise ``_check_containers`` and ``_check_single_container``, which glue
together monitoring selection, quarantine handling, health evaluation and
restarts.
"""

import pytest

from app.config.config_manager import config_manager
from app.tests.unit.conftest import make_container


def event_types() -> list:
    return [event.event_type for event in config_manager.get_events()]


@pytest.mark.asyncio
class TestCheckSingleContainer:
    """End-to-end decision making for one container."""

    async def test_healthy_container_is_not_restarted(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)

        await engine._check_single_container(container)

        assert docker_client.restart_calls == []
        assert config_manager.get_events() == []

    async def test_crashed_container_is_restarted(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)

        await engine._check_single_container(container)

        assert docker_client.restart_calls == ["web"]
        assert event_types() == ["restart"]

    async def test_unmonitored_container_is_ignored(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1, labels={})
        docker_client.add_container(container, info)

        await engine._check_single_container(container)

        assert docker_client.restart_calls == []

    async def test_maintenance_mode_suspends_all_checks(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        config_manager.enable_maintenance_mode()

        await engine._check_single_container(container)

        assert docker_client.restart_calls == []
        assert config_manager.get_events() == []

    async def test_checks_resume_when_maintenance_mode_is_disabled(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        config_manager.enable_maintenance_mode()
        await engine._check_single_container(container)
        config_manager.disable_maintenance_mode()

        await engine._check_single_container(container)

        assert docker_client.restart_calls == ["web"]


@pytest.mark.asyncio
class TestQuarantinedContainerChecks:
    """A quarantined container is skipped until it heals itself."""

    async def test_quarantined_unhealthy_container_is_skipped(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await engine._check_single_container(container)

        assert docker_client.restart_calls == []
        assert config_manager.is_quarantined("web") is True

    async def test_quarantined_running_but_unhealthy_container_stays_quarantined(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "mode", "both"))
        container, info = make_container(name="web", status="running", health={"status": "unhealthy"})
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await engine._check_single_container(container)

        assert config_manager.is_quarantined("web") is True
        assert docker_client.restart_calls == []

    async def test_recovered_container_is_auto_unquarantined(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        config_manager.record_restart("web")
        engine._backoff_delays["web"] = 320

        await engine._check_single_container(container)

        assert config_manager.is_quarantined("web") is False
        assert config_manager.get_restart_count("web", 600) == 0
        assert engine._backoff_delays["web"] == 10  # reset to initial_seconds
        assert event_types() == ["auto_unquarantine"]

    async def test_auto_unquarantine_sends_notification(
        self, engine, docker_client, mock_notification_manager
    ):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await engine._check_single_container(container)

        mock_notification_manager.send_event_notification.assert_awaited_once()

    async def test_quarantine_recorded_under_container_name_is_honoured(self, engine, docker_client):
        """Backwards compatibility: quarantine entries predating stable IDs."""
        container, info = make_container(
            name="stack-web-1",
            status="running",
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)
        config_manager.quarantine_container("stack-web-1")

        await engine._check_single_container(container)

        assert config_manager.is_quarantined("stack-web-1") is False
        assert event_types() == ["auto_unquarantine"]

    async def test_quarantine_recorded_under_container_id_is_honoured(self, engine, docker_client):
        container, info = make_container(name="web", container_id="e" * 64, status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("e" * 64)

        await engine._check_single_container(container)

        assert config_manager.is_quarantined("e" * 64) is False

    async def test_quarantine_survives_container_recreation(self, engine, docker_client):
        """A recreated compose container keeps its quarantine via the stable ID."""
        labels = {
            "autoheal": "true",
            "com.docker.compose.project": "stack",
            "com.docker.compose.service": "web",
        }
        config_manager.quarantine_container("stack_web")
        new_container, new_info = make_container(
            name="stack-web-1",
            container_id="c" * 64,
            status="exited",
            exit_code=1,
            labels=labels,
        )
        docker_client.add_container(new_container, new_info)

        await engine._check_single_container(new_container)

        assert config_manager.is_quarantined("stack_web") is True
        assert docker_client.restart_calls == []


@pytest.mark.asyncio
class TestContainerDisappearance:
    """Containers can vanish between being listed and being inspected."""

    async def test_disappeared_container_is_handled_without_error(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        docker_client.remove_container(container)  # inspection now returns {}

        await engine._check_single_container(container)

        assert docker_client.restart_calls == []
        assert config_manager.get_events() == []

    async def test_disappeared_container_during_full_cycle(self, engine, docker_client):
        alive, alive_info = make_container(name="web", container_id="a" * 64, status="exited", exit_code=1)
        gone, gone_info = make_container(name="ghost", container_id="f" * 64, status="exited", exit_code=1)
        docker_client.add_container(alive, alive_info)
        docker_client.add_container(gone, gone_info)
        docker_client._info.pop(gone.id)  # still listed, but no longer inspectable

        await engine._check_containers()

        assert docker_client.restart_calls == ["web"]

    async def test_inspection_error_does_not_stop_other_containers(self, engine, docker_client):
        broken, broken_info = make_container(name="broken", container_id="b" * 64, status="exited", exit_code=1)
        healthy, healthy_info = make_container(name="web", container_id="a" * 64, status="exited", exit_code=1)
        docker_client.add_container(broken, broken_info)
        docker_client.add_container(healthy, healthy_info)
        docker_client.info_errors[broken.id] = RuntimeError("container is gone")

        await engine._check_containers()

        assert docker_client.restart_calls == ["web"]


@pytest.mark.asyncio
class TestCheckContainersDockerFailures:
    """Docker API failures must never crash the monitoring loop."""

    async def test_reconnects_when_the_connection_is_lost(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        docker_client.connected = False

        await engine._check_containers()

        assert docker_client.reconnect_calls == 1
        assert docker_client.restart_calls == ["web"]

    async def test_gives_up_for_this_cycle_when_reconnect_fails(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        docker_client.connected = False
        docker_client.reconnect_succeeds = False

        await engine._check_containers()

        assert docker_client.reconnect_calls == 1
        assert docker_client.restart_calls == []

    async def test_listing_failure_is_swallowed(self, engine, docker_client):
        docker_client.list_containers_error = RuntimeError("docker daemon unavailable")

        await engine._check_containers()

        assert docker_client.restart_calls == []

    async def test_multiple_containers_are_checked_in_one_cycle(self, engine, docker_client):
        crashed, crashed_info = make_container(name="crashed", container_id="a" * 64, status="exited", exit_code=1)
        running, running_info = make_container(name="running", container_id="b" * 64, status="running")
        unlabelled, unlabelled_info = make_container(
            name="unlabelled", container_id="c" * 64, status="exited", exit_code=1, labels={}
        )
        for container, info in (
            (crashed, crashed_info),
            (running, running_info),
            (unlabelled, unlabelled_info),
        ):
            docker_client.add_container(container, info)

        await engine._check_containers()

        assert docker_client.restart_calls == ["crashed"]


@pytest.mark.asyncio
class TestAutoUnquarantineFailure:
    """Failures while auto-unquarantining must not escape the check cycle."""

    async def test_error_is_swallowed_and_container_stays_quarantined(
        self, engine, docker_client, monkeypatch
    ):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        def boom(_container_id):
            raise RuntimeError("could not write quarantine file")

        monkeypatch.setattr(config_manager, "unquarantine_container", boom)

        await engine._check_single_container(container)

        assert config_manager.is_quarantined("web") is True
        assert config_manager.get_events() == []
