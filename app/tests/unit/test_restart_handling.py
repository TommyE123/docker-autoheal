"""
Unit tests for ``MonitoringEngine._handle_container_restart``.

This covers the restart state machine: cooldown, restart threshold, quarantine,
exponential backoff, successful restarts, failed restarts and the events they
produce.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.config.config_manager import config_manager
from app.tests.unit.conftest import (
    INCOMPLETE_INFO_CASES,
    after_backoff,
    make_container,
    until_stable,
)


def events_of_type(event_type: str) -> list:
    """Return the recorded events of a given type."""
    return [event for event in config_manager.get_events() if event.event_type == event_type]


@pytest.mark.asyncio
class TestRestartDecision:
    """The happy path: an unhealthy container is restarted and recorded."""

    async def test_successful_restart_records_event_and_state(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await after_backoff(
            engine,
            engine._handle_container_restart,
            container,
            info,
            "Container exited with code 1",
        )

        assert docker_client.restart_calls == ["web"]
        assert config_manager.get_restart_count("web", 600) == 1
        assert "web" in engine._last_restart_times

        restarts = events_of_type("restart")
        assert len(restarts) == 1
        assert restarts[0].status == "success"
        assert restarts[0].restart_count == 1
        assert restarts[0].container_name == "web (web)"
        assert restarts[0].container_id == info["full_id"]
        assert "Container exited with code 1" in restarts[0].message

    async def test_successful_restart_sends_notification(
        self, engine, docker_client, mock_notification_manager
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        mock_notification_manager.send_event_notification.assert_awaited_once()

    async def test_restart_is_recorded_against_the_stable_id(self, engine, docker_client):
        """Compose containers are tracked by ``project_service``, not by name."""
        container, info = make_container(
            name="stack-web-1",
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert config_manager.get_restart_count("stack_web", 600) == 1
        assert config_manager.get_restart_count("stack-web-1", 600) == 0
        assert "stack_web" in engine._last_restart_times


@pytest.mark.asyncio
class TestFailedRestart:
    """A restart that the Docker API rejects."""

    async def test_failed_restart_is_recorded_as_a_failure_event(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        restarts = events_of_type("restart")
        assert len(restarts) == 1
        assert restarts[0].status == "failure"
        assert "Restart failed" in restarts[0].message

    async def test_failed_restart_still_counts_towards_the_threshold(self, engine, docker_client):
        """Existing behaviour: failures count, so a broken container is quarantined."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert config_manager.get_restart_count("web", 600) == 1
        assert "web" in engine._last_restart_times

    async def test_failed_restart_does_not_reset_backoff(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert docker_client.restart_calls == ["web"]
        assert engine._backoff_delays["web"] == 20


@pytest.mark.asyncio
class TestCooldown:
    """Restarts are suppressed while the container is inside its cooldown."""

    async def test_restart_suppressed_during_cooldown(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._last_restart_times["web"] = datetime.now(UTC)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == []
        assert config_manager.get_restart_count("web", 600) == 0
        assert config_manager.get_events() == []

    async def test_restart_allowed_once_cooldown_expires(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 60))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._last_restart_times["web"] = datetime.now(UTC) - timedelta(seconds=61)

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert docker_client.restart_calls == ["web"]

    async def test_zero_cooldown_allows_back_to_back_restarts(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")
        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert docker_client.restart_calls == ["web", "web"]
        assert config_manager.get_restart_count("web", 600) == 2

    async def test_cooldown_is_keyed_by_stable_id_not_container_id(
        self, engine, docker_client, update_config
    ):
        """A recreated container inherits the cooldown of its predecessor."""
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 60))
        labels = {
            "autoheal": "true",
            "com.docker.compose.project": "stack",
            "com.docker.compose.service": "web",
        }
        old_container, old_info = make_container(
            name="stack-web-1", container_id="a" * 64, labels=labels
        )
        docker_client.add_container(old_container, old_info)

        await after_backoff(
            engine,
            engine._handle_container_restart,
            old_container,
            old_info,
            "unhealthy",
        )

        new_container, new_info = make_container(
            name="stack-web-1", container_id="c" * 64, labels=labels
        )
        docker_client.add_container(new_container, new_info)

        await after_backoff(
            engine,
            engine._handle_container_restart,
            new_container,
            new_info,
            "unhealthy",
        )

        assert docker_client.restart_calls == ["stack-web-1"]
        assert config_manager.get_restart_count("stack_web", 600) == 1


