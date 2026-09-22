"""
Integration test for the engine/API -> NotificationManager event-type contract
under the *shipped default* ``NotificationsConfig``.

``MonitoringEngine`` (and one API endpoint) emit ``AutoHealEvent`` values, and
``NotificationsConfig.event_filters`` plus ``NotificationManager``'s title map
decide what happens to them. The two sides are joined only by bare event-type
strings, and nothing else in the suite checks them against each other: engine
tests swap ``notification_manager`` for a ``MagicMock`` (see
``mock_notification_manager`` in ``conftest.py``), and
``test_notification_manager.py`` always supplies its own ``event_filters``.

These tests deliberately document *current* behaviour rather than desired
behaviour, including the known gaps (see #100 and its follow-up):

* ``health_check_failed`` sits in the default filter list but nothing ever
  emits it - a failed custom health check surfaces as ``restart``.
* ``auto_monitor`` and ``unquarantine`` are emitted but excluded by the default
  filters, so they are silently dropped out of the box.
* ``auto_unquarantine`` notifies by default but has no entry in
  ``_format_notification``'s ``title_map``, so it falls through to the generic
  title fallback.

Integration boundary: real ``MonitoringEngine`` and real
``NotificationManager``, wired together instead of one being mocked out. Only
the outbound HTTP session is faked, reusing ``_FakeSession`` from
``test_notification_manager.py``.

``unquarantine`` is emitted by ``app/api/api.py``, not by the engine, so it is
driven through that endpoint coroutine directly (the pattern
``test_api.py`` already uses - no HTTP client, no Docker daemon) rather than by
hand-building the event. Hand-building it would pin nothing: the whole point of
scenario 2 is to catch a future rename on either side of the contract, and a
locally constructed event can never drift from itself.
"""

import pytest

from app.api.api import unquarantine_container
from app.config.config_manager import NotificationService, config_manager
from app.notifications.notification_manager import NotificationManager
from app.tests.unit.conftest import make_container
from app.tests.unit.test_engine_lifecycle import start_event
from app.tests.unit.test_notification_manager import _FakeSession

WEBHOOK_URL = "https://example.invalid/default-contract"

# The shipped default, asserted rather than imported so that changing it is a
# deliberate act that breaks this test.
DEFAULT_EVENT_FILTERS = ["restart", "quarantine", "health_check_failed", "auto_unquarantine"]

RESTART_ID = "1" * 64
QUARANTINE_ID = "2" * 64
AUTO_UNQUARANTINE_ID = "3" * 64
AUTO_MONITOR_ID = "4" * 64
UNQUARANTINE_ID = "5" * 64


@pytest.fixture
def real_notification_manager(monkeypatch, docker_client) -> NotificationManager:
    """
    A real ``NotificationManager`` wired into both event producers.

    Overrides the autouse ``mock_notification_manager`` fixture for the engine
    and patches the API module's singleton, so events travel the real
    ``send_event_notification`` -> ``_should_notify_for_event`` ->
    ``_process_notification`` -> ``_format_notification`` path. Only
    ``_session`` is faked, so no outbound request is ever attempted.
    """
    manager = NotificationManager()
    manager._session = _FakeSession()
    monkeypatch.setattr("app.monitor.monitoring_engine.notification_manager", manager)
    monkeypatch.setattr("app.api.api.notification_manager", manager)
    monkeypatch.setattr("app.api.api.docker_client", docker_client)
    return manager


def enable_notifications_with_default_filters():
    """
    Enable notifications and add one webhook service, leaving ``event_filters``
    untouched at its shipped default.
    """
    config = config_manager.get_config()
    config.notifications.enabled = True
    config.notifications.services = [
        NotificationService(
            name="Default Contract Webhook",
            type="webhook",
            enabled=True,
            url=WEBHOOK_URL,
        )
    ]
    config_manager.update_config(config)


async def emit_one_event_of_each_type(engine, docker_client) -> None:
    """
    Drive the real producers to emit exactly one event of every type the
    codebase actually emits.

    A separate container per event type keeps the engine's per-``stable_id``
    cooldown and backoff state from interfering between steps.
    """
    # "restart": an unhealthy container below the restart threshold.
    container, info = make_container(name="restart-target", container_id=RESTART_ID)
    docker_client.add_container(container, info)
    await engine._handle_container_restart(container, info, "unhealthy")

    # "quarantine": the same path once the restart threshold is exceeded.
    container, info = make_container(name="quarantine-target", container_id=QUARANTINE_ID)
    docker_client.add_container(container, info)
    for _ in range(3):  # default restart.max_restarts
        config_manager.record_restart("quarantine-target")
    await engine._handle_container_restart(container, info, "unhealthy")

    # "auto_unquarantine": a quarantined container found healthy again.
    container, info = make_container(
        name="auto-unquarantine-target", container_id=AUTO_UNQUARANTINE_ID, status="running"
    )
    docker_client.add_container(container, info)
    config_manager.quarantine_container("auto-unquarantine-target")
    await engine._check_single_container(container)

    # "auto_monitor": a labelled container starting while the engine runs.
    container, info = make_container(name="auto-monitor-target", container_id=AUTO_MONITOR_ID)
    docker_client.add_container(container, info)
    await engine._process_container_start_event(start_event(container.id, "auto-monitor-target"))

    # "unquarantine": user-initiated, emitted by the API rather than the engine.
    container, info = make_container(name="unquarantine-target", container_id=UNQUARANTINE_ID)
    docker_client.add_container(container, info)
    config_manager.quarantine_container("unquarantine-target")
    await unquarantine_container(UNQUARANTINE_ID)


