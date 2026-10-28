"""
In-memory restart and backoff state for the monitoring engine

``RecoveryPolicy`` is synchronous and does not touch Docker, the configuration manager or
notifications. The engine passes in the configuration snapshot it is already working with,
so a decision never mixes two configurations, and the policy's clock can be replaced in tests.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.config.config_manager import RestartConfig

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """The current time in UTC, the policy's default clock"""
    return datetime.now(UTC)


class RecoveryPolicy:
    """
    Cooldown, restart backoff and healthy-run state, keyed by recovery identifier

    Restart waits and healthy runs also record the container (by Docker ID) they belong
    to, because replicas can share a recovery ID and a recreated container gets a new ID.
    """

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        """
        Initialize empty recovery state

        Args:
            clock: Returns the current time; timezone-aware UTC
        """
        self._clock = clock
        self.last_restart_times: dict[str, datetime] = {}
        self.backoff_delays: dict[str, int] = {}
        # Per recovery ID: the container (by Docker ID) and when its current unbroken run
        # of healthy evaluations began. A recreated container starts a new run.
        self.healthy_since: dict[str, tuple[str | None, datetime]] = {}
        self.next_allowed_restart: dict[str, datetime] = {}
        # The container (by Docker ID) whose failure started each pending wait. Replicas
        # sharing a recovery ID share the wait, so only its owner recovering may cancel
        # it. A recreated container has a new ID, so it never inherits a predecessor's wait.
        self.restart_wait_owner: dict[str, str | None] = {}
        # The cycle in which the owner last confirmed each pending wait by failing again.
        # A wait the owner did not confirm in the previous cycle (it was quarantined, in
        # maintenance, or Docker was unavailable) is stale: the failure was not observed
        # continuously, so the next failure starts a fresh wait instead of using it.
        self.restart_wait_seen: dict[str, int] = {}
        # Counts monitoring cycles. A quarantined container's healthy checks are consecutive
        # only if each happened in the cycle after the previous one, so a skipped or failed
        # check, or a failed cycle, breaks the streak without any explicit reset.
        self._check_cycle = 0

    @property
    def check_cycle(self) -> int:
        """The number of monitoring cycles begun so far"""
        return self._check_cycle

    def begin_cycle(self) -> None:
        """Count the start of a monitoring cycle"""
        self._check_cycle += 1

    def forget_absent(self, listed_ids: set[str | None]) -> None:
        """
        Forget the restart waits and healthy runs of containers Docker no longer lists

        Args:
            listed_ids: Docker IDs of every container Docker listed this cycle. Only
                call this with a non-empty listing: an empty one may be a failed call.
        """
        abandoned = [
            recovery_id
            for recovery_id, owner in self.restart_wait_owner.items()
            if owner not in listed_ids
        ]
        for recovery_id in abandoned:
            self.clear_restart_wait(recovery_id)
        gone = [
            recovery_id
            for recovery_id, (owner, _) in self.healthy_since.items()
            if owner not in listed_ids
        ]
        for recovery_id in gone:
            del self.healthy_since[recovery_id]

    def forget_container(self, container_id: str | None) -> None:
        """Forget every restart wait and healthy run the given container (by Docker ID) has"""
        owned_waits = [
            recovery_id
            for recovery_id, owner in self.restart_wait_owner.items()
            if owner == container_id
        ]
        for recovery_id in owned_waits:
            self.clear_restart_wait(recovery_id)
        owned_runs = [
            recovery_id
            for recovery_id, (owner, _) in self.healthy_since.items()
            if owner == container_id
        ]
        for recovery_id in owned_runs:
            del self.healthy_since[recovery_id]

    def note_unhealthy(self, recovery_id: str) -> None:
        """End the healthy run of a container that needs restarting"""
        self.healthy_since.pop(recovery_id, None)

    def note_healthy(
        self,
        recovery_id: str,
        container_id: str | None,
        running: bool,
        restart: RestartConfig,
    ) -> None:
        """
        Update restart state for a container that was evaluated as healthy

        Args:
            recovery_id: Recovery identifier the state is recorded under
            container_id: Docker ID of the container
            running: Whether Docker reports the container as running
            restart: Restart configuration snapshot
        """
        # Recovered on its own: drop the restart it was waiting out its backoff for
        self.cancel_restart_wait(recovery_id, container_id)
        self._reset_backoff_if_stable(recovery_id, container_id, running, restart)

    def _reset_backoff_if_stable(
        self,
        recovery_id: str,
        container_id: str | None,
        running: bool,
        restart: RestartConfig,
    ) -> None:
        """
        Reset a container's restart backoff once it has stayed healthy for long enough

        A restarted container is briefly running and healthy even if it is crash-looping, so
        a healthy evaluation alone is not a recovery. The container must have been running
        and healthy, without a failed evaluation in between, for at least the delay it would
        wait before its next restart.

        Args:
            recovery_id: Recovery identifier the backoff is recorded under
            container_id: Docker ID of the container the healthy run belongs to
            running: Whether Docker reports the container as running
            restart: Restart configuration snapshot
        """
        if not running:
            self.healthy_since.pop(recovery_id, None)
            return
        now = self._clock()
        owner, healthy_since = self.healthy_since.get(recovery_id, (None, now))
        if owner != container_id:
            healthy_since = now
        self.healthy_since[recovery_id] = (container_id, healthy_since)
        delay = self.backoff_delays.get(recovery_id)
        if delay is None or (now - healthy_since).total_seconds() < delay:
            return
        self.backoff_delays[recovery_id] = restart.backoff.initial_seconds
        del self.healthy_since[recovery_id]

    def seconds_into_cooldown(self, recovery_id: str, cooldown_seconds: int) -> float | None:
        """
        Seconds since the last restart, if the cooldown after it has not run out

        Args:
            recovery_id: Recovery identifier the last restart is recorded under
            cooldown_seconds: Configured cooldown between restarts

        Returns:
            The seconds elapsed while still in cooldown, or None if a restart may go ahead
        """
        last_restart = self.last_restart_times.get(recovery_id)
        if last_restart:
            elapsed = (self._clock() - last_restart).total_seconds()
            if elapsed < cooldown_seconds:
                return elapsed
        return None

    def restart_wait_elapsed(
        self,
        recovery_id: str,
        container_id: str | None,
        container_name: str | None,
        restart: RestartConfig,
    ) -> bool:
        """
        Apply the restart backoff for a container that needs restarting

        The wait is recorded as a timestamp and checked on later cycles, never slept
        inline, so one container's backoff cannot stall the monitoring of the others.

        Args:
            recovery_id: Recovery identifier the wait is recorded under
            container_id: Docker ID of the container, recorded as the owner of a new wait
            container_name: Container name, for logging
            restart: Restart configuration snapshot

        Returns:
            True if the restart may go ahead now. False if a wait was just scheduled
            or the existing one has not run out yet.
        """
        now = self._clock()
        next_allowed = self.next_allowed_restart.get(recovery_id)
        if next_allowed is not None:
            if self.restart_wait_seen[recovery_id] < self._check_cycle - 1:
                logger.debug(
                    "Restart wait for %s (recovery_id: %s) was not confirmed last cycle, "
                    "starting a new one",
                    container_name,
                    recovery_id,
                )
                self.clear_restart_wait(recovery_id)
                next_allowed = None
            elif self.restart_wait_owner.get(recovery_id) == container_id:
                self.restart_wait_seen[recovery_id] = self._check_cycle
        backoff_delay = min(
            self.backoff_delays.get(recovery_id, restart.backoff.initial_seconds),
            restart.backoff.max_seconds,
        )
        if next_allowed is None:
            logger.debug(
                "Applying backoff delay of %ss for %s (recovery_id: %s)",
                backoff_delay,
                container_name,
                recovery_id,
            )
            self.next_allowed_restart[recovery_id] = now + timedelta(seconds=backoff_delay)
            self.restart_wait_owner[recovery_id] = container_id
            self.restart_wait_seen[recovery_id] = self._check_cycle
            return False
        if now < next_allowed:
            logger.debug(
                "Container %s (recovery_id: %s) waiting out restart backoff (%.1fs left)",
                container_name,
                recovery_id,
                (next_allowed - now).total_seconds(),
            )
            return False

        # Update backoff for next time
        next_backoff = min(
            int(backoff_delay * restart.backoff.multiplier),
            restart.backoff.max_seconds,
        )
        self.backoff_delays[recovery_id] = next_backoff
        return True

    def cancel_restart_wait(self, recovery_id: str, container_id: str | None) -> None:
        """
        Forget a recovery ID's restart wait if the given container (by Docker ID) started it

        A wait started by another replica sharing the recovery ID is kept.
        """
        if self.restart_wait_owner.get(recovery_id) == container_id:
            self.clear_restart_wait(recovery_id)

    def clear_restart_wait(self, recovery_id: str) -> None:
        """Forget the restart wait recorded for a recovery ID, and who it belongs to"""
        self.next_allowed_restart.pop(recovery_id, None)
        self.restart_wait_owner.pop(recovery_id, None)
        self.restart_wait_seen.pop(recovery_id, None)

    def record_restart(self, recovery_id: str) -> None:
        """Start the cooldown after a restart attempt, whether or not it succeeded"""
        self.last_restart_times[recovery_id] = self._clock()
