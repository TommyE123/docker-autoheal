"""
Unit tests for the monitoring engine lifecycle and container auto-discovery.

Covers ``start``/``stop``/``get_status``, the startup scan for containers
labelled ``autoheal=true`` and the handling of Docker ``container start``
events.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.config.config_manager import config_manager
from app.tests.unit.conftest import make_container


def monitor_label(key: str, value: str):
    """Return a config mutator that sets the monitor label key and value."""

    def mutate(config):
        config.monitor.label_key = key
        config.monitor.label_value = value

    return mutate


def start_event(container_id: str, name: str) -> dict:
    """
    Build a Docker ``container start`` event payload.

    Matches the real Docker Events API shape: the container ID lives at
    ``Actor.ID``, not a top-level ``id`` key (regression coverage for #78,
    where reading ``event["id"]`` silently no-opped against real events).
    """
    return {
        "Type": "container",
        "Action": "start",
        "Actor": {"ID": container_id, "Attributes": {"name": name}},
        "scope": "local",
    }


@pytest.fixture
def quiet_loops(monkeypatch):
    """Replace the engine's long-running loops so ``start()`` is safe to call."""
    monkeypatch.setattr(
        "app.monitor.monitoring_engine.MonitoringEngine._monitor_loop",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.monitor.monitoring_engine.MonitoringEngine._event_listener_loop",
        AsyncMock(),
    )


@pytest.mark.asyncio
class TestStartStop:
    """Engine start/stop state transitions."""

    async def test_start_marks_engine_running_and_creates_tasks(self, engine, quiet_loops):
        await engine.start()
        try:
            assert engine._running is True
            assert isinstance(engine._task, asyncio.Task)
            assert isinstance(engine._event_task, asyncio.Task)
        finally:
            await engine.stop()

    async def test_start_is_idempotent(self, engine, quiet_loops, monkeypatch):
        scan = AsyncMock()
        monkeypatch.setattr(engine, "_scan_existing_containers", scan)

        await engine.start()
        await engine.start()
        try:
            assert scan.await_count == 1
        finally:
            await engine.stop()

    async def test_stop_cancels_tasks_and_clears_running_flag(self, engine, quiet_loops):
        await engine.start()

        await engine.stop()

        assert engine._running is False
        assert engine._task.done()
        assert engine._event_task.done()

    async def test_stop_when_not_running_is_a_no_op(self, engine):
        await engine.stop()

        assert engine._running is False

    async def test_get_status_reports_engine_state(self, engine):
        engine._last_restart_times["web"] = None
        config_manager.quarantine_container("db")

        status = engine.get_status()

        assert status == {
            "running": False,
            "monitored_containers": 1,
            "quarantined_containers": 1,
        }


