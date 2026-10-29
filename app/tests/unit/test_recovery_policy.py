"""
Unit tests for ``app.monitor.recovery.RecoveryPolicy``.

The policy is synchronous and takes its clock and configuration as arguments, so these tests
drive it directly with a fake clock: no engine, Docker client or configuration manager.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.config.config_manager import BackoffConfig, RestartConfig
from app.monitor.recovery import (
    QUARANTINE_STABLE_CHECKS,
    RecoveryPolicy,
    uptime_seconds,
    utc_now,
)

OWNER = "a" * 64
SIBLING = "b" * 64
START = datetime(2026, 1, 1, tzinfo=UTC)


class FakeClock:
    """A clock that only moves when the test advances it"""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def policy(clock: FakeClock) -> RecoveryPolicy:
    return RecoveryPolicy(clock)


def restart_config(initial: int = 10, multiplier: float = 2.0, maximum: int = 300) -> RestartConfig:
    return RestartConfig(
        backoff=BackoffConfig(initial_seconds=initial, multiplier=multiplier, max_seconds=maximum)
    )


def wait_elapsed(policy: RecoveryPolicy, container_id: str = OWNER, **config) -> bool:
    return policy.restart_wait_elapsed("web", container_id, "web-1", restart_config(**config))


def test_default_clock_is_utc_now():
    before = datetime.now(UTC)
    assert before <= utc_now() <= datetime.now(UTC)
    assert utc_now().tzinfo is UTC
    assert RecoveryPolicy()._clock is utc_now


class TestCycle:
    def test_starts_at_zero_and_counts_each_cycle(self, policy):
        assert policy.check_cycle == 0
        policy.begin_cycle()
        policy.begin_cycle()
        assert policy.check_cycle == 2


class TestCooldown:
    def test_no_restart_means_no_cooldown(self, policy):
        assert policy.seconds_into_cooldown("web", 60) is None

    def test_reports_elapsed_seconds_inside_the_cooldown(self, policy, clock):
        policy.record_restart("web")
        assert policy.last_restart_times == {"web": START}
        clock.advance(59.5)
        assert policy.seconds_into_cooldown("web", 60) == 59.5

    def test_reports_zero_right_after_a_restart(self, policy):
        policy.record_restart("web")
        assert policy.seconds_into_cooldown("web", 60) == 0.0

    def test_ends_once_the_cooldown_has_run(self, policy, clock):
        policy.record_restart("web")
        clock.advance(60)
        assert policy.seconds_into_cooldown("web", 60) is None

    def test_zero_cooldown_never_blocks(self, policy):
        policy.record_restart("web")
        assert policy.seconds_into_cooldown("web", 0) is None

    def test_is_tracked_per_recovery_id(self, policy):
        policy.record_restart("web")
        assert policy.seconds_into_cooldown("db", 60) is None

    def test_record_restart_moves_the_cooldown_on(self, policy, clock):
        policy.record_restart("web")
        clock.advance(100)
        policy.record_restart("web")
        assert policy.last_restart_times == {"web": START + timedelta(seconds=100)}
        assert policy.seconds_into_cooldown("web", 60) == 0.0


class TestBackoff:
    def test_first_failure_schedules_a_wait_owned_by_the_container(self, policy):
        policy.begin_cycle()
        assert wait_elapsed(policy) is False
        assert policy.next_allowed_restart == {"web": START + timedelta(seconds=10)}
        assert policy.restart_wait_owner == {"web": OWNER}
        assert policy.restart_wait_seen == {"web": 1}
        assert policy.backoff_delays == {}

    def test_restart_waits_until_the_deadline(self, policy, clock):
        wait_elapsed(policy)
        clock.advance(9.9)
        assert wait_elapsed(policy) is False
        assert policy.next_allowed_restart == {"web": START + timedelta(seconds=10)}

    def test_restart_goes_ahead_at_the_deadline_and_escalates(self, policy, clock):
        wait_elapsed(policy)
        clock.advance(10)
        assert wait_elapsed(policy) is True
        assert policy.backoff_delays == {"web": 20}
        # The caller clears the wait before restarting
        assert "web" in policy.next_allowed_restart

    def test_escalated_delay_is_used_for_the_next_wait(self, policy, clock):
        policy.backoff_delays["web"] = 40
        wait_elapsed(policy)
        assert policy.next_allowed_restart["web"] == START + timedelta(seconds=40)
        clock.advance(40)
        assert wait_elapsed(policy) is True
        assert policy.backoff_delays["web"] == 80

    def test_escalation_truncates_to_whole_seconds(self, policy, clock):
        wait_elapsed(policy, multiplier=1.5, initial=5)
        clock.advance(5)
        assert wait_elapsed(policy, multiplier=1.5, initial=5) is True
        assert policy.backoff_delays["web"] == 7

    def test_escalation_is_capped_at_the_maximum(self, policy, clock):
        policy.backoff_delays["web"] = 200
        wait_elapsed(policy, maximum=300)
        clock.advance(200)
        assert wait_elapsed(policy, maximum=300) is True
        assert policy.backoff_delays["web"] == 300

    def test_a_delay_above_a_lowered_maximum_is_capped(self, policy, clock):
        policy.backoff_delays["web"] = 300
        wait_elapsed(policy, maximum=50)
        assert policy.next_allowed_restart["web"] == START + timedelta(seconds=50)
        clock.advance(50)
        assert wait_elapsed(policy, maximum=50) is True
        assert policy.backoff_delays["web"] == 50

    def test_waits_are_per_recovery_id(self, policy):
        wait_elapsed(policy)
        policy.restart_wait_elapsed("db", SIBLING, "db-1", restart_config())
        assert set(policy.next_allowed_restart) == {"web", "db"}
        assert policy.restart_wait_owner == {"web": OWNER, "db": SIBLING}


class TestStaleWait:
    def test_a_wait_confirmed_in_the_previous_cycle_is_kept(self, policy, clock):
        policy.begin_cycle()
        wait_elapsed(policy)
        policy.begin_cycle()
        clock.advance(10)
        assert wait_elapsed(policy) is True
        assert policy.restart_wait_seen == {"web": 2}

    def test_a_wait_not_confirmed_last_cycle_starts_again(self, policy, clock, caplog):
        policy.begin_cycle()
        wait_elapsed(policy)
        policy.begin_cycle()
        policy.begin_cycle()
        clock.advance(10)
        with caplog.at_level(logging.DEBUG, logger="app.monitor.recovery"):
            assert wait_elapsed(policy) is False
        assert policy.next_allowed_restart == {"web": START + timedelta(seconds=20)}
        assert policy.restart_wait_seen == {"web": 3}
        assert policy.restart_wait_owner == {"web": OWNER}
        assert policy.backoff_delays == {}  # the stale wait was not consumed
        assert (
            "Restart wait for web-1 (recovery_id: web) was not confirmed last cycle, "
            "starting a new one"
        ) in caplog.messages

    def test_a_stale_wait_is_taken_over_by_the_container_now_failing(self, policy):
        policy.begin_cycle()
        wait_elapsed(policy)
        policy.begin_cycle()
        policy.begin_cycle()
        assert wait_elapsed(policy, container_id=SIBLING) is False
        assert policy.restart_wait_owner == {"web": SIBLING}


class TestOwnerGating:
    def test_only_the_owner_confirms_a_pending_wait(self, policy):
        policy.begin_cycle()
        wait_elapsed(policy)
        policy.begin_cycle()
        assert wait_elapsed(policy, container_id=SIBLING) is False
        assert policy.restart_wait_seen == {"web": 1}
        assert policy.restart_wait_owner == {"web": OWNER}
        assert wait_elapsed(policy) is False
        assert policy.restart_wait_seen == {"web": 2}

    def test_cancel_by_the_owner_clears_the_wait(self, policy):
        wait_elapsed(policy)
        policy.cancel_restart_wait("web", OWNER)
        assert policy.next_allowed_restart == {}
        assert policy.restart_wait_owner == {}
        assert policy.restart_wait_seen == {}

    def test_cancel_by_another_container_keeps_the_wait(self, policy):
        wait_elapsed(policy)
        policy.cancel_restart_wait("web", SIBLING)
        assert policy.restart_wait_owner == {"web": OWNER}
        assert set(policy.next_allowed_restart) == set(policy.restart_wait_seen) == {"web"}

    def test_clear_drops_the_wait_whoever_owns_it(self, policy):
        wait_elapsed(policy)
        policy.clear_restart_wait("web")
        policy.clear_restart_wait("missing")
        assert policy.next_allowed_restart == {}
        assert policy.restart_wait_owner == {}
        assert policy.restart_wait_seen == {}


class TestSweeps:
    def test_forget_absent_drops_waits_and_runs_of_unlisted_containers(self, policy, clock):
        wait_elapsed(policy)
        policy.restart_wait_elapsed("db", SIBLING, "db-1", restart_config())
        policy.healthy_since.update({"api": (OWNER, START), "cache": (SIBLING, START)})

        policy.forget_absent({SIBLING})

        assert policy.restart_wait_owner == {"db": SIBLING}
        assert set(policy.next_allowed_restart) == set(policy.restart_wait_seen) == {"db"}
        assert policy.healthy_since == {"cache": (SIBLING, START)}

    def test_forget_container_drops_only_what_it_owns(self, policy):
        wait_elapsed(policy)
        policy.restart_wait_elapsed("db", SIBLING, "db-1", restart_config())
        policy.healthy_since.update({"api": (OWNER, START), "cache": (SIBLING, START)})
        policy.backoff_delays["web"] = 40
        policy.record_restart("web")

        policy.forget_container(OWNER)

        assert policy.restart_wait_owner == {"db": SIBLING}
        assert set(policy.next_allowed_restart) == set(policy.restart_wait_seen) == {"db"}
        assert policy.healthy_since == {"cache": (SIBLING, START)}
        assert policy.backoff_delays == {"web": 40}  # cooldown and backoff are kept
        assert policy.last_restart_times == {"web": START}


class TestHealthyRun:
    def test_note_unhealthy_ends_the_run(self, policy):
        policy.healthy_since["web"] = (OWNER, START)
        policy.note_unhealthy("web")
        policy.note_unhealthy("missing")
        assert policy.healthy_since == {}

    def test_a_healthy_check_starts_a_run(self, policy):
        policy.note_healthy("web", OWNER, True, restart_config())
        assert policy.healthy_since == {"web": (OWNER, START)}

    def test_a_continuing_run_keeps_its_start(self, policy, clock):
        policy.note_healthy("web", OWNER, True, restart_config())
        clock.advance(5)
        policy.note_healthy("web", OWNER, True, restart_config())
        assert policy.healthy_since == {"web": (OWNER, START)}

    def test_a_new_container_starts_a_new_run(self, policy, clock):
        policy.backoff_delays["web"] = 80
        policy.healthy_since["web"] = (OWNER, START)
        clock.advance(1000)
        policy.note_healthy("web", SIBLING, True, restart_config())
        assert policy.healthy_since == {"web": (SIBLING, clock.now)}
        assert policy.backoff_delays == {"web": 80}

    def test_not_running_ends_the_run(self, policy):
        policy.healthy_since["web"] = (OWNER, START)
        policy.note_healthy("web", OWNER, False, restart_config())
        assert policy.healthy_since == {}

    def test_not_running_without_a_run_records_nothing(self, policy):
        policy.note_healthy("web", OWNER, False, restart_config())
        assert policy.healthy_since == {}

    def test_backoff_resets_after_a_run_as_long_as_the_delay(self, policy, clock):
        policy.backoff_delays["web"] = 80
        policy.note_healthy("web", OWNER, True, restart_config(initial=10))
        clock.advance(79)
        policy.note_healthy("web", OWNER, True, restart_config(initial=10))
        assert policy.backoff_delays == {"web": 80}
        clock.advance(1)
        policy.note_healthy("web", OWNER, True, restart_config(initial=10))
        assert policy.backoff_delays == {"web": 10}
        assert policy.healthy_since == {}  # the next run starts from scratch

    def test_without_a_backoff_the_run_is_only_tracked(self, policy, clock):
        policy.note_healthy("web", OWNER, True, restart_config())
        clock.advance(10_000)
        policy.note_healthy("web", OWNER, True, restart_config())
        assert policy.backoff_delays == {}
        assert policy.healthy_since == {"web": (OWNER, START)}

    def test_recovering_cancels_its_own_wait(self, policy):
        wait_elapsed(policy)
        policy.note_healthy("web", OWNER, True, restart_config())
        assert policy.next_allowed_restart == {}
        assert policy.restart_wait_owner == {}

    def test_a_sibling_recovering_keeps_the_wait(self, policy):
        wait_elapsed(policy)
        policy.note_healthy("web", SIBLING, True, restart_config())
        assert policy.restart_wait_owner == {"web": OWNER}


class TestLogging:
    def test_scheduling_and_waiting_are_logged(self, policy, clock, caplog):
        with caplog.at_level(logging.DEBUG, logger="app.monitor.recovery"):
            wait_elapsed(policy)
            clock.advance(2.5)
            wait_elapsed(policy)
        assert caplog.messages == [
            "Applying backoff delay of 10s for web-1 (recovery_id: web)",
            "Container web-1 (recovery_id: web) waiting out restart backoff (7.5s left)",
        ]
        assert {record.name for record in caplog.records} == {"app.monitor.recovery"}


def started(at: datetime = START) -> str:
    """A Docker ``StartedAt`` timestamp"""
    return at.isoformat().replace("+00:00", "Z")


def running_info(started_at: str | None = None, **extra) -> dict:
    return {"started_at": started() if started_at is None else started_at, **extra}


def confirm(
    policy: RecoveryPolicy,
    info: dict | None = None,
    container_id: str = OWNER,
    mode: str = "on-failure",
    interval: int = 10,
) -> bool:
    return policy.quarantine_recovery_confirmed(
        container_id, running_info() if info is None else info, mode, interval
    )


class TestUptime:
    def test_seconds_since_a_docker_timestamp(self):
        now = START + timedelta(seconds=90)
        assert uptime_seconds(f"{started()[:-1]}.123456789Z", now) == pytest.approx(
            89.877, abs=1e-3
        )
        assert uptime_seconds(started(), now) == 90.0

    def test_a_naive_timestamp_is_utc(self):
        assert uptime_seconds("2026-01-01T00:00:00", START + timedelta(seconds=5)) == 5.0

    def test_an_offset_is_honoured(self):
        assert uptime_seconds("2026-01-01T02:00:00+02:00", START + timedelta(seconds=5)) == 5.0

    @pytest.mark.parametrize("started_at", ["", "not-a-date", "0001-01-01T00:00:00Z"])
    def test_unusable_timestamps(self, started_at):
        assert uptime_seconds(started_at, START) is None

    def test_year_two_is_a_real_start(self):
        assert uptime_seconds("0002-01-01T00:00:00Z", START) is not None


class TestQuarantineStreak:
    def test_needs_the_configured_number_of_consecutive_checks(self, policy, clock):
        clock.advance(1000)
        results = []
        for _ in range(QUARANTINE_STABLE_CHECKS):
            policy.begin_cycle()
            results.append(confirm(policy))
        assert results == [False] * (QUARANTINE_STABLE_CHECKS - 1) + [True]
        assert policy.quarantine_streaks == {
            OWNER: (started(), QUARANTINE_STABLE_CHECKS, QUARANTINE_STABLE_CHECKS)
        }

    def test_the_streak_records_the_cycle_it_was_last_seen(self, policy):
        policy.begin_cycle()
        policy.begin_cycle()
        confirm(policy)
        assert policy.quarantine_streaks == {OWNER: (started(), 1, 2)}

    def test_uptime_must_cover_that_many_intervals(self, policy, clock):
        for _ in range(QUARANTINE_STABLE_CHECKS):
            policy.begin_cycle()
            confirm(policy, interval=10)
        clock.advance(QUARANTINE_STABLE_CHECKS * 10 - 1)
        policy.begin_cycle()
        assert confirm(policy, interval=10) is False
        clock.advance(1)
        policy.begin_cycle()
        assert confirm(policy, interval=10) is True

    def test_a_gap_of_a_cycle_restarts_the_count(self, policy, clock):
        clock.advance(1000)
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            policy.begin_cycle()
            confirm(policy)
        policy.begin_cycle()  # not checked this cycle
        policy.begin_cycle()
        assert OWNER not in policy.quarantine_streaks
        assert confirm(policy) is False
        assert policy.quarantine_streaks[OWNER][1] == 1

    def test_a_new_run_restarts_the_count(self, policy, clock):
        clock.advance(1000)
        for _ in range(QUARANTINE_STABLE_CHECKS - 1):
            policy.begin_cycle()
            confirm(policy)
        restarted = started(START + timedelta(seconds=1))
        policy.begin_cycle()
        assert confirm(policy, running_info(restarted)) is False
        assert policy.quarantine_streaks == {OWNER: (restarted, 1, QUARANTINE_STABLE_CHECKS)}

    def test_streaks_are_per_container(self, policy):
        policy.begin_cycle()
        confirm(policy)
        confirm(policy, container_id=SIBLING)
        confirm(policy)
        assert policy.quarantine_streaks == {OWNER: (started(), 2, 1), SIBLING: (started(), 1, 1)}

    def test_state_started_at_is_the_fallback(self, policy):
        info = {"started_at": "", "state": {"StartedAt": started()}}
        confirm(policy, info)
        assert policy.quarantine_streaks == {OWNER: (started(), 1, 0)}

    @pytest.mark.parametrize("info", [{}, {"state": {}}, running_info("0001-01-01T00:00:00Z")])
    def test_without_a_usable_start_nothing_counts(self, policy, info):
        assert confirm(policy, info) is False
        assert policy.quarantine_streaks == {}

    @pytest.mark.parametrize("mode", ["health", "both"])
    def test_health_starting_is_not_healthy_in_health_modes(self, policy, mode):
        info = running_info(health={"status": "starting"})
        assert confirm(policy, info, mode=mode) is False
        assert policy.quarantine_streaks == {}

    @pytest.mark.parametrize(
        ("mode", "health"),
        [
            ("on-failure", {"status": "starting"}),
            ("health", {"status": "healthy"}),
            ("health", None),
            ("both", {}),
        ],
    )
    def test_other_health_states_count(self, policy, mode, health):
        confirm(policy, running_info(health=health), mode=mode)
        assert policy.quarantine_streaks[OWNER][1] == 1


class TestStreakPrune:
    def test_begin_cycle_ends_streaks_not_extended_last_cycle(self, policy):
        streaks = policy.quarantine_streaks
        streaks.update({OWNER: ("a", 1, 1), SIBLING: ("b", 2, 2), "c" * 64: ("c", 1, 0)})
        for _ in range(3):
            policy.begin_cycle()
        assert policy.check_cycle == 3
        assert policy.quarantine_streaks == {SIBLING: ("b", 2, 2)}
        assert policy.quarantine_streaks is streaks  # pruned in place

    def test_a_streak_from_this_cycle_is_kept(self, policy):
        policy.begin_cycle()
        policy.quarantine_streaks[OWNER] = ("a", 1, 1)
        policy.begin_cycle()
        assert policy.quarantine_streaks == {OWNER: ("a", 1, 1)}


class TestQuarantineRelease:
    def test_forgets_the_streak_and_resets_a_tracked_backoff(self, policy):
        policy.quarantine_streaks.update({OWNER: ("a", 2, 0), SIBLING: ("b", 1, 0)})
        policy.backoff_delays.update({"web": 160, "db": 40})
        policy.note_quarantine_released(OWNER, "web", lambda: 10)
        assert policy.quarantine_streaks == {SIBLING: ("b", 1, 0)}
        assert policy.backoff_delays == {"web": 10, "db": 40}

    def test_without_a_backoff_the_configuration_is_not_read(self, policy):
        def initial_backoff() -> int:
            raise AssertionError("read the configuration without a backoff to reset")

        policy.note_quarantine_released(OWNER, "web", initial_backoff)
        assert policy.backoff_delays == {}

    def test_cancels_its_own_wait(self, policy):
        wait_elapsed(policy)
        policy.note_quarantine_released(OWNER, "web", lambda: 10)
        assert policy.next_allowed_restart == {}
        assert policy.restart_wait_owner == {}
        assert policy.restart_wait_seen == {}

    def test_keeps_a_wait_started_by_a_sibling(self, policy):
        wait_elapsed(policy, container_id=SIBLING)
        policy.note_quarantine_released(OWNER, "web", lambda: 10)
        assert policy.restart_wait_owner == {"web": SIBLING}

    def test_a_failed_configuration_read_leaves_the_backoff(self, policy):
        wait_elapsed(policy)
        policy.quarantine_streaks[OWNER] = ("a", 2, 0)
        policy.backoff_delays["web"] = 160

        def initial_backoff() -> int:
            raise RuntimeError("config unavailable")

        with pytest.raises(RuntimeError, match="config unavailable"):
            policy.note_quarantine_released(OWNER, "web", initial_backoff)
        assert policy.quarantine_streaks == {}
        assert policy.restart_wait_owner == {}
        assert policy.backoff_delays == {"web": 160}
