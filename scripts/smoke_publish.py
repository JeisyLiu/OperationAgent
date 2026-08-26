"""End-to-end smoke: create publish job(s) and wait for terminal status."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

TERMINAL = {"SUCCESS", "FAILED", "DEAD", "CANCELLED"}


def wait_for_job(base_url: str, job_id: int, timeout: int) -> dict:
    deadline = time.time() + timeout
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        while time.time() < deadline:
            resp = client.get(f"/api/jobs/{job_id}")
            resp.raise_for_status()
            job = resp.json()
            status = job["status"]
            print(f"[{datetime.now(timezone.utc).isoformat()}] job={job_id} status={status}")
            if status in TERMINAL:
                return job
            time.sleep(3)
    raise TimeoutError(f"Job {job_id} did not reach terminal status within {timeout}s")


def check_readiness(base_url: str) -> dict:
    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        resp = client.get("/api/health/readiness")
        resp.raise_for_status()
        return resp.json()


def print_readiness(report: dict) -> bool:
    print("=== Readiness ===")
    for check in report.get("checks", []):
        mark = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(check["status"], "?")
        print(f"  [{mark}] {check['id']}: {check['message']}")
        if check.get("fix") and check["status"] != "ok":
            for line in str(check["fix"]).splitlines():
                print(f"        fix: {line}")
    print(f"ready={report.get('ready')} adapter={report.get('adapter')}")
    return bool(report.get("ready"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke publish: Job -> SUCCESS/FAILED")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--variant-id", type=int, required=True)
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--runs", type=int, default=1, help="Consecutive publish runs (MVP: >=3)")
    parser.add_argument("--skip-readiness", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write JSON summary (success rate, job ids)",
    )
    args = parser.parse_args()

    if not args.skip_readiness:
        try:
            readiness = check_readiness(args.base_url)
            ok = print_readiness(readiness)
            if not ok:
                print("Readiness failed — fix issues above or pass --skip-readiness")
                return 2
        except httpx.HTTPError as exc:
            print(f"Readiness check failed: {exc}")
            return 2

    results: list[dict] = []
    for run in range(1, args.runs + 1):
        print(f"\n=== Run {run}/{args.runs} ===")
        payload = {
            "content_variant_id": args.variant_id,
            "account_id": args.account_id,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
        }
        with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
            create = client.post("/api/jobs", json=payload)
            create.raise_for_status()
            job = create.json()
            job_id = job["id"]
            print("created job:", job_id)

        final = wait_for_job(args.base_url, job_id, args.timeout)
        logs = httpx.get(f"{args.base_url}/api/jobs/{job_id}/logs").json()
        entry = {
            "run": run,
            "job_id": job_id,
            "status": final["status"],
            "error_message": final.get("error_message"),
            "log_count": len(logs),
        }
        results.append(entry)
        print("final:", entry)

    successes = sum(1 for r in results if r["status"] == "SUCCESS")
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runs": args.runs,
        "successes": successes,
        "success_rate": successes / args.runs if args.runs else 0,
        "variant_id": args.variant_id,
        "account_id": args.account_id,
        "results": results,
    }
    print(f"\n=== Summary: {successes}/{args.runs} SUCCESS ===")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Report written: {args.report}")

    if successes == args.runs:
        print("SMOKE PASS")
        return 0
    print("SMOKE FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