@pytest.mark.asyncio
class TestScanExistingContainers:
    """Startup discovery of containers already running with ``autoheal=true``."""

    async def test_labelled_container_is_added_to_monitoring(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["web"]
        assert [e.event_type for e in config_manager.get_events()] == ["auto_monitor"]
        assert "autoheal=true" in config_manager.get_events()[0].message

    async def test_custom_label_container_is_added_to_monitoring(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"heal": "yes"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_default_label_is_ignored_when_a_custom_label_is_configured(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []

    async def test_custom_label_with_wrong_value_is_ignored(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"heal": "no"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []

    async def test_empty_custom_label_value_requires_the_label_to_be_present(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "")))
        container, info = make_container(name="web", labels={})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []

    async def test_empty_custom_label_value_matches_only_an_empty_label_value(
        self, engine, docker_client, update_config
    ):
        update_config(monitor_label("heal", ""))
        empty_value, empty_info = make_container(name="empty", container_id="e" * 64, labels={"heal": ""})
        other_value, other_info = make_container(name="other", container_id="f" * 64, labels={"heal": "yes"})
        docker_client.add_container(empty_value, empty_info)
        docker_client.add_container(other_value, other_info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["empty"]

    async def test_event_message_names_the_default_label(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_events()[0].message == (
            "Automatically added to monitoring on startup due to autoheal=true label (stable_id: web)"
        )

    async def test_event_message_names_the_configured_label(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"heal": "yes"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_events()[0].message == (
            "Automatically added to monitoring on startup due to heal=yes label (stable_id: web)"
        )

    async def test_empty_monitoring_id_falls_back_to_the_container_name(self, engine, docker_client):
        container, info = make_container(
            name="web", labels={"autoheal": "true", "monitoring.id": ""}
        )
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_empty_monitoring_id_falls_back_to_the_compose_identity(
        self, engine, docker_client
    ):
        container, info = make_container(
            name="stack-web-1",
            labels={
                "autoheal": "true",
                "monitoring.id": "",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["stack_web"]

    async def test_selection_is_kept_when_recording_the_event_fails(
        self, engine, docker_client, monkeypatch
    ):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        def failing_add_event(_event):
            raise RuntimeError("event store unavailable")

        monkeypatch.setattr(config_manager, "add_event", failing_add_event)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_compose_container_is_added_under_its_stable_id(self, engine, docker_client):
        container, info = make_container(
            name="stack-web-1",
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["stack_web"]

    async def test_monitoring_id_label_wins(self, engine, docker_client):
        container, info = make_container(
            name="web",
            labels={"autoheal": "true", "monitoring.id": "my-service"},
        )
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["my-service"]

    async def test_unlabelled_container_is_ignored(self, engine, docker_client):
        container, info = make_container(name="web", labels={})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []
        assert config_manager.get_events() == []

    async def test_container_with_non_true_autoheal_value_is_ignored(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "false"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []
        assert config_manager.get_events() == []

    async def test_notification_failure_does_not_prevent_container_from_being_added(
        self, engine, docker_client, mock_notification_manager
    ):
        mock_notification_manager.send_event_notification.side_effect = RuntimeError(
            "notification transport unavailable"
        )
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["web"]
        assert [e.event_type for e in config_manager.get_events()] == ["auto_monitor"]
        mock_notification_manager.send_event_notification.assert_awaited_once()
        (notified_event,) = mock_notification_manager.send_event_notification.await_args.args
        assert notified_event.event_type == "auto_monitor"

    async def test_already_selected_container_is_not_added_twice(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: c.containers.selected.append("web"))
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["web"]
        assert config_manager.get_events() == []

    async def test_excluded_container_is_not_added(self, engine, docker_client, update_config):
        update_config(lambda c: c.containers.excluded.append("web"))
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []

    async def test_scan_is_skipped_when_docker_is_unavailable(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)
        docker_client.connected = False

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []

    async def test_scan_start_log_names_the_configured_label(self, engine, caplog, update_config):
        update_config(monitor_label("heal", "yes"))

        with caplog.at_level("INFO"):
            await engine._scan_existing_containers()

        assert "Scanning existing containers for heal=yes label" in caplog.text
        assert "autoheal=true" not in caplog.text

    async def test_uninspectable_container_is_skipped(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)
        docker_client._info.pop(container.id)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []

    async def test_one_failing_container_does_not_abort_the_scan(self, engine, docker_client):
        broken, broken_info = make_container(
            name="broken", container_id="b" * 64, labels={"autoheal": "true"}
        )
        good, good_info = make_container(
            name="web", container_id="a" * 64, labels={"autoheal": "true"}
        )
        docker_client.add_container(broken, broken_info)
        docker_client.add_container(good, good_info)
        docker_client.info_errors[broken.id] = RuntimeError("inspect failed")

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_listing_failure_is_swallowed(self, engine, docker_client):
        docker_client.list_containers_error = RuntimeError("docker daemon unavailable")

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == []


@pytest.mark.asyncio
class TestProcessContainerStartEvent:
    """Auto-monitoring of containers started after the engine is running."""

    async def test_labelled_container_is_added_on_start_event(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == ["web"]
        assert [e.event_type for e in config_manager.get_events()] == ["auto_monitor"]

    async def test_empty_monitoring_id_falls_back_to_the_container_name(self, engine, docker_client):
        container, info = make_container(
            name="web", labels={"autoheal": "true", "monitoring.id": ""}
        )
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_custom_label_container_is_added_to_monitoring(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"heal": "yes"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_empty_monitoring_id_falls_back_to_the_compose_identity(
        self, engine, docker_client
    ):
        container, info = make_container(
            name="stack-web-1",
            labels={
                "autoheal": "true",
                "monitoring.id": "",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "stack-web-1"))

        assert config_manager.get_config().containers.selected == ["stack_web"]

    async def test_selection_is_kept_when_recording_the_event_fails(
        self, engine, docker_client, monkeypatch
    ):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        def failing_add_event(_event):
            raise RuntimeError("event store unavailable")

        monkeypatch.setattr(config_manager, "add_event", failing_add_event)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_default_label_is_ignored_when_a_custom_label_is_configured(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []

    async def test_custom_label_with_wrong_value_is_ignored(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"heal": "no"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []

    async def test_empty_custom_label_value_requires_the_label_to_be_present(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "")))
        container, info = make_container(name="web", labels={})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []

    async def test_empty_custom_label_value_matches_only_an_empty_label_value(
        self, engine, docker_client, update_config
    ):
        update_config(monitor_label("heal", ""))
        empty_value, empty_info = make_container(name="empty", container_id="e" * 64, labels={"heal": ""})
        other_value, other_info = make_container(name="other", container_id="f" * 64, labels={"heal": "yes"})
        docker_client.add_container(empty_value, empty_info)
        docker_client.add_container(other_value, other_info)

        await engine._process_container_start_event(start_event(empty_value.id, "empty"))
        await engine._process_container_start_event(start_event(other_value.id, "other"))

        assert config_manager.get_config().containers.selected == ["empty"]

    async def test_event_message_names_the_default_label(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_events()[0].message == (
            "Automatically added to monitoring due to autoheal=true label (stable_id: web)"
        )

    async def test_event_message_names_the_configured_label(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: (setattr(c.monitor, "label_key", "heal"), setattr(c.monitor, "label_value", "yes")))
        container, info = make_container(name="web", labels={"heal": "yes"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_events()[0].message == (
            "Automatically added to monitoring due to heal=yes label (stable_id: web)"
        )

    async def test_compose_container_is_added_under_its_stable_id(self, engine, docker_client):
        container, info = make_container(
            name="stack-web-1",
            labels={
                "autoheal": "true",
                "com.docker.compose.project": "stack",
                "com.docker.compose.service": "web",
            },
        )
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "stack-web-1"))

        assert config_manager.get_config().containers.selected == ["stack_web"]

    async def test_real_docker_daemon_event_shape_is_handled(self, engine, docker_client):
        """
        Regression test for #78.

        A real Docker daemon ``start`` event has no top-level ``id`` key -
        the container ID is only ever under ``Actor.ID``. The engine used to
        read ``event["id"]``, which is always ``None`` against a real event
        and made it silently return before doing anything or logging.
        """
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)
        real_daemon_event = {
            "Type": "container",
            "Action": "start",
            "Actor": {
                "ID": container.id,
                "Attributes": {"autoheal": "true", "image": "nginx:alpine", "name": "web"},
            },
            "scope": "local",
            "time": 1700000000,
            "timeNano": 1700000000000000000,
        }

        await engine._process_container_start_event(real_daemon_event)

        assert config_manager.get_config().containers.selected == ["web"]

    async def test_monitoring_id_label_wins(self, engine, docker_client):
        container, info = make_container(
            name="web",
            labels={"autoheal": "true", "monitoring.id": "my-service"},
        )
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == ["my-service"]

    async def test_recreated_container_is_not_added_twice(self, engine, docker_client):
        """The stable ID keeps monitoring identity stable across recreation."""
        labels = {
            "autoheal": "true",
            "com.docker.compose.project": "stack",
            "com.docker.compose.service": "web",
        }
        old, old_info = make_container(name="stack-web-1", container_id="a" * 64, labels=labels)
        docker_client.add_container(old, old_info)
        await engine._process_container_start_event(start_event(old.id, "stack-web-1"))

        new, new_info = make_container(name="stack-web-1", container_id="c" * 64, labels=labels)
        docker_client.add_container(new, new_info)
        await engine._process_container_start_event(start_event(new.id, "stack-web-1"))

        assert config_manager.get_config().containers.selected == ["stack_web"]
        assert len(config_manager.get_events()) == 1

    async def test_event_name_attribute_labels_the_container(self, engine, docker_client):
        container, info = make_container(name="inspected-name", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "event-name"))

        assert config_manager.get_config().containers.selected == ["event-name"]
        (event,) = config_manager.get_events()
        assert event.container_name == "event-name (event-name)"

    async def test_selection_is_saved_before_the_event_is_recorded(
        self, engine, docker_client, mock_notification_manager, monkeypatch
    ):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        def failing_save(_config):
            raise OSError("disk full")

        monkeypatch.setattr(config_manager, "update_config", failing_save)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []
        assert config_manager.get_events() == []
        mock_notification_manager.send_event_notification.assert_not_awaited()

    async def test_event_without_container_id_is_ignored(self, engine):
        await engine._process_container_start_event({"Actor": {"Attributes": {"name": "web"}}})

        assert config_manager.get_config().containers.selected == []

    async def test_missing_container_is_ignored(self, engine, docker_client):
        await engine._process_container_start_event(start_event("z" * 64, "vanished"))

        assert config_manager.get_config().containers.selected == []

    async def test_unlabelled_container_is_ignored(self, engine, docker_client):
        container, info = make_container(name="web", labels={})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []

    async def test_excluded_container_is_ignored(self, engine, docker_client, update_config):
        update_config(lambda c: c.containers.excluded.append("web"))
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []

    async def test_malformed_event_does_not_raise(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)
        docker_client.info_errors[container.id] = RuntimeError("inspect failed")

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []

    async def test_container_with_non_true_autoheal_value_is_ignored(self, engine, docker_client):
        container, info = make_container(name="web", labels={"autoheal": "false"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == []

    async def test_notification_failure_does_not_prevent_container_from_being_added(
        self, engine, docker_client, mock_notification_manager
    ):
        mock_notification_manager.send_event_notification.side_effect = RuntimeError(
            "notification transport unavailable"
        )
        container, info = make_container(name="web", labels={"autoheal": "true"})
        docker_client.add_container(container, info)

        await engine._process_container_start_event(start_event(container.id, "web"))

        assert config_manager.get_config().containers.selected == ["web"]
        assert [e.event_type for e in config_manager.get_events()] == ["auto_monitor"]
        mock_notification_manager.send_event_notification.assert_awaited_once()
        (notified_event,) = mock_notification_manager.send_event_notification.await_args.args
        assert notified_event.event_type == "auto_monitor"


@pytest.mark.asyncio
class TestMonitorLoop:
    """The periodic loop that drives ``_check_containers``."""

    async def test_loop_checks_containers_then_waits_for_the_interval(
        self, engine, monkeypatch, recorded_sleeps, update_config
    ):
        update_config(lambda c: setattr(c.monitor, "interval_seconds", 45))
        calls = []

        async def fake_check():
            calls.append(1)
            engine._running = False

        monkeypatch.setattr(engine, "_check_containers", fake_check)
        engine._running = True

        await engine._monitor_loop()

        assert calls == [1]
        assert recorded_sleeps == [45]

    async def test_loop_recovers_from_an_unexpected_error(
        self, engine, monkeypatch, recorded_sleeps
    ):
        calls = []

        async def fake_check():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient failure")
            engine._running = False

        monkeypatch.setattr(engine, "_check_containers", fake_check)
        engine._running = True

        await engine._monitor_loop()

        assert len(calls) == 2
        assert recorded_sleeps == [5, 30]  # error pause, then the normal interval

    async def test_stop_survives_a_task_that_failed(self, engine):
        async def boom():
            raise RuntimeError("task blew up")

        engine._running = True
        engine._task = asyncio.create_task(boom())
        engine._event_task = asyncio.create_task(boom())
        await asyncio.sleep(0)

        await engine.stop()

        assert engine._running is False


@pytest.mark.asyncio
class TestEventListenerLoop:
    """The Docker event listener thread and its async consumer."""

    async def test_start_events_are_forwarded_to_the_handler(self, engine, docker_client, monkeypatch):
        import threading

        release = threading.Event()
        event = start_event("a" * 64, "web")

        def event_stream():
            yield event
            release.wait(timeout=5)

        docker_client.events = event_stream()

        processed = []

        async def fake_process(received):
            processed.append(received)
            engine._running = False

        monkeypatch.setattr(engine, "_process_container_start_event", fake_process)
        engine._running = True

        try:
            await asyncio.wait_for(engine._event_listener_loop(), timeout=10)
        finally:
            release.set()

        assert processed == [event]

    async def test_none_event_stream_is_retried_until_it_recovers(
        self, engine, docker_client, monkeypatch, caplog
    ):
        import threading

        release = threading.Event()
        event = start_event("b" * 64, "web")
        sleep_calls = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr("time.sleep", fake_sleep)

        def working_stream():
            yield event
            release.wait(timeout=5)

        attempts = []

        def get_events_sequence():
            attempts.append(1)
            if len(attempts) == 1:
                return None
            return working_stream()

        docker_client.events = get_events_sequence

        processed = []

        async def fake_process(received):
            processed.append(received)
            engine._running = False

        monkeypatch.setattr(engine, "_process_container_start_event", fake_process)
        engine._running = True

        try:
            await asyncio.wait_for(engine._event_listener_loop(), timeout=10)
        finally:
            release.set()

        assert processed == [event]
        assert len(attempts) == 2
        assert sleep_calls == [10]
        assert "Failed to get event stream, retrying in 10 seconds" in caplog.text

    async def test_mid_stream_exception_is_retried_until_it_recovers(
        self, engine, docker_client, monkeypatch, caplog
    ):
        import threading

        release = threading.Event()
        first_event = start_event("c" * 64, "web-1")
        second_event = start_event("d" * 64, "web-2")
        sleep_calls = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr("time.sleep", fake_sleep)

        def broken_stream():
            yield first_event
            raise RuntimeError("stream disconnected")

        def working_stream():
            yield second_event
            release.wait(timeout=5)

        attempts = []

        def get_events_sequence():
            attempts.append(1)
            if len(attempts) == 1:
                return broken_stream()
            return working_stream()

        docker_client.events = get_events_sequence

        processed = []

        async def fake_process(received):
            processed.append(received)
            if received == second_event:
                engine._running = False

        monkeypatch.setattr(engine, "_process_container_start_event", fake_process)
        engine._running = True

        try:
            await asyncio.wait_for(engine._event_listener_loop(), timeout=10)
        finally:
            release.set()

        assert processed == [first_event, second_event]
        assert len(attempts) == 2
        assert sleep_calls == [10]
        assert "Error in event listener thread: stream disconnected" in caplog.text

    async def test_retry_loop_stops_once_shutdown_is_requested(
        self, engine, docker_client, monkeypatch
    ):
        attempts = []

        def fake_sleep(seconds):
            # Simulate a shutdown request arriving while the thread is
            # waiting to retry, so it must not call get_events() again.
            engine._running = False

        monkeypatch.setattr("time.sleep", fake_sleep)

        def get_events_sequence():
            attempts.append(1)

        docker_client.events = get_events_sequence
        engine._running = True

        await asyncio.wait_for(engine._event_listener_loop(), timeout=10)

        assert attempts == [1]


DEV_LABEL = "autoheal.dev"


@pytest.fixture
def dev_label_config(update_config):
    """Configure the monitoring label the way the dev Compose stack does."""
    update_config(lambda c: setattr(c.monitor, "label_key", DEV_LABEL))


@pytest.mark.asyncio
class TestCustomMonitorLabel:
    """Auto-discovery honours ``monitor.label_key``/``label_value`` (#369)."""

    async def test_scan_and_event_use_default_label_by_default(self, engine, docker_client):
        prod, prod_info = make_container(name="prod", container_id="a" * 64, labels={"autoheal": "true"})
        dev, dev_info = make_container(name="dev", container_id="b" * 64, labels={DEV_LABEL: "true"})
        docker_client.add_container(prod, prod_info)
        docker_client.add_container(dev, dev_info)

        await engine._scan_existing_containers()
        await engine._process_container_start_event(start_event(dev.id, "dev"))

        assert config_manager.get_config().containers.selected == ["prod"]

    async def test_scan_selects_only_custom_labelled_containers(
        self, engine, docker_client, dev_label_config
    ):
        prod, prod_info = make_container(name="prod", container_id="a" * 64, labels={"autoheal": "true"})
        dev, dev_info = make_container(name="dev", container_id="b" * 64, labels={DEV_LABEL: "true"})
        docker_client.add_container(prod, prod_info)
        docker_client.add_container(dev, dev_info)

        await engine._scan_existing_containers()

        assert config_manager.get_config().containers.selected == ["dev"]
        [event] = config_manager.get_events()
        assert f"{DEV_LABEL}=true" in event.message
        assert "autoheal=true" not in event.message

    async def test_start_event_selects_only_custom_labelled_containers(
        self, engine, docker_client, dev_label_config
    ):
        prod, prod_info = make_container(name="prod", container_id="a" * 64, labels={"autoheal": "true"})
        dev, dev_info = make_container(name="dev", container_id="b" * 64, labels={DEV_LABEL: "true"})
        docker_client.add_container(prod, prod_info)
        docker_client.add_container(dev, dev_info)

        await engine._process_container_start_event(start_event(prod.id, "prod"))
        assert config_manager.get_config().containers.selected == []

        await engine._process_container_start_event(start_event(dev.id, "dev"))
        assert config_manager.get_config().containers.selected == ["dev"]
        [event] = config_manager.get_events()
        assert f"{DEV_LABEL}=true" in event.message
        assert "autoheal=true" not in event.message

    async def test_dev_config_does_not_monitor_unselected_production_labelled_container(
        self, engine, docker_client, update_config
    ):
        """With the dev label, automatic discovery does not pick up ``autoheal=true`` containers."""
        prod, prod_info = make_container(name="prod", container_id="a" * 64, labels={"autoheal": "true"})
        dev, dev_info = make_container(name="dev", container_id="b" * 64, labels={DEV_LABEL: "true"})

        # Default (production) config: only autoheal=true is monitored.
        assert engine.should_monitor_container(prod, prod_info) is True
        assert engine.should_monitor_container(dev, dev_info) is False

        # Dev config: only autoheal.dev=true is monitored.
        update_config(lambda c: setattr(c.monitor, "label_key", DEV_LABEL))
        assert engine.should_monitor_container(dev, dev_info) is True
        assert engine.should_monitor_container(prod, prod_info) is False
