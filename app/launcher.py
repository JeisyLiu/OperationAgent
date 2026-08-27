"""One-click launcher: bootstrap env, start API, open UI."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("OA_HOST", "127.0.0.1")
PORT = int(os.environ.get("OA_PORT", "8000"))
BASE_URL = f"http://{HOST}:{PORT}"


def wait_for_health(timeout: float = 90.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{BASE_URL}/health")
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    os.chdir(ROOT)

    print("=== OperationAgent bootstrap ===")
    from app.bootstrap import run_bootstrap

    report = run_bootstrap(install_deps=True, install_browser=True)
    report.print()
    if not report.ok:
        print("Bootstrap failed. Fix network/Python and run again.", file=sys.stderr)
        return 1

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
