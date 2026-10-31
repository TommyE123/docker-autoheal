"""
Unit tests for the monitoring engine's per-cycle container checks.

These exercise ``_check_containers`` and ``_check_single_container``, which glue
together monitoring selection, quarantine handling, health evaluation and
restarts.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.config.config_manager import config_manager
from app.monitor.recovery import QUARANTINE_STABLE_CHECKS
from app.tests.unit.conftest import (
    INCOMPLETE_INFO_CASES,
    after_backoff,
    make_container,
    until_stable,
)


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

        await after_backoff(engine, engine._check_single_container, container)

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
        await after_backoff(engine, engine._check_single_container, container)
        config_manager.disable_maintenance_mode()

        await after_backoff(engine, engine._check_single_container, container)

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
        container, info = make_container(
            name="web", status="running", health={"status": "unhealthy"}
        )
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is True
        assert docker_client.restart_calls == []

    async def test_unhealthy_check_in_the_middle_of_a_streak_resets_it(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "mode", "both"))
        container, info = make_container(name="web", status="running", health={"status": "healthy"})
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()

        docker_client._info[container.id] = {**info, "health": {"status": "unhealthy"}}
        await engine._check_containers()
        docker_client._info[container.id] = info
        await engine._check_containers()

        assert config_manager.is_quarantined("web") is True

    async def test_recovered_container_is_auto_unquarantined(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        config_manager.record_restart("web")
        engine._recovery.backoff_delays["web"] = 320

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is False
        assert config_manager.get_restart_count("web", 600) == 0
        assert engine._recovery.backoff_delays["web"] == 10  # reset to initial_seconds
        assert event_types() == ["auto_unquarantine"]

    async def test_single_running_check_does_not_unquarantine(self, engine, docker_client):
        """A crash-looping container is running between crashes; one snapshot is not recovery."""
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        config_manager.record_restart("web")

        await engine._check_single_container(container)

        assert config_manager.is_quarantined("web") is True
        assert config_manager.get_restart_count("web", 600) == 1
        assert event_types() == []

    async def test_unquarantine_needs_consecutive_healthy_checks(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)
        assert config_manager.is_quarantined("web") is False

        config_manager.quarantine_container("web")
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()
        assert config_manager.is_quarantined("web") is True

    async def test_crash_between_checks_resets_the_streak(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()

        docker_client._info[container.id] = {
            **info,
            "state": {"Status": "exited", "ExitCode": 1},
        }
        await engine._check_containers()
        docker_client._info[container.id] = info
        await engine._check_containers()

        assert config_manager.is_quarantined("web") is True

    async def test_restart_between_checks_resets_the_streak(self, engine, docker_client):
        """Running at every check, but a new run each time: StartedAt changes."""
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        for run in range(QUARANTINE_STABLE_CHECKS + 1):
            docker_client._info[container.id] = {
                **info,
                "started_at": f"2024-01-01T00:00:0{run}Z",
            }
            await engine._check_containers()

        assert config_manager.is_quarantined("web") is True

    @pytest.mark.parametrize("started_at", ["", "not-a-date", "0001-01-01T00:00:00Z"])
    async def test_unusable_started_at_keeps_quarantine_and_records_no_streak(
        self, engine, docker_client, started_at
    ):
        container, info = make_container(name="web", status="running")
        info["started_at"] = started_at
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is True
        assert engine._recovery.quarantine_streaks == {}

    async def test_short_uptime_blocks_unquarantine(self, engine, docker_client):
        """Enough consecutive checks are not enough when the current run is young."""
        container, info = make_container(name="web", status="running")
        info["started_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is True

    async def test_uptime_is_measured_against_the_monitoring_interval(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.monitor, "interval_seconds", 3600))
        container, info = make_container(name="web", status="running")
        info["started_at"] = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is True

    @pytest.mark.parametrize("mode", ["health", "both"])
    async def test_docker_health_starting_is_not_recovered(
        self, engine, docker_client, update_config, mode
    ):
        update_config(lambda c: setattr(c.restart, "mode", mode))
        container, info = make_container(
            name="web", status="running", health={"status": "starting"}
        )
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is True

    async def test_docker_health_starting_is_ignored_in_on_failure_mode(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "mode", "on-failure"))
        container, info = make_container(
            name="web", status="running", health={"status": "starting"}
        )
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is False

    async def test_manual_release_then_requarantine_starts_a_fresh_streak(
        self, engine, docker_client
    ):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()

        config_manager.unquarantine_container("web")
        await engine._check_containers()
        config_manager.quarantine_container("web")
        await engine._check_containers()

        assert config_manager.is_quarantined("web") is True

    async def test_streak_is_dropped_when_container_disappears(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        other, other_info = make_container(name="api", container_id="b" * 64, status="running")
        docker_client.add_container(container, info)
        docker_client.add_container(other, other_info)
        config_manager.quarantine_container("web")
        await engine._check_containers()
        assert container.id in engine._recovery.quarantine_streaks

        docker_client.remove_container(container)
        await engine._check_containers()
        await engine._check_containers()

        assert engine._recovery.quarantine_streaks == {}

    async def test_maintenance_mode_gap_resets_the_streak(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()

        config_manager.enable_maintenance_mode()
        await engine._check_containers()
        config_manager.disable_maintenance_mode()
        await engine._check_containers()

        assert config_manager.is_quarantined("web") is True

    async def _quarantined_web_with_two_healthy_cycles(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()
        assert container.id in engine._recovery.quarantine_streaks
        return container, info

    async def _assert_fresh_streak_is_needed(self, engine):
        """One healthy cycle after the gap must not release; a fresh full streak must"""
        await engine._check_containers()
        assert config_manager.is_quarantined("web") is True
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()
        assert config_manager.is_quarantined("web") is False

    async def test_starting_health_mid_streak_resets_it(self, engine, docker_client, update_config):
        update_config(lambda c: setattr(c.restart, "mode", "both"))
        container, info = await self._quarantined_web_with_two_healthy_cycles(engine, docker_client)

        docker_client._info[container.id] = {**info, "health": {"status": "starting"}}
        await engine._check_containers()
        docker_client._info[container.id] = info

        await self._assert_fresh_streak_is_needed(engine)

    async def test_unusable_started_at_mid_streak_resets_it(self, engine, docker_client):
        container, info = await self._quarantined_web_with_two_healthy_cycles(engine, docker_client)

        docker_client._info[container.id] = {**info, "started_at": ""}
        await engine._check_containers()
        docker_client._info[container.id] = info

        await self._assert_fresh_streak_is_needed(engine)

    async def test_incomplete_container_info_mid_streak_resets_it(self, engine, docker_client):
        container, info = await self._quarantined_web_with_two_healthy_cycles(engine, docker_client)

        docker_client._info[container.id] = {k: v for k, v in info.items() if k != "full_id"}
        await engine._check_containers()
        docker_client._info[container.id] = info

        await self._assert_fresh_streak_is_needed(engine)

    async def test_failed_listing_resets_the_streak(self, engine, docker_client, monkeypatch):
        await self._quarantined_web_with_two_healthy_cycles(engine, docker_client)
        listing = docker_client.list_containers
        monkeypatch.setattr(docker_client, "list_containers", lambda all_containers=False: [])
        await engine._check_containers()
        monkeypatch.setattr(docker_client, "list_containers", listing)

        await self._assert_fresh_streak_is_needed(engine)

    async def test_failed_reconnect_resets_the_streak(self, engine, docker_client):
        await self._quarantined_web_with_two_healthy_cycles(engine, docker_client)
        docker_client.connected = False
        docker_client.reconnect_succeeds = False
        await engine._check_containers()
        docker_client.connected = True
        docker_client.reconnect_succeeds = True

        await self._assert_fresh_streak_is_needed(engine)

    async def test_listing_error_resets_the_streak(self, engine, docker_client, monkeypatch):
        await self._quarantined_web_with_two_healthy_cycles(engine, docker_client)
        listing = docker_client.list_containers

        def boom(all_containers=False):
            raise RuntimeError("docker socket closed")

        monkeypatch.setattr(docker_client, "list_containers", boom)
        await engine._check_containers()
        monkeypatch.setattr(docker_client, "list_containers", listing)

        await self._assert_fresh_streak_is_needed(engine)

    async def test_failed_check_of_a_container_resets_its_streak(
        self, engine, docker_client, monkeypatch
    ):
        await self._quarantined_web_with_two_healthy_cycles(engine, docker_client)
        inspect = docker_client.get_container_info

        def boom(_container):
            raise RuntimeError("inspect failed")

        monkeypatch.setattr(docker_client, "get_container_info", boom)
        await engine._check_containers()
        monkeypatch.setattr(docker_client, "get_container_info", inspect)

        await self._assert_fresh_streak_is_needed(engine)

    async def test_unmonitored_gap_resets_the_streak(self, engine, docker_client):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            await engine._check_containers()

        docker_client._info[container.id] = {**info, "labels": {"autoheal": "false"}}
        await engine._check_containers()
        docker_client._info[container.id] = info
        await engine._check_containers()

        assert config_manager.is_quarantined("web") is True

    async def test_auto_unquarantine_sends_notification(
        self, engine, docker_client, mock_notification_manager
    ):
        container, info = make_container(name="web", status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("web")

        await until_stable(engine._check_containers)

        mock_notification_manager.send_event_notification.assert_awaited_once()

    async def test_quarantine_recorded_under_container_name_is_honoured(
        self, engine, docker_client
    ):
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

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("stack-web-1") is False
        assert event_types() == ["auto_unquarantine"]

    async def test_quarantine_recorded_under_container_id_is_honoured(self, engine, docker_client):
        container, info = make_container(name="web", container_id="e" * 64, status="running")
        docker_client.add_container(container, info)
        config_manager.quarantine_container("e" * 64)

        await until_stable(engine._check_containers)

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
        alive, alive_info = make_container(
            name="web", container_id="a" * 64, status="exited", exit_code=1
        )
        gone, gone_info = make_container(
            name="ghost", container_id="f" * 64, status="exited", exit_code=1
        )
        docker_client.add_container(alive, alive_info)
        docker_client.add_container(gone, gone_info)
        docker_client._info.pop(gone.id)  # still listed, but no longer inspectable

        await after_backoff(engine, engine._check_containers)

        assert docker_client.restart_calls == ["web"]

    async def test_inspection_error_does_not_stop_other_containers(self, engine, docker_client):
        broken, broken_info = make_container(
            name="broken", container_id="b" * 64, status="exited", exit_code=1
        )
        healthy, healthy_info = make_container(
            name="web", container_id="a" * 64, status="exited", exit_code=1
        )
        docker_client.add_container(broken, broken_info)
        docker_client.add_container(healthy, healthy_info)
        docker_client.info_errors[broken.id] = RuntimeError("container is gone")

        await after_backoff(engine, engine._check_containers)

        assert docker_client.restart_calls == ["web"]


@pytest.mark.asyncio
class TestCheckContainersDockerFailures:
    """Docker API failures must never crash the monitoring loop."""

    async def test_reconnects_when_the_connection_is_lost(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        docker_client.connected = False

        await after_backoff(engine, engine._check_containers)

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
        crashed, crashed_info = make_container(
            name="crashed", container_id="a" * 64, status="exited", exit_code=1
        )
        running, running_info = make_container(
            name="running", container_id="b" * 64, status="running"
        )
        unlabelled, unlabelled_info = make_container(
            name="unlabelled",
            container_id="c" * 64,
            status="exited",
            exit_code=1,
            labels={},
        )
        for container, info in (
            (crashed, crashed_info),
            (running, running_info),
            (unlabelled, unlabelled_info),
        ):
            docker_client.add_container(container, info)

        await after_backoff(engine, engine._check_containers)

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

        attempts = []

        def boom(_container_id):
            attempts.append(_container_id)
            raise RuntimeError("could not write quarantine file")

        monkeypatch.setattr(config_manager, "unquarantine_container", boom)

        await until_stable(engine._check_containers)

        assert attempts == ["web"]
        assert config_manager.is_quarantined("web") is True
        assert config_manager.get_events() == []


@pytest.mark.asyncio
async def test_name_filters_do_not_match_container_info_without_name(engine):
    container, info = make_container(name="web")
    del info["name"]
    config = config_manager.get_config()
    config.filters.whitelist_names = ["*"]
    config_manager.update_config(config)

    assert engine.should_monitor_container(container, info) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("missing", "labels"), INCOMPLETE_INFO_CASES)
async def test_container_info_missing_identifier_is_skipped_without_restart(
    engine, docker_client, caplog, missing, labels
):
    container, info = make_container(name="web", status="exited", exit_code=1, labels=labels)
    del info[missing]
    docker_client.add_container(container, info)

    with caplog.at_level("WARNING"):
        await engine._check_single_container(container)

    assert docker_client.restart_calls == []
    assert config_manager.get_events() == []
    # Logs the name, or the ID when the name is what is missing
    logged = info["full_id"] if missing == "name" else info["name"]
    assert [r.getMessage() for r in caplog.records] == [
        "Skipping container with incomplete identifiers: " + logged
    ]