async def drain_notification_queue(manager: NotificationManager) -> None:
    """
    Process everything ``send_event_notification`` queued.

    Driving ``_process_notification`` directly rather than starting the
    background worker keeps the test deterministic (no sleeping, no races).
    """
    while not manager._notification_queue.empty():
        await manager._process_notification(manager._notification_queue.get_nowait())


def delivered_event_types(manager: NotificationManager) -> list:
    return [call["json"]["event"]["type"] for call in manager._session.calls]


@pytest.mark.asyncio
class TestDefaultNotificationContract:
    """
    Scenario 1 of #100: which real events actually reach the wire under the
    default configuration.
    """

    async def test_default_event_filters_are_the_shipped_defaults(self):
        """Guard: the rest of this module is only meaningful against the default."""
        assert config_manager.get_config().notifications.event_filters == DEFAULT_EVENT_FILTERS

    async def test_every_emitted_event_type_is_covered(
        self, engine, docker_client, real_notification_manager
    ):
        """Guard: the drive helper really does produce one of each event type."""
        enable_notifications_with_default_filters()

        await emit_one_event_of_each_type(engine, docker_client)

        assert [event.event_type for event in config_manager.get_events()] == [
            "restart",
            "quarantine",
            "auto_unquarantine",
            "auto_monitor",
            "unquarantine",
        ]

    async def test_only_three_of_five_event_types_notify_by_default(
        self, engine, docker_client, real_notification_manager
    ):
        """
        Current behaviour, gaps included: ``auto_monitor`` and ``unquarantine``
        are emitted but silently dropped by the default filters.
        """
        enable_notifications_with_default_filters()

        await emit_one_event_of_each_type(engine, docker_client)
        await drain_notification_queue(real_notification_manager)

        assert delivered_event_types(real_notification_manager) == [
            "restart",
            "quarantine",
            "auto_unquarantine",
        ]

    async def test_auto_monitor_and_unquarantine_are_dropped(
        self, engine, docker_client, real_notification_manager
    ):
        """
        Both have dedicated titles in ``_format_notification``'s ``title_map``
        but are absent from the default filters, so they never reach a service.
        """
        enable_notifications_with_default_filters()

        await emit_one_event_of_each_type(engine, docker_client)
        await drain_notification_queue(real_notification_manager)

        delivered = delivered_event_types(real_notification_manager)
        assert "auto_monitor" not in delivered
        assert "unquarantine" not in delivered

    async def test_health_check_failed_filter_entry_is_unreachable(
        self, engine, docker_client, real_notification_manager
    ):
        """
        ``health_check_failed`` is in the default filter list but no code path
        emits it - a failed custom health check surfaces as ``restart``.
        """
        enable_notifications_with_default_filters()

        await emit_one_event_of_each_type(engine, docker_client)

        assert "health_check_failed" in DEFAULT_EVENT_FILTERS
        emitted = {event.event_type for event in config_manager.get_events()}
        assert "health_check_failed" not in emitted

    async def test_nothing_is_delivered_while_notifications_are_disabled(
        self, engine, docker_client, real_notification_manager
    ):
        """The default ``notifications.enabled`` is False, so the default is silence."""
        assert config_manager.get_config().notifications.enabled is False

        await emit_one_event_of_each_type(engine, docker_client)
        await drain_notification_queue(real_notification_manager)

        assert real_notification_manager._session.calls == []


@pytest.mark.asyncio
class TestDefaultNotificationPayloads:
    """
    Scenario 2 of #100: the payloads that do go out are well-formed, so a
    rename on either side of the contract breaks a test.
    """

    async def test_delivered_payload_titles_match_the_event_types(
        self, engine, docker_client, real_notification_manager
    ):
        enable_notifications_with_default_filters()

        await emit_one_event_of_each_type(engine, docker_client)
        await drain_notification_queue(real_notification_manager)

        titles_by_type = {
            call["json"]["event"]["type"]: call["json"]["title"]
            for call in real_notification_manager._session.calls
        }

        assert titles_by_type["restart"] == "Container Restarted"
        assert titles_by_type["quarantine"] == "Container Quarantined"
        # Known gap: ``title_map`` has no ``auto_unquarantine`` entry even though
        # the default filters let it through, so it lands on the generic
        # fallback - note the leading space the fallback produces.
        assert titles_by_type["auto_unquarantine"] == " Auto Unquarantine"

    async def test_delivered_payloads_carry_the_container_and_url(
        self, engine, docker_client, real_notification_manager
    ):
        enable_notifications_with_default_filters()

        await emit_one_event_of_each_type(engine, docker_client)
        await drain_notification_queue(real_notification_manager)

        assert len(real_notification_manager._session.calls) == 3
        for call in real_notification_manager._session.calls:
            assert call["url"] == WEBHOOK_URL
            event = call["json"]["event"]
            assert event["container_name"].endswith("-target)")
            assert event["container_id"] is not None
            assert call["json"]["message"].startswith("**Container:**")
