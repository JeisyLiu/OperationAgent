"""End-to-end smoke: create a publish job and wait for terminal status."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

import httpx


def wait_for_job(base_url: str, job_id: int, timeout: int) -> dict:
    terminal = {"SUCCESS", "FAILED", "DEAD", "CANCELLED"}
    deadline = time.time() + timeout
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        while time.time() < deadline:
            resp = client.get(f"/api/jobs/{job_id}")
            resp.raise_for_status()
            job = resp.json()
            status = job["status"]
            print(f"[{datetime.now(timezone.utc).isoformat()}] job={job_id} status={status}")
            if status in terminal:
                return job
            time.sleep(3)
    raise TimeoutError(f"Job {job_id} did not reach terminal status within {timeout}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke publish: Job -> SUCCESS/FAILED")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--variant-id", type=int, required=True)
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    payload = {
        "content_variant_id": args.variant_id,
        "account_id": args.account_id,
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        health = client.get("/health")
        health.raise_for_status()
        print("health:", health.json())

        create = client.post("/api/jobs", json=payload)
        create.raise_for_status()
        job = create.json()
        job_id = job["id"]
        print("created job:", job_id)

    final = wait_for_job(args.base_url, job_id, args.timeout)
    print("final job:", final)
    logs = httpx.get(f"{args.base_url}/api/jobs/{job_id}/logs").json()
    print("logs:", len(logs), "entries")

    if final["status"] == "SUCCESS":
        print("SMOKE PASS")
        return 0

    print("SMOKE FAIL:", final.get("error_message"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
