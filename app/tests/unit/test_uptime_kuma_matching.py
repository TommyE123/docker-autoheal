"""Unit tests for the Uptime-Kuma container/monitor matcher (issue #141).

The matcher must never guess: it only produces a mapping when a container
and a monitor uniquely identify each other after deterministic name
normalization, since a wrong auto-mapping could cause AutoHeal to act on
the wrong container.
"""

from app.uptime_kuma.matching import match_uptime_kuma_monitors, normalize_name


def _container(stable_id, name, compose_service=None):
    info = {"stable_id": stable_id, "name": name}
    if compose_service is not None:
        info["compose_service"] = compose_service
    return info


def _monitor(friendly_name):
    return {"friendly_name": friendly_name}


class TestNormalizeName:
    def test_case_is_ignored(self):
        assert normalize_name("Radarr") == normalize_name("radarr")

    def test_hyphen_underscore_and_space_are_equivalent(self):
        variants = ["Steam-Headless", "steam_headless", "steam headless", "STEAM-HEADLESS"]
        normalized = {normalize_name(v) for v in variants}
        assert len(normalized) == 1


class TestMatchUptimeKumaMonitors:
    def test_exact_match(self):
        containers = [_container("web", "web")]
        monitors = [_monitor("web")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert result == [{"container_id": "web", "monitor_friendly_name": "web"}]

    def test_case_insensitive_match(self):
        containers = [_container("radarr", "radarr")]
        monitors = [_monitor("Radarr")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert result == [{"container_id": "radarr", "monitor_friendly_name": "Radarr"}]

    def test_hyphen_underscore_space_normalization(self):
        cases = [
            ("steam-headless", "Steam-Headless"),
            ("wireguard-easy", "Wireguard Easy"),
            ("filebrowser-quantum", "FileBrowser Quantum"),
        ]
        for container_name, monitor_name in cases:
            containers = [_container(container_name, container_name)]
            monitors = [_monitor(monitor_name)]

            result = match_uptime_kuma_monitors(containers, monitors)

            assert result == [
                {"container_id": container_name, "monitor_friendly_name": monitor_name}
            ], f"{container_name} should match {monitor_name}"

    def test_compose_project_prefix_matches_via_service_name(self):
        # Docker Compose stable IDs are "project_service"; the container's
        # actual Docker name may be something else entirely (e.g.
        # "vpn-apps-trawl-1"), so only the compose service name, not the
        # full stable ID, should be compared against the monitor name.
        containers = [_container("vpn-apps_trawl", "vpn-apps-trawl-1", compose_service="trawl")]
        monitors = [_monitor("Trawl")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert result == [
            {"container_id": "vpn-apps_trawl", "monitor_friendly_name": "Trawl"}
        ]

    def test_sabnzbd_and_qbittorrent_style_capitalisation(self):
        containers = [
            _container("sabnzbd", "sabnzbd"),
            _container("qbittorrent", "qbittorrent"),
        ]
        monitors = [_monitor("SABnzbd"), _monitor("qBittorrent")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert {(m["container_id"], m["monitor_friendly_name"]) for m in result} == {
            ("sabnzbd", "SABnzbd"),
            ("qbittorrent", "qBittorrent"),
        }

    def test_no_match_leaves_monitor_and_container_unmapped(self):
        containers = [_container("web", "web")]
        monitors = [_monitor("completely-unrelated")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert result == []

    def test_ambiguous_match_across_two_containers_is_left_unmapped(self, caplog):
        """Two containers that both normalize to the same monitor name must
        not have either one arbitrarily selected."""
        containers = [
            _container("steam-headless", "steam-headless"),
            _container("steam_headless-2", "steam_headless"),
        ]
        monitors = [_monitor("Steam-Headless")]

        with caplog.at_level("DEBUG", logger="app.uptime_kuma.matching"):
            result = match_uptime_kuma_monitors(containers, monitors)

        assert result == []
        # A monitor matching >1 container is only detectable once every
        # container's candidates are known, so this is logged from the
        # monitor side (len(matched_indices) == 1 for each container
        # individually) rather than the "matched several monitors" branch.
        assert "steam-headless" in caplog.text
        assert "ambiguous" in caplog.text

    def test_ambiguous_match_across_two_monitors_is_left_unmapped(self, caplog):
        """A container whose name normalizes to two distinct monitor names
        must not have either one arbitrarily selected."""
        containers = [_container("web", "web")]
        monitors = [_monitor("Web"), _monitor("web")]

        with caplog.at_level("DEBUG", logger="app.uptime_kuma.matching"):
            result = match_uptime_kuma_monitors(containers, monitors)

        assert result == []
        assert "web" in caplog.text
        assert "matched 2 monitors" in caplog.text
        assert "ambiguous" in caplog.text

    def test_ambiguous_match_across_two_monitors_sharing_identical_friendly_name(self):
        """Two distinct Uptime-Kuma monitor objects can legitimately share the
        exact same friendly_name text. A naive implementation that tracks
        candidates by name string (rather than by monitor identity) would
        collapse these into a single candidate and treat the match as
        unambiguous - breaking the safety contract that a mapping is only
        ever created when exactly one monitor is a candidate."""
        containers = [_container("web", "web")]
        monitors = [_monitor("web"), _monitor("web")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert result == []

    def test_multiple_containers_and_monitors_do_not_cross_match(self):
        containers = [
            _container("web", "web"),
            _container("db", "db"),
        ]
        monitors = [_monitor("web"), _monitor("db"), _monitor("unrelated")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert {(m["container_id"], m["monitor_friendly_name"]) for m in result} == {
            ("web", "web"),
            ("db", "db"),
        }

    def test_no_fuzzy_matching_for_near_miss_names(self):
        """A monitor name that is merely similar (not equal after
        normalization) must never be selected as the 'closest' match."""
        containers = [_container("radarr", "radarr")]
        monitors = [_monitor("Radar")]

        result = match_uptime_kuma_monitors(containers, monitors)

        assert result == []
