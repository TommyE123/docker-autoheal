"""
Unit tests for the ``if``/``else`` return branches in :mod:`app.scripts.demo`.

These are regression tests written ahead of a Ruff RET505 cleanup
(flattening ``if ...: return X else: return Y`` into sequential returns) to
pin down the current success/failure behaviour of each function so the
refactor cannot silently change what is returned.
"""

from unittest.mock import MagicMock, patch

from app.scripts import demo


class TestCheckServiceHealth:
    def test_returns_true_on_200(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "status": "ok",
            "docker_connected": True,
            "monitoring_active": True,
        }
        with patch.object(demo.requests, "get", return_value=response):
            assert demo.check_service_health() is True

    def test_returns_false_on_non_200(self):
        response = MagicMock(status_code=503)
        with patch.object(demo.requests, "get", return_value=response):
            assert demo.check_service_health() is False


class TestEnableAutohealForContainer:
    def test_returns_true_on_200(self):
        response = MagicMock(status_code=200)
        with patch.object(demo.requests, "post", return_value=response):
            assert demo.enable_autoheal_for_container("abc123") is True

    def test_returns_false_on_non_200(self):
        response = MagicMock(status_code=400)
        with patch.object(demo.requests, "post", return_value=response):
            assert demo.enable_autoheal_for_container("abc123") is False


class TestAddHttpHealthCheck:
    def test_returns_true_on_200(self):
        response = MagicMock(status_code=200)
        with patch.object(demo.requests, "post", return_value=response):
            assert demo.add_http_health_check("abc123", "/health") is True

    def test_returns_false_on_non_200(self):
        response = MagicMock(status_code=400)
        with patch.object(demo.requests, "post", return_value=response):
            assert demo.add_http_health_check("abc123", "/health") is False


class TestExportConfig:
    def test_returns_filename_on_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        response = MagicMock(status_code=200)
        response.json.return_value = {"monitor": {}}
        with patch.object(demo.requests, "get", return_value=response):
            filename = demo.export_config()

        assert filename is not None
        assert (tmp_path / filename).exists()

    def test_returns_none_on_non_200(self):
        response = MagicMock(status_code=500)
        with patch.object(demo.requests, "get", return_value=response):
            assert demo.export_config() is None
