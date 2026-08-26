# Known issues (MVP 0.2.0)

Environment and reliability blockers tracked for the core hypothesis. Update when smoke runs complete.

## P0 — blocks「无人值守真实发布」

| Issue | Symptom | Mitigation |
|-------|---------|------------|
| Windows + `uvicorn --reload` | Playwright `NotImplementedError` in worker; job FAILED with empty or infra message | Start without reload: `scripts/start_server.ps1` or `uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| Chrome CDP not running | `Cannot connect to Chrome DevTools at http://127.0.0.1:9222` | `scripts/start_chrome_cdp.ps1` before publish |
| Duplicate server / stale lock | Worker not running; jobs stuck QUEUED | One uvicorn only; remove stale `data/.worker.lock` if no process holds it |
| Login session expired | Agent cannot find upload UI; WAITING_HUMAN or FAILED | Accounts → Open profile → re-login → Mark active → retry job |
| Generic channel untested | Non-TikTok publish may fail verification | MVP acceptance uses **TikTok** (dedicated Channel) first |

## P1 — UX / observability

| Issue | Symptom | Mitigation |
|-------|---------|------------|
| Empty `error_message` on infra fail | History shows failed with no text | Fixed in worker via `ensure_failure_message`; re-run on latest code |
| LLM not configured | Skill generate / rewrite fails | Settings → enable LLM pool entry |
| `media_path=None` text posts | Upload step may skip file picker | Use video asset for TikTok MVP smoke |

## Smoke acceptance (fill after local runs)

```text
Date:
Machine:
Adapter: chrome_devtools
Platform: TikTok
Runs: 3
SUCCESS: _ / 3
Platform visible: yes / no
Notes:
```

Command:

```bash
python scripts/smoke_publish.py --variant-id N --account-id M --runs 3 --report data/smoke_report.json
```

## Not MVP blockers

- Multi-platform simultaneous reliability
- Comment reply, analytics, AI scheduling
- OCR / PyAutoGUI primary path
- Cloud multi-tenant deployment
