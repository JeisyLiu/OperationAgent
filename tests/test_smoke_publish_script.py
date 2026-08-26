"""Unit tests for smoke_publish helpers (no live server)."""

from scripts.smoke_publish import TERMINAL


def test_terminal_statuses_include_success_and_failed():
    assert "SUCCESS" in TERMINAL
    assert "FAILED" in TERMINAL
    assert "QUEUED" not in TERMINAL
