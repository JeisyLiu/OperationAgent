"""Tests for one-click launcher helpers."""

from pathlib import Path

from app.bootstrap import ROOT, ensure_env_file


def test_ensure_env_creates_from_example(tmp_path, monkeypatch):
    example = tmp_path / ".env.example"
    example.write_text("AGENT_ADAPTER=stagehand\n", encoding="utf-8")
    monkeypatch.setattr("app.bootstrap.ROOT", tmp_path)
    step = ensure_env_file()
    assert step.ok
    assert (tmp_path / ".env").exists()


def test_launcher_root_points_to_repo():
    assert (ROOT / "app").is_dir()
    assert (ROOT / "pyproject.toml").exists() or (ROOT / "app" / "main.py").exists()
