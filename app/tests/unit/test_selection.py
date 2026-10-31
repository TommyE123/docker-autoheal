"""
Unit tests for ``app.monitor.selection.should_monitor``.

The function is pure: it takes the configuration, the container information and the stable
identifier, so these tests need no engine, Docker client or configuration manager.
"""

import pytest

from app.config.config_manager import AutoHealConfig
from app.monitor.selection import should_monitor

FULL_ID = "a" * 64
INFO = {
    "full_id": FULL_ID,
    "id": FULL_ID[:12],
    "name": "stack-web-1",
    "labels": {
        "autoheal": "true",
        "com.docker.compose.project": "stack",
        "com.docker.compose.service": "web",
    },
}
STABLE_ID = "stack_web"


def config_with(**sections) -> AutoHealConfig:
    """A default configuration with the given sections replaced"""
    return AutoHealConfig.model_validate(sections)


def monitored(config: AutoHealConfig, info: dict = INFO, stable_id: str | None = STABLE_ID):
    return should_monitor(config, info, stable_id)


IDENTITIES = [STABLE_ID, FULL_ID, FULL_ID[:12], "stack-web-1", "web"]


@pytest.mark.parametrize("identity", IDENTITIES)
def test_excluded_by_any_identity(identity):
    config = config_with(containers={"excluded": [identity]}, monitor={"include_all": True})

    assert monitored(config) is False


@pytest.mark.parametrize("identity", IDENTITIES)
def test_selected_by_any_identity_without_the_label(identity):
    config = config_with(containers={"selected": [identity]})
    info = {**INFO, "labels": {**INFO["labels"], "autoheal": "false"}}

    assert monitored(config, info) is True


def test_exclusion_beats_selection():
    config = config_with(containers={"selected": ["web"], "excluded": [STABLE_ID]})

    assert monitored(config) is False


def test_selection_skips_the_filters():
    config = config_with(
        containers={"selected": [STABLE_ID]}, filters={"blacklist_names": ["stack-*"]}
    )

    assert monitored(config) is True


def test_a_missing_stable_id_does_not_match_a_list():
    config = config_with(containers={"excluded": [STABLE_ID]})

    assert monitored(config, stable_id=STABLE_ID) is False
    assert monitored(config, stable_id=None) is True


@pytest.mark.parametrize("labels", [{"com.docker.compose.service": ""}, {}])
def test_an_empty_compose_service_does_not_match_an_empty_list_entry(labels):
    config = config_with(containers={"excluded": [""]}, monitor={"include_all": True})
    info = {**INFO, "labels": labels}

    assert monitored(config, info) is True


class TestLabelGate:
    def test_matching_label_is_monitored(self):
        assert monitored(config_with()) is True

    def test_missing_label_is_not_monitored(self):
        assert monitored(config_with(), {**INFO, "labels": {}}) is False

    def test_wrong_label_value_is_not_monitored(self):
        info = {**INFO, "labels": {"autoheal": "false"}}

        assert monitored(config_with(), info) is False

    def test_custom_label_key_and_value(self):
        config = config_with(monitor={"label_key": "heal", "label_value": "yes"})

        assert monitored(config, {**INFO, "labels": {"heal": "yes"}}) is True
        assert monitored(config) is False

    def test_include_all_ignores_the_label(self):
        config = config_with(monitor={"include_all": True})

        assert monitored(config, {**INFO, "labels": {}}) is True


class TestNameFilters:
    def test_blacklisted_name_pattern(self):
        config = config_with(filters={"blacklist_names": ["stack-*"]})

        assert monitored(config) is False

    def test_unmatched_blacklist_pattern_keeps_the_container(self):
        config = config_with(filters={"blacklist_names": ["other-*"]})

        assert monitored(config) is True

    def test_whitelist_requires_a_matching_name(self):
        config = config_with(filters={"whitelist_names": ["db-*", "stack-*"]})

        assert monitored(config) is True
        assert monitored(config_with(filters={"whitelist_names": ["db-*"]})) is False

    def test_a_container_without_a_name_matches_no_pattern(self):
        info = {**INFO, "name": None}

        assert monitored(config_with(filters={"blacklist_names": ["*"]}), info) is True
        assert monitored(config_with(filters={"whitelist_names": ["*"]}), info) is False


class TestLabelFilters:
    def test_blacklisted_label(self):
        config = config_with(filters={"blacklist_labels": [{"tier": "dev"}]})
        info = {**INFO, "labels": {**INFO["labels"], "tier": "dev"}}

        assert monitored(config, info) is False

    def test_blacklist_label_with_another_value_keeps_the_container(self):
        config = config_with(filters={"blacklist_labels": [{"tier": "dev"}]})
        info = {**INFO, "labels": {**INFO["labels"], "tier": "prod"}}

        assert monitored(config, info) is True

    def test_whitelist_needs_one_matching_label(self):
        config = config_with(filters={"whitelist_labels": [{"tier": "dev"}, {"tier": "prod"}]})
        info = {**INFO, "labels": {**INFO["labels"], "tier": "prod"}}

        assert monitored(config, info) is True
        assert monitored(config) is False

    def test_an_empty_whitelist_filter_matches_nothing(self):
        config = config_with(filters={"whitelist_labels": [{}]})

        assert monitored(config) is False

    def test_multi_label_blacklist_filter_needs_every_label(self):
        config = config_with(filters={"blacklist_labels": [{"tier": "dev", "team": "a"}]})
        partial = {**INFO, "labels": {**INFO["labels"], "tier": "dev", "team": "b"}}
        full = {**INFO, "labels": {**INFO["labels"], "tier": "dev", "team": "a"}}

        assert monitored(config, partial) is True
        assert monitored(config, full) is False

    def test_multi_label_whitelist_filter_needs_every_label(self):
        config = config_with(filters={"whitelist_labels": [{"tier": "prod", "team": "a"}]})
        partial = {**INFO, "labels": {**INFO["labels"], "tier": "prod", "team": "b"}}
        full = {**INFO, "labels": {**INFO["labels"], "tier": "prod", "team": "a"}}

        assert monitored(config, partial) is False
        assert monitored(config, full) is True

    def test_any_one_of_several_multi_label_filters_is_enough(self):
        config = config_with(
            filters={
                "whitelist_labels": [{"tier": "prod", "team": "a"}, {"tier": "dev", "team": "b"}]
            }
        )
        info = {**INFO, "labels": {**INFO["labels"], "tier": "dev", "team": "b"}}

        assert monitored(config, info) is True

    def test_blacklist_wins_over_whitelist(self):
        config = config_with(
            filters={
                "whitelist_names": ["stack-*"],
                "blacklist_labels": [{"com.docker.compose.service": "web"}],
            }
        )

        assert monitored(config) is False
