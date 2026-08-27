# OperationAgent

Local AI social media operator — runs entirely on your machine.

This is a **single-machine** app: one local process, SQLite database under `data/`, browser profiles, and a pluggable Agent adapter on disk. It is **not** a cloud backend.

## Requirements

- Python 3.11+
- Windows / macOS / Linux
- Playwright Chromium (`playwright install chromium`)
- LLM API key optional (Settings → LLM pool; only needed for AI generate / rewrite)

## Quick start (one click)

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

**Start everything (server + open UI):**

```bash
python -m app.launcher
```

Windows double-click:

```powershell
powershell -File scripts/start.ps1
```

No second terminal, no manual Chrome CDP, no `--reload`.

## First-time use

1. App opens at **http://127.0.0.1:8000/**
2. **Accounts** → add platform → **登录并启用** → complete login in the opened browser → confirm in app
3. **Content** → upload → create variant → **Queue**
4. Wait for **SUCCESS**; view steps/screenshots in **History**

Login and captcha happen only once per account. Publishing runs unattended afterward.

## Environment

`.env` is auto-created from `.env.example` on first launch.

```text
APP_DATA_DIR=./data
AGENT_ADAPTER=stagehand
```

Use `AGENT_ADAPTER=mock` for queue testing without a real browser.

### Agent adapters

| `AGENT_ADAPTER` | When to use |
|-----------------|-------------|
| `stagehand` | **Default**; same browser profile as login (`data/profiles/...`) |
| `browser_use` | Autonomous browser-use + persistent profile |
| `chrome_devtools` | Attach to Chrome CDP (auto-started when needed) |
| `openclaw` | External OpenClaw CLI/HTTP gateway |
| `mock` | Tests / queue dry-run |

Infra degrade chain: `browser_use` → `stagehand`.  
Platforms may set `preferred_adapter` in catalog (e.g. RedNote → `chrome_devtools`).

## Smoke script (MVP acceptance)

```bash
python scripts/smoke_publish.py --variant-id 1 --account-id 1 --runs 3 --report data/smoke_report.json
```

Or:

```powershell
powershell -File scripts/run_mvp_smoke.ps1 -VariantId 1 -AccountId 1
```

## Worker controls

- UI footer: **Pause** / **Stop**
- API: `GET /api/worker/status`, pause/stop

## Verify

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/health/readiness
```

## Key APIs

| Area | Endpoints |
|------|-----------|
| Health | `GET /health`, `GET /api/health/readiness`, `POST /api/health/heal` |
| Accounts | `POST .../login-and-activate`, `.../mark-active` |
| Jobs | create, detail, logs, republish |
| Worker | status, pause, stop |

## Architecture

```text
UI → FastAPI → Channel → AgentAdapter (stagehand) → Playwright persistent profile
```

Login and publish share the same `data/profiles/...` session.

## MVP 0.2.0 hypothesis

**Hypothesis:** A local operator can publish from persisted browser profiles with one-click startup and acceptable reliability.

**Conclusion:** **Partially validated** — one-click launcher, unified login flow, profile-aligned stagehand path, and self-heal readiness are in place. Run `smoke_publish.py --runs 3` locally to confirm platform SUCCESS.

Known issues: [version/KNOWN_ISSUES.md](./version/KNOWN_ISSUES.md)

## Documentation

| Document | Purpose |
|----------|---------|
| [version/0.2.0](./version/0.2.0) | MVP freeze checklist |
| [version/KNOWN_ISSUES.md](./version/KNOWN_ISSUES.md) | Environment blockers |

## Current version

**v0.2.0** — one-click launcher, stagehand default, login-and-activate, auto-heal readiness.
