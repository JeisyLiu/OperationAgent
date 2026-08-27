"""Bootstrap auto-setup tests."""

from app.bootstrap import BootstrapReport, BootstrapStep, ensure_env_file, deps_missing


def test_ensure_env_file_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.bootstrap.ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("AGENT_ADAPTER=stagehand\n", encoding="utf-8")
    step1 = ensure_env_file()
    assert step1.ok
    step2 = ensure_env_file()
    assert step2.ok
    assert (tmp_path / ".env").exists()


def test_deps_missing_returns_list():
    missing = deps_missing()
    assert isinstance(missing, list)


def test_bootstrap_report_print(capsys):
    report = BootstrapReport(
        ok=True,
        steps=[BootstrapStep("env", True, "ok")],
    )
    report.print()
    out = capsys.readouterr().out
    assert "[OK]" in out
