"""
Unit tests for ``MonitoringEngine._handle_container_restart``.

This covers the restart state machine: cooldown, restart threshold, quarantine,
exponential backoff, successful restarts, failed restarts and the events they
produce.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.config.config_manager import config_manager
from app.tests.unit.conftest import make_container


def events_of_type(event_type: str) -> list:
    """Return the recorded events of a given type."""
    return [event for event in config_manager.get_events() if event.event_type == event_type]


@pytest.mark.asyncio
class TestRestartDecision:
    """The happy path: an unhealthy container is restarted and recorded."""

    async def test_successful_restart_records_event_and_state(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "Container exited with code 1")

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

        await engine._handle_container_restart(container, info, "unhealthy")

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

        await engine._handle_container_restart(container, info, "unhealthy")

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

        await engine._handle_container_restart(container, info, "unhealthy")

        restarts = events_of_type("restart")
        assert len(restarts) == 1
        assert restarts[0].status == "failure"
        assert "Restart failed" in restarts[0].message

    async def test_failed_restart_still_counts_towards_the_threshold(self, engine, docker_client):
        """Existing behaviour: failures count, so a broken container is quarantined."""
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        await engine._handle_container_restart(container, info, "unhealthy")

        assert config_manager.get_restart_count("web", 600) == 1
        assert "web" in engine._last_restart_times

    async def test_failed_restart_does_not_reset_backoff(self, engine, docker_client, update_config):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        await engine._handle_container_restart(container, info, "unhealthy")

        assert engine._backoff_delays["web"] == 20


@pytest.mark.asyncio
class TestCooldown:
    """Restarts are suppressed while the container is inside its cooldown."""

    async def test_restart_suppressed_during_cooldown(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._last_restart_times["web"] = datetime.now(timezone.utc)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == []
        assert config_manager.get_restart_count("web", 600) == 0
        assert config_manager.get_events() == []

    async def test_restart_allowed_once_cooldown_expires(self, engine, docker_client, update_config):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 60))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        engine._last_restart_times["web"] = datetime.now(timezone.utc) - timedelta(seconds=61)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == ["web"]

    async def test_zero_cooldown_allows_back_to_back_restarts(
        self, engine, docker_client, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")
        await engine._handle_container_restart(container, info, "unhealthy")

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

        await engine._handle_container_restart(old_container, old_info, "unhealthy")

        new_container, new_info = make_container(
            name="stack-web-1", container_id="c" * 64, labels=labels
        )
        docker_client.add_container(new_container, new_info)

        await engine._handle_container_restart(new_container, new_info, "unhealthy")

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

        await engine._handle_container_restart(container, info, "unhealthy")

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
            await engine._handle_container_restart(container, info, "unhealthy")

        assert docker_client.restart_calls == ["web"] * 3
        assert config_manager.is_quarantined("web") is True
        assert len(events_of_type("restart")) == 3
        assert len(events_of_type("quarantine")) == 1

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


@pytest.mark.asyncio
class TestRestartBackoff:
    """Exponential backoff between restart attempts."""

    async def test_initial_backoff_delay_is_applied(self, engine, docker_client, recorded_sleeps):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert recorded_sleeps == [10]  # default initial_seconds

    async def test_backoff_is_skipped_when_disabled(self, engine, docker_client, recorded_sleeps, update_config):
        update_config(lambda c: setattr(c.restart.backoff, "enabled", False))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert recorded_sleeps == []
        assert docker_client.restart_calls == ["web"]

    async def test_backoff_resets_after_a_successful_restart(self, engine, docker_client):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)

        await engine._handle_container_restart(container, info, "unhealthy")

        assert engine._backoff_delays["web"] == 10  # reset to initial_seconds

    async def test_backoff_grows_while_restarts_keep_failing(
        self, engine, docker_client, recorded_sleeps, update_config
    ):
        update_config(lambda c: setattr(c.restart, "cooldown_seconds", 0))
        update_config(lambda c: setattr(c.restart, "max_restarts", 10))
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        await engine._handle_container_restart(container, info, "unhealthy")
        await engine._handle_container_restart(container, info, "unhealthy")
        await engine._handle_container_restart(container, info, "unhealthy")

        assert recorded_sleeps == [10, 20, 40]
        assert engine._backoff_delays["web"] == 80

    async def test_backoff_multiplier_is_configurable(
        self, engine, docker_client, recorded_sleeps, update_config
    ):
        def _configure(config):
            config.restart.cooldown_seconds = 0
            config.restart.backoff.initial_seconds = 5
            config.restart.backoff.multiplier = 3.0

        update_config(_configure)
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        docker_client.restart_results["web"] = False

        await engine._handle_container_restart(container, info, "unhealthy")
        await engine._handle_container_restart(container, info, "unhealthy")

        assert recorded_sleeps == [5, 15]

    async def test_no_backoff_delay_when_container_is_quarantined(
        self, engine, docker_client, recorded_sleeps
    ):
        container, info = make_container(name="web")
        docker_client.add_container(container, info)
        for _ in range(3):
            config_manager.record_restart("web")

        await engine._handle_container_restart(container, info, "unhealthy")

        assert recorded_sleeps == []


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

    async def test_no_alert_when_alerts_disabled(self, engine, docker_client, update_config, monkeypatch):
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