@pytest.mark.asyncio
class TestRestartThresholdAndQuarantine:
    """Exceeding ``max_restarts`` quarantines the container instead of restarting."""

    async def test_container_is_quarantined_at_the_threshold(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):  # default max_restarts
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is True
        assert docker_client.restart_calls == []

        quarantines = events_of_type("quarantine")
        assert len(quarantines) == 1
        assert quarantines[0].status == "quarantined"
        assert quarantines[0].restart_count == 3
        assert "exceeded 3 restarts" in quarantines[0].message

    async def test_container_below_threshold_is_still_restarted(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(2):
            config_manager.record_restart("web")

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is False
        assert docker_client.restart_calls == ["web"]
        assert events_of_type("restart")[0].restart_count == 3

    async def test_threshold_is_reached_by_repeated_restarts(
        self, engine, docker_client, update_config
    ):
        """Full transition: restart, restart, restart, quarantine."""
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        for _ in range(4):
            await after_backoff(
                engine, engine._handle_container_restart, container, info, "unhealthy"
            )

        assert docker_client.restart_calls == ["web"] * 3
        assert config_manager.is_quarantined("web") is True
        assert len(events_of_type("restart")) == 3
        assert len(events_of_type("quarantine")) == 1

    async def test_expired_restarts_do_not_quarantine(self, engine, docker_client, monkeypatch):
        """Lifetime total reaches max_restarts, but all of those restarts are outside the window."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")
        window = config_manager.get_config().restart.max_restarts_window_seconds
        real_time = time.time
        monkeypatch.setattr("app.config.config_manager.time.time", lambda: real_time() + window + 1)

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is False
        assert docker_client.restart_calls == ["web"]
        assert events_of_type("quarantine") == []

    async def test_restart_event_reports_the_lifetime_count(
        self, engine, docker_client, monkeypatch
    ):
        """The restart event shows the lifetime total, not just restarts inside the window."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        window = config_manager.get_config().restart.max_restarts_window_seconds
        real_time = time.time
        monkeypatch.setattr("app.config.config_manager.time.time", lambda: real_time() - window - 1)
        for _ in range(5):
            config_manager.record_restart("web")
        monkeypatch.setattr("app.config.config_manager.time.time", real_time)

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert events_of_type("restart")[0].restart_count == 6

    async def test_recent_restarts_quarantine_despite_expired_ones(
        self, engine, docker_client, monkeypatch
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        window = config_manager.get_config().restart.max_restarts_window_seconds
        real_time = time.time
        # Two restarts that happened long ago, then three recent ones
        monkeypatch.setattr("app.config.config_manager.time.time", lambda: real_time() - window - 1)
        for _ in range(2):
            config_manager.record_restart("web")
        monkeypatch.setattr("app.config.config_manager.time.time", real_time)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is True
        assert docker_client.restart_calls == []
        assert events_of_type("quarantine")[0].restart_count == 3

    async def test_quarantine_uses_the_stable_id(self, engine, docker_client):
        container, info = make_container(
            name="stack-web-1",
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("stack_web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("stack_web") is True
        assert config_manager.is_quarantined("stack-web-1") is False

    async def test_custom_threshold_is_honoured(self, engine, docker_client, update_config):
        update_config(lambda c: setattr(c.restart, "max_restarts", 1))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is True

    async def test_quarantine_sends_notification(
        self, engine, docker_client, mock_notification_manager
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        mock_notification_manager.send_event_notification.assert_awaited_once()


def scheduled_delay(engine, recovery_id: str) -> float:
    """Seconds from now until the engine allows the next restart of ``recovery_id``."""
    return (engine._next_allowed_restart[recovery_id] - datetime.now(UTC)).total_seconds()


def elapse_backoff(engine, recovery_id: str) -> None:
    """Pretend the backoff wait recorded for ``recovery_id`` has run out."""
    engine._next_allowed_restart[recovery_id] = datetime.now(UTC) - timedelta(seconds=1)


@pytest.mark.asyncio
class TestRestartBackoff:
    """Exponential backoff between restart attempts."""

    async def test_initial_backoff_delay_is_scheduled_not_slept(
        self, engine, docker_client, recorded_sleeps
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert scheduled_delay(engine, "web") == pytest.approx(10, abs=1)  # default initial_seconds
        assert recorded_sleeps == []
        assert docker_client.restart_calls == []

    async def test_restart_is_skipped_until_the_backoff_has_elapsed(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")
        await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == []
        assert config_manager.get_restart_count("web", 600) == 0

        elapse_backoff(engine, "web")
        await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == ["web"]
        assert "web" not in engine._next_allowed_restart

    async def test_a_new_failure_after_a_restart_waits_for_an_escalated_backoff(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == ["web"]  # not restarted again straight away
        assert scheduled_delay(engine, "web") == pytest.approx(20, abs=1)

    async def test_container_that_recovers_during_the_backoff_is_not_restarted(
        self, engine, docker_client
    ):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_single_container(container)
        assert "web" in engine._next_allowed_restart

        healthy_info = {
            **info,
            "status": "running",
            "state": {"Status": "running", "ExitCode": 0},
        }
        docker_client._info[container.id] = healthy_info
        await engine._check_single_container(container)
        assert "web" not in engine._next_allowed_restart

        docker_client._info[container.id] = info  # fails again later
        await engine._check_single_container(container)

        assert docker_client.restart_calls == []
        assert scheduled_delay(engine, "web") == pytest.approx(10, abs=1)

    async def test_no_restart_while_maintenance_mode_is_enabled(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_single_container(container)
        elapse_backoff(engine, "web")

        config_manager.enable_maintenance_mode()
        await engine._check_single_container(container)

        assert docker_client.restart_calls == []

    async def test_disabling_backoff_during_the_wait_leaves_no_stale_wait(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_single_container(container)
        elapse_backoff(engine, "web")
        update_config(lambda c: setattr(c.restart.backoff, "enabled", False))

        await engine._check_single_container(container)

        assert docker_client.restart_calls == ["web"]  # restarted at once, no backoff
        assert "web" not in engine._next_allowed_restart

        update_config(lambda c: setattr(c.restart.backoff, "enabled", True))
        await engine._check_single_container(container)

        assert docker_client.restart_calls == ["web"]  # a fresh wait, not an instant restart
        assert scheduled_delay(engine, "web") == pytest.approx(10, abs=1)

    async def test_quarantined_container_that_recovers_loses_its_pending_wait(
        self, engine, docker_client
    ):
        """Quarantined by hand while waiting, then it heals and is auto-unquarantined."""
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_single_container(container)
        assert "web" in engine._next_allowed_restart
        config_manager.quarantine_container("web")
        docker_client._info[container.id] = {
            **info,
            "status": "running",
            "state": {"Status": "running", "ExitCode": 0},
        }

        await until_stable(engine._check_containers)

        assert config_manager.is_quarantined("web") is False
        assert "web" not in engine._next_allowed_restart
        assert engine._restart_wait_owner == {}

    async def test_backoff_is_not_reset_by_a_successful_restart_call(self, engine, docker_client):
        """Issue #433: restart() returning says nothing about the container staying up."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await after_backoff(engine, engine._handle_container_restart, container, info, "unhealthy")

        assert docker_client.restart_calls == ["web"]
        assert engine._backoff_delays["web"] == 20

    async def test_backoff_escalates_for_a_crash_looping_container(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        update_config(lambda c: setattr(c.restart, "max_restarts", 10))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        delays = []
        for _ in range(4):
            await engine._handle_container_restart(container, info, "unhealthy")
            delays.append(scheduled_delay(engine, "web"))
            elapse_backoff(engine, "web")
            await engine._handle_container_restart(container, info, "unhealthy")

        assert delays == pytest.approx([10, 20, 40, 80], abs=1)
        assert docker_client.restart_calls == ["web"] * 4

    async def test_backoff_is_capped_at_max_seconds(self, engine, docker_client, update_config):
        def _configure(config):
            config.restart.cooldown_seconds = 0
            config.restart.max_restarts = 10
            config.restart.backoff.max_seconds = 30

        update_config(_configure)
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        delays = []
        for _ in range(4):
            await engine._handle_container_restart(container, info, "unhealthy")
            delays.append(scheduled_delay(engine, "web"))
            elapse_backoff(engine, "web")
            await engine._handle_container_restart(container, info, "unhealthy")

        assert delays == pytest.approx([10, 20, 30, 30], abs=1)
        assert engine._backoff_delays["web"] == 30

    async def test_backoff_cap_below_initial_seconds_bounds_the_first_wait(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart.backoff, "max_seconds", 5))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert scheduled_delay(engine, "web") == pytest.approx(5, abs=1)

    async def test_lowering_the_cap_bounds_an_already_larger_delay(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart.backoff, "max_seconds", 30))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._backoff_delays["web"] = 160

        await engine._handle_container_restart(container, info, "unhealthy")

        assert scheduled_delay(engine, "web") == pytest.approx(30, abs=1)

    async def test_backoff_resets_once_the_container_has_stayed_healthy(
        self, engine, docker_client
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._backoff_delays["web"] = 80
        engine._healthy_since["web"] = ("a" * 64, datetime.now(UTC) - timedelta(seconds=81))

        await engine._check_single_container(container)

        assert engine._backoff_delays["web"] == 10  # reset to initial_seconds

    async def test_brief_health_between_crash_loop_restarts_does_not_reset_backoff(
        self, engine, docker_client
    ):
        """A restarted container is running for a moment even when it keeps crashing."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._backoff_delays["web"] = 80
        engine._healthy_since["web"] = ("a" * 64, datetime.now(UTC) - timedelta(seconds=5))

        await engine._check_single_container(container)

        assert engine._backoff_delays["web"] == 80

    async def test_first_healthy_evaluation_starts_the_healthy_period(self, engine, docker_client):
        """Time since the last restart is not time spent healthy."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._backoff_delays["web"] = 80
        engine._last_restart_times["web"] = datetime.now(UTC) - timedelta(seconds=1000)

        await engine._check_single_container(container)

        assert engine._backoff_delays["web"] == 80
        assert "web" in engine._healthy_since

    async def test_unhealthy_evaluation_restarts_the_healthy_period(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        engine._backoff_delays["web"] = 80
        engine._healthy_since["web"] = ("a" * 64, datetime.now(UTC) - timedelta(seconds=1000))

        await engine._check_single_container(container)  # fails 79s in, say

        assert "web" not in engine._healthy_since
        assert engine._backoff_delays["web"] == 80

    async def test_recreated_container_starts_a_new_healthy_period(self, engine, docker_client):
        container, info = make_container(name="web", container_id="c" * 64)
        docker_client.add_container(container, info)
        engine._backoff_delays["web"] = 80
        engine._healthy_since["web"] = ("a" * 64, datetime.now(UTC) - timedelta(seconds=1000))

        await engine._check_single_container(container)

        assert engine._backoff_delays["web"] == 80
        assert engine._healthy_since["web"][0] == "c" * 64

    async def test_healthy_period_is_forgotten_when_the_container_disappears(
        self, engine, docker_client
    ):
        other, other_info = make_container(name="db", container_id="b" * 64)
        docker_client.add_container(other, other_info)
        now = datetime.now(UTC)
        engine._healthy_since.update({"web": ("a" * 64, now), "db": ("b" * 64, now)})

        await engine._check_containers()

        assert "web" not in engine._healthy_since
        assert "db" in engine._healthy_since

    async def test_healthy_period_is_forgotten_when_the_container_is_no_longer_monitored(
        self, engine, docker_client, update_config
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._healthy_since["web"] = ("a" * 64, datetime.now(UTC))
        update_config(lambda c: c.containers.excluded.append("web"))

        await engine._check_single_container(container)

        assert "web" not in engine._healthy_since

    async def test_cleanly_stopped_container_does_not_reset_backoff(self, engine, docker_client):
        """Not restarting a manual stop is not the same as the container having recovered."""
        container, info = make_container(name="web", status="exited", exit_code=0)
        docker_client.add_container(container, info)
        engine._backoff_delays["web"] = 80
        engine._healthy_since["web"] = ("a" * 64, datetime.now(UTC) - timedelta(seconds=1000))

        await engine._check_single_container(container)

        assert engine._backoff_delays["web"] == 80
        assert "web" not in engine._healthy_since

    async def test_healthy_container_does_not_reset_another_containers_backoff(
        self, engine, docker_client
    ):
        healthy, healthy_info = make_container(name="web")
        failing, failing_info = make_container(
            name="db", container_id="b" * 64, status="exited", exit_code=1
        )
        docker_client.add_container(healthy, healthy_info)
        docker_client.add_container(failing, failing_info)
        long_ago = datetime.now(UTC) - timedelta(seconds=1000)
        engine._backoff_delays.update({"web": 80, "db": 80})
        engine._healthy_since.update({"web": ("a" * 64, long_ago), "db": ("b" * 64, long_ago)})
        await engine._check_single_container(failing)  # db waits out a backoff

        await engine._check_single_container(healthy)

        assert engine._backoff_delays["web"] == 10
        assert engine._backoff_delays["db"] == 80
        assert "db" in engine._next_allowed_restart

    async def test_backoff_grows_while_restarts_keep_failing(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        update_config(lambda c: setattr(c.restart, "max_restarts", 10))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        delays = []
        for _ in range(3):
            await engine._handle_container_restart(container, info, "unhealthy")
            delays.append(scheduled_delay(engine, "web"))
            elapse_backoff(engine, "web")
            await engine._handle_container_restart(container, info, "unhealthy")

        assert delays == pytest.approx([10, 20, 40], abs=1)
        assert docker_client.restart_calls == ["web"] * 3
        assert engine._backoff_delays["web"] == 80

    async def test_backoff_multiplier_is_configurable(self, engine, docker_client, update_config):
        def _configure(config):
            config.restart.cooldown_seconds = 0
            config.restart.backoff.initial_seconds = 5
            config.restart.backoff.multiplier = 3.0

        update_config(_configure)
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        delays = []
        for _ in range(2):
            await engine._handle_container_restart(container, info, "unhealthy")
            delays.append(scheduled_delay(engine, "web"))
            elapse_backoff(engine, "web")
            await engine._handle_container_restart(container, info, "unhealthy")

        assert delays == pytest.approx([5, 15], abs=1)

    async def test_backoff_is_skipped_when_disabled(
        self, engine, docker_client, recorded_sleeps, update_config
    ):
        update_config(lambda c: setattr(c.restart.backoff, "enabled", False))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert recorded_sleeps == []
        assert docker_client.restart_calls == ["web"]

    async def test_no_backoff_wait_is_scheduled_when_container_is_quarantined(
        self, engine, docker_client
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is True
        assert docker_client.restart_calls == []
        assert engine._next_allowed_restart == {}
        assert engine._restart_wait_owner == {}


@pytest.mark.asyncio
class TestBackoffDoesNotStallMonitoring:
    """Issue #434: a container waiting out its backoff must not block the cycle."""

    async def test_cycle_is_not_stalled_by_a_failing_containers_backoff(
        self, engine, docker_client, monkeypatch
    ):
        """
        Any ``asyncio.sleep`` here blocks forever, so a cycle that sleeps through a
        container's backoff never finishes and the timeout fails the test.
        """
        failing, failing_info = make_container(
            name="db", container_id="a" * 64, status="exited", exit_code=1
        )
        other, other_info = make_container(
            name="api", container_id="b" * 64, status="exited", exit_code=1
        )
        docker_client.add_container(failing, failing_info)
        docker_client.add_container(other, other_info)

        async def blocked_forever(*_args, **_kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(asyncio, "sleep", blocked_forever)
        evaluated: list[str] = []
        real_evaluate = engine._evaluate_container_health

        async def spy(container, info):
            evaluated.append(container.name)
            return await real_evaluate(container, info)

        monkeypatch.setattr(engine, "_evaluate_container_health", spy)

        await asyncio.wait_for(engine._check_containers(), timeout=5)

        assert evaluated == ["db", "api"]  # "api" was reached in the same cycle
        assert docker_client.restart_calls == []  # both are still waiting out their backoff
        assert set(engine._next_allowed_restart) == {"db", "api"}

        # Once the waits have run out, the next cycle restarts both.
        elapse_backoff(engine, "db")
        elapse_backoff(engine, "api")
        await asyncio.wait_for(engine._check_containers(), timeout=5)

        assert docker_client.restart_calls == ["db", "api"]
        assert engine._next_allowed_restart == {}
        assert engine._restart_wait_owner == {}


@pytest.mark.asyncio
class TestAbandonedRestartWait:
    """A pending restart wait must not outlive the container that started it."""

    @staticmethod
    def _assert_consistent(engine):
        assert set(engine._next_allowed_restart) == set(engine._restart_wait_owner)

    async def test_wait_is_dropped_when_its_container_disappears(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        bystander, bystander_info = make_container(name="db", container_id="d" * 64)
        docker_client.add_container(container, info)
        docker_client.add_container(bystander, bystander_info)
        await engine._check_containers()
        assert "web" in engine._next_allowed_restart

        docker_client.remove_container(container)
        await engine._check_containers()

        assert engine._next_allowed_restart == {}
        assert engine._restart_wait_owner == {}
        assert docker_client.restart_calls == []

    async def test_wait_is_kept_while_its_container_is_still_listed(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_containers()
        deadline = engine._next_allowed_restart["web"]

        await engine._check_containers()

        assert engine._next_allowed_restart == {"web": deadline}
        self._assert_consistent(engine)

    async def test_wait_is_not_dropped_when_listing_fails(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_containers()
        docker_client.list_containers_error = RuntimeError("docker daemon unavailable")

        await engine._check_containers()

        assert "web" in engine._next_allowed_restart
        self._assert_consistent(engine)

    async def test_wait_is_not_dropped_when_listing_returns_nothing(
        self, engine, docker_client, monkeypatch
    ):
        """DockerClientWrapper.list_containers logs a failure and returns [], not an error."""
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_containers()
        deadline = engine._next_allowed_restart["web"]
        monkeypatch.setattr(docker_client, "list_containers", lambda all_containers=False: [])

        await engine._check_containers()

        assert engine._next_allowed_restart == {"web": deadline}
        self._assert_consistent(engine)

    async def test_wait_is_dropped_when_its_container_stops_being_monitored(
        self, engine, docker_client, update_config, caplog
    ):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_containers()
        assert "web" in engine._next_allowed_restart

        update_config(lambda c: c.containers.excluded.append("web"))
        await engine._check_containers()

        assert engine._next_allowed_restart == {}
        assert engine._restart_wait_owner == {}
        assert docker_client.restart_calls == []
        assert "Error checking container" not in caplog.text  # cleared without raising

        # Monitored again and still failing: it gets a fresh wait, not an instant restart.
        update_config(lambda c: c.containers.excluded.remove("web"))
        await engine._check_containers()

        assert docker_client.restart_calls == []
        assert scheduled_delay(engine, "web") == pytest.approx(10, abs=1)
        self._assert_consistent(engine)

    async def test_replacement_does_not_inherit_the_abandoned_deadline(self, engine, docker_client):
        """
        A recreated container has the same name and recovery ID but a new ID. Its
        predecessor's wait, even one that has already run out, is not the new
        container's: it must wait for itself. Restart history is kept regardless.
        """
        old, old_info = make_container(
            name="web", container_id="a" * 64, status="exited", exit_code=1
        )
        docker_client.add_container(old, old_info)
        config_manager.record_restart("web")
        engine._backoff_delays["web"] = 40
        last_restart = datetime.now(UTC) - timedelta(hours=1)
        engine._last_restart_times["web"] = last_restart
        await engine._check_containers()
        elapse_backoff(engine, "web")  # the predecessor's deadline has run out

        docker_client.remove_container(old)
        new, new_info = make_container(
            name="web", container_id="b" * 64, status="exited", exit_code=1
        )
        docker_client.add_container(new, new_info)
        await engine._check_containers()

        assert docker_client.restart_calls == []  # it did not restart straight away
        assert scheduled_delay(engine, "web") == pytest.approx(40, abs=1)  # escalation kept
        assert engine._restart_wait_owner == {"web": new.id}
        assert config_manager.get_total_restart_count("web") == 1  # history kept
        assert engine._last_restart_times["web"] == last_restart  # cooldown history kept
        self._assert_consistent(engine)

        elapse_backoff(engine, "web")
        await engine._check_containers()

        assert docker_client.restart_calls == ["web"]
        assert config_manager.get_total_restart_count("web") == 2


@pytest.mark.asyncio
class TestQuarantineAlerts:
    """Webhook alerting on quarantine."""

    async def test_alert_is_posted_when_a_webhook_is_configured(
        self, engine, docker_client, update_config, monkeypatch
    ):
        posted = {}

        def fake_post(url, json=None, timeout=None):
            posted["url"] = url
            posted["json"] = json
            response = type("Response", (), {"status_code": 200})
            return response()

        monkeypatch.setattr("requests.post", fake_post)
        update_config(lambda c: setattr(c.alerts, "webhook", "http://alerts.invalid/hook"))

        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert posted["url"] == "http://alerts.invalid/hook"
        assert posted["json"]["event_type"] == "quarantine"

    async def test_alert_failure_does_not_break_quarantine(
        self, engine, docker_client, update_config, monkeypatch
    ):
        def fake_post(*args, **kwargs):
            raise RuntimeError("webhook unreachable")

        monkeypatch.setattr("requests.post", fake_post)
        update_config(lambda c: setattr(c.alerts, "webhook", "http://alerts.invalid/hook"))

        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is True

    async def test_no_alert_when_alerts_disabled(
        self, engine, docker_client, update_config, monkeypatch
    ):
        calls = []
        monkeypatch.setattr("requests.post", lambda *a, **k: calls.append(a))

        def _configure(config):
            config.alerts.enabled = False
            config.alerts.webhook = "http://alerts.invalid/hook"

        update_config(_configure)

        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert calls == []
        assert config_manager.is_quarantined("web") is True


@pytest.mark.asyncio
class TestAlertResponseHandling:
    """Non-success responses from the alert webhook."""

    async def test_non_200_response_does_not_break_quarantine(
        self, engine, docker_client, update_config, monkeypatch
    ):
        def fake_post(url, json=None, timeout=None):
            return type("Response", (), {"status_code": 500})()

        monkeypatch.setattr("requests.post", fake_post)
        update_config(lambda c: setattr(c.alerts, "webhook", "http://alerts.invalid/hook"))

        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.is_quarantined("web") is True
        assert len(events_of_type("quarantine")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("missing", "labels"), INCOMPLETE_INFO_CASES)
async def test_restart_is_skipped_when_container_info_lacks_identifiers(
    engine, docker_client, caplog, missing, labels
):
    """Incomplete info must not restart a container or record state under a missing key."""
    container, info = make_container(name="web", labels=labels)
    del info[missing]
    docker_client.add_container(container, info)

    with caplog.at_level("WARNING"):
        await engine._handle_container_restart(container, info, "Container exited with code 1")

    assert docker_client.restart_calls == []
    assert config_manager.get_config().containers.restart_counts == {}
    assert config_manager.get_events() == []
    # Logs the name, or the ID when the name is what is missing
    logged = info["full_id"] if missing == "name" else info["name"]
    assert [r.getMessage() for r in caplog.records] == [
        "Not restarting container with incomplete identifiers: " + logged
    ]


@pytest.mark.asyncio
class TestStaleRestartWait:
    """
    A wait is only kept while its owner is seen failing every cycle (#15).

    After a gap (quarantine, maintenance mode, an unavailable Docker daemon) the failure
    was not observed continuously, so the next failure starts a fresh wait instead of
    restarting at once on a deadline that ran out long ago. The stale wait does not
    escalate the backoff.
    """

    @staticmethod
    def _failing_web(docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        return container

    @staticmethod
    def _assert_fresh_wait(engine, docker_client):
        assert docker_client.restart_calls == []
        assert scheduled_delay(engine, "web") == pytest.approx(10, abs=1)
        assert engine._backoff_delays == {}  # the stale wait was not consumed

    async def test_wait_is_kept_while_failures_are_observed_every_cycle(
        self, engine, docker_client
    ):
        self._failing_web(docker_client)
        await engine._check_containers()
        deadline = engine._next_allowed_restart["web"]

        await engine._check_containers()
        assert engine._next_allowed_restart == {"web": deadline}
        assert docker_client.restart_calls == []

        elapse_backoff(engine, "web")
        await engine._check_containers()
        assert docker_client.restart_calls == ["web"]

    async def test_unquarantine_after_a_quarantine_starts_a_fresh_wait(self, engine, docker_client):
        self._failing_web(docker_client)
        await engine._check_containers()  # schedules the wait

        config_manager.quarantine_container("web")  # e.g. max_restarts was lowered
        await engine._check_containers()
        await engine._check_containers()
        config_manager.unquarantine_container("web")
        elapse_backoff(engine, "web")
        await engine._check_containers()

        self._assert_fresh_wait(engine, docker_client)

    async def test_maintenance_mode_gap_starts_a_fresh_wait(self, engine, docker_client):
        self._failing_web(docker_client)
        await engine._check_containers()

        config_manager.enable_maintenance_mode()
        await engine._check_containers()
        config_manager.disable_maintenance_mode()
        elapse_backoff(engine, "web")
        await engine._check_containers()

        self._assert_fresh_wait(engine, docker_client)

    async def test_failed_listing_gap_starts_a_fresh_wait(self, engine, docker_client):
        self._failing_web(docker_client)
        await engine._check_containers()

        docker_client.list_containers_error = RuntimeError("docker daemon unavailable")
        await engine._check_containers()
        docker_client.list_containers_error = None
        elapse_backoff(engine, "web")
        await engine._check_containers()

        self._assert_fresh_wait(engine, docker_client)

    async def test_empty_listing_gap_starts_a_fresh_wait(self, engine, docker_client, monkeypatch):
        container = self._failing_web(docker_client)
        await engine._check_containers()

        with monkeypatch.context() as patched:
            patched.setattr(docker_client, "list_containers", lambda all_containers=False: [])
            await engine._check_containers()
        assert container in docker_client.list_containers(all_containers=True)
        elapse_backoff(engine, "web")
        await engine._check_containers()

        self._assert_fresh_wait(engine, docker_client)

    async def test_fresh_wait_after_a_gap_keeps_the_escalated_delay(self, engine, docker_client):
        self._failing_web(docker_client)
        engine._backoff_delays["web"] = 40
        await engine._check_containers()

        config_manager.enable_maintenance_mode()
        await engine._check_containers()
        config_manager.disable_maintenance_mode()
        elapse_backoff(engine, "web")
        await engine._check_containers()

        assert docker_client.restart_calls == []
        assert scheduled_delay(engine, "web") == pytest.approx(40, abs=1)
        assert engine._backoff_delays == {"web": 40}  # escalation kept, not advanced

    async def test_stale_wait_is_replaced_and_owned_by_the_current_container(
        self, engine, docker_client
    ):
        container = self._failing_web(docker_client)
        await engine._check_containers()
        config_manager.enable_maintenance_mode()
        await engine._check_containers()
        config_manager.disable_maintenance_mode()

        await engine._check_containers()

        assert engine._restart_wait_owner == {"web": container.id}
        assert set(engine._restart_wait_seen) == set(engine._next_allowed_restart) == {"web"}
        assert engine._restart_wait_seen["web"] == engine._check_cycle

    async def test_clearing_a_wait_forgets_when_it_was_last_seen(self, engine, docker_client):
        container, info = make_container(name="web", status="exited", exit_code=1)
        docker_client.add_container(container, info)
        await engine._check_containers()
        assert engine._restart_wait_seen

        docker_client.remove_container(container)
        bystander, bystander_info = make_container(name="db", container_id="d" * 64)
        docker_client.add_container(bystander, bystander_info)
        await engine._check_containers()

        assert engine._restart_wait_seen == {}
