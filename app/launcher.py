"""One-click launcher: setup env, start API server, open UI."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("OA_HOST", "127.0.0.1")
PORT = int(os.environ.get("OA_PORT", "8000"))
BASE_URL = f"http://{HOST}:{PORT}"


def ensure_env() -> None:
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_path.exists() and example.exists():
        shutil.copy(example, env_path)
        print(f"Created {env_path} from .env.example")


def ensure_data() -> None:
    from app.config import settings
    from app.db.models import Base
    from app.db.session import engine

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def wait_for_health(timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{BASE_URL}/health")
                if resp.status_code == 200:
                    return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    os.chdir(ROOT)
    ensure_env()
    ensure_data()

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]
    proc = subprocess.Popen(cmd, cwd=str(ROOT))

    def cleanup(*_args) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def handle_signal(signum, frame) -> None:  # noqa: ARG001
        cleanup()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    print(f"Starting OperationAgent at {BASE_URL} ...")
    if not wait_for_health():
        cleanup()
        print("Server failed to start within timeout", file=sys.stderr)
        return 1

    print(f"Opening {BASE_URL}")
    webbrowser.open(BASE_URL)

    try:
        return proc.wait()
    except KeyboardInterrupt:
        cleanup()
        return 0


if __name__ == "__main__":
    sys.exit(main())
