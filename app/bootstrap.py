"""Environment bootstrap — everything the product can install itself.

User should only need: Python 3.11+ on PATH, then scripts/start.ps1 (or python -m app.launcher).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# Critical imports that mean "pip install -e ." succeeded
_REQUIRED_MODULES = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "playwright",
    "httpx",
    "pydantic_settings",
)


@dataclass
class BootstrapStep:
    id: str
    ok: bool
    message: str
    auto: bool = True


@dataclass
class BootstrapReport:
    ok: bool
    steps: list[BootstrapStep] = field(default_factory=list)

    def print(self) -> None:
        for step in self.steps:
            mark = "OK" if step.ok else "FAIL"
            print(f"  [{mark}] {step.id}: {step.message}")


def ensure_env_file() -> BootstrapStep:
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if env_path.exists():
        return BootstrapStep("env", True, ".env 已存在")
    if not example.exists():
        return BootstrapStep("env", False, "缺少 .env.example，无法自动生成配置")
    shutil.copy(example, env_path)
    return BootstrapStep("env", True, "已从 .env.example 创建 .env")


def ensure_data_dir_and_db() -> BootstrapStep:
    try:
        from app.config import settings
        from app.db.migrate import run_migrations
        from app.db.models import Base
        from app.db.session import engine

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        (settings.data_dir / "profiles").mkdir(parents=True, exist_ok=True)
        (settings.data_dir / "content").mkdir(parents=True, exist_ok=True)
        (settings.data_dir / "execution").mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(bind=engine)
        run_migrations()
        return BootstrapStep("database", True, f"数据目录与数据库已就绪（{settings.data_dir}）")
    except Exception as exc:
        return BootstrapStep("database", False, f"初始化数据库失败：{exc}")


def deps_missing() -> list[str]:
    missing: list[str] = []
    for name in _REQUIRED_MODULES:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    return missing


def ensure_python_deps(*, force: bool = False) -> BootstrapStep:
    missing = deps_missing()
    if not missing and not force:
        return BootstrapStep("python_deps", True, "Python 依赖已就绪")

    print("Installing Python package dependencies (pip install -e .)…")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return BootstrapStep("python_deps", False, "pip 安装超时，请检查网络后重试")
    except Exception as exc:
        return BootstrapStep("python_deps", False, f"pip 安装失败：{exc}")

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[-800:]
        return BootstrapStep("python_deps", False, f"pip 安装失败：{err}")

    still = deps_missing()
    if still:
        return BootstrapStep("python_deps", False, f"安装后仍缺模块：{', '.join(still)}")
    return BootstrapStep("python_deps", True, "已自动安装 Python 依赖")


def ensure_playwright_browser() -> BootstrapStep:
    from app.services.playwright_browser import ensure_chromium

    ok, msg = ensure_chromium()
    return BootstrapStep("playwright_browser", ok, msg)


def run_bootstrap(*, install_deps: bool = True, install_browser: bool = True) -> BootstrapReport:
    """Run all auto-install steps. Safe to call on every start."""
    steps: list[BootstrapStep] = []

    steps.append(ensure_env_file())

    if install_deps:
        steps.append(ensure_python_deps())
    else:
        missing = deps_missing()
        steps.append(
            BootstrapStep(
                "python_deps",
                not missing,
                "Python 依赖已就绪" if not missing else f"缺少依赖：{', '.join(missing)}",
            )
        )

    # DB needs deps
    if all(s.ok for s in steps if s.id == "python_deps"):
        steps.append(ensure_data_dir_and_db())
    else:
        steps.append(BootstrapStep("database", False, "跳过：依赖未就绪"))

    if install_browser and all(s.ok for s in steps if s.id == "python_deps"):
        steps.append(ensure_playwright_browser())
    elif install_browser:
        steps.append(BootstrapStep("playwright_browser", False, "跳过：依赖未就绪"))

    ok = all(s.ok for s in steps)
    return BootstrapReport(ok=ok, steps=steps)
