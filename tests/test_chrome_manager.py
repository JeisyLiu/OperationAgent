"""Tests for chrome_manager CDP helpers."""

from unittest.mock import patch

from app.services.chrome_manager import is_cdp_reachable


def test_is_cdp_reachable_false_when_unreachable():
    with patch("app.services.chrome_manager.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = OSError("refused")
        assert is_cdp_reachable("http://127.0.0.1:9222") is False


def test_is_cdp_reachable_true_on_200():
    with patch("app.services.chrome_manager.httpx.Client") as mock_client:
        resp = mock_client.return_value.__enter__.return_value.get.return_value
        resp.status_code = 200
        assert is_cdp_reachable("http://127.0.0.1:9222") is True
