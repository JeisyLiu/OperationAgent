"""Tests for one-click launcher helpers."""

from pathlib import Path

from app.launcher import ensure_env, ROOT


def test_ensure_env_creates_from_example(tmp_path, monkeypatch):
    example = tmp_path / ".env.example"
    example.write_text("AGENT_ADAPTER=stagehand\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.launcher.ROOT", tmp_path)
    ensure_env()
    assert (tmp_path / ".env").exists()


def test_launcher_root_points_to_repo():
    assert (ROOT / "app").is_dir()
    assert (ROOT / "pyproject.toml").exists() or (ROOT / "app" / "main.py").exists()
