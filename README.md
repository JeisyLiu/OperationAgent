# OperationAgent

Local AI social media operator — runs entirely on your machine.

This is a **single-machine** app: one local process, SQLite database under `data/`, browser profiles, and a pluggable Agent adapter on disk. It is **not** a cloud backend.

## Requirements

- Python 3.11+
- Windows / macOS / Linux
- Google Chrome (for default `chrome_devtools` adapter)
- LLM API key (Settings → LLM pool; optional for queue-only / mock tests)

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python scripts/init_db.py
copy .env.example .env          # macOS/Linux: cp .env.example .env
playwright install chromium
```

**Start API (do not use `--reload` on Windows — Playwright subprocess will fail):**

```bash
# Windows helper:
powershell -File scripts/start_server.ps1

# Or directly:
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Start Chrome with remote debugging (required for default adapter):**

```powershell
powershell -File scripts/start_chrome_cdp.ps1
```

Open **http://127.0.0.1:8000/** — Dashboard shows a **系统自检** panel (CDP, worker, LLM, ACTIVE accounts).

## Environment

`.env` example:

```text
APP_DATA_DIR=./data
AGENT_ADAPTER=chrome_devtools
CHROME_DEVTOOLS_URL=http://127.0.0.1:9222
```

Use `AGENT_ADAPTER=mock` for queue testing without a real browser agent.

### Agent adapters

| `AGENT_ADAPTER` | When to use |
|-----------------|-------------|
| `chrome_devtools` | **Default**; attach to your Chrome (`--remote-debugging-port=9222`) |
| `browser_use` | Autonomous browser-use + persistent profile |
| `stagehand` | Observe-act-verify tool loop; more deterministic |
| `openclaw` | External OpenClaw CLI/HTTP gateway |
| `mock` | Tests / queue dry-run |

Infra failure degrade chain: `browser_use` → `stagehand` → `chrome_devtools` (logged as Step `fallback`).
Platforms may set `preferred_adapter` in catalog (e.g. RedNote → `chrome_devtools`).

**Windows:** never run `uvicorn --reload` when publishing. Use the command above or `scripts/start_server.ps1`.

## First-time publish (no code)

1. Start server + Chrome CDP (see Quick start).
2. **Settings** — add at least one enabled LLM config (for Skill generate / rewrite; optional for manual variants).
3. **Accounts** — add TikTok (or target platform) → **Open profile** → log in manually (captcha here only) → **Mark active**.
4. **Content** — upload video → create variant with title/caption.
5. **Queue** — schedule job with variant + active account.
6. Wait for **SUCCESS** on Dashboard / Queue; screenshots under **History**.

Login and captcha happen only during step 3. Publishing runs unattended.

## Account Skill + multi-account workflow

1. **Accounts** — configure Skill (tone, audience, taboos, extra prompt) per account
2. **Content** — upload Asset → select ACTIVE accounts → **Generate variants**
3. Review generated variants → **Enqueue selected** (publishable platforms)
4. Worker runs jobs automatically

## Smoke script (MVP acceptance)

Preflight + consecutive runs (target ≥3 SUCCESS):

```bash
python scripts/smoke_publish.py --variant-id 1 --account-id 1 --runs 3 --report data/smoke_report.json
```

Requires: server running, Chrome CDP up, ACTIVE account, valid variant. Fix failures using Dashboard **系统自检** or `GET /api/health/readiness`.

## Worker controls

- UI footer: **Pause** / **Stop** for the current agent run
- API: `GET /api/worker/status`, `POST /api/worker/pause`, `POST /api/worker/stop`

## Verify

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/health/readiness
```

## Key APIs

| Area | Endpoints |
|------|-----------|
| Health | `GET /health`, `GET /api/health/readiness` |
| Settings | `GET/PUT /api/settings/ai`, `POST /api/settings/ai/test` |
| LLM pool | `GET/POST /api/llm-models`, test/update/delete |
| Accounts | `GET/POST /api/accounts`, `POST .../open-profile`, `.../mark-active` |
| Content | `GET/POST /api/content/assets`, upload, variants, `POST .../generate-variants` |
| Jobs | `GET/POST /api/jobs`, detail/logs, cancel/retry/republish |
| Worker | `GET /api/worker/status`, pause/stop |
| Platforms | `GET /api/platforms` |

## Platforms

Supported platforms are defined in [`app/platforms/*.json`](app/platforms/).

- **Login ready:** all enabled platforms in the catalog
- **Publishing:** TikTok has a dedicated Channel; other platforms use **GenericAgentChannel** (LLM + adapter driven — less battle-tested than TikTok)

To add a platform: add JSON under `app/platforms/`, optionally implement a dedicated Channel.

## Local data layout

```text
data/
├── app.db
├── profiles/
├── content/
├── execution/
└── .worker.lock
```

## Architecture

```text
UI → FastAPI /api/* → services → Channel.publish → AgentAdapter → Playwright / CDP / browser-use
```

Default execution path (MVP): **`chrome_devtools`** → user Chrome via CDP → shared tool loop.

See [version/BUILD_VS_BUY.md](./version/BUILD_VS_BUY.md) for build vs reuse boundaries.

## MVP 0.2.0 hypothesis

**Hypothesis:** A local operator can publish to a social platform from persisted browser profiles with acceptable reliability, without official APIs or a custom agent framework.

**Conclusion (MVP):** **Partially validated** — queue, profiles, Channel orchestration, adapter fallback, Step Line, republish, and self-heal readiness are in place. Real platform SUCCESS depends on environment (CDP Chrome, logged-in profile, stable UI). Run `scripts/smoke_publish.py --runs 3` locally and verify content on the platform.

We do **not** bypass captchas during publish. If login expires, re-open the profile and mark active, then retry.

Known issues: [version/KNOWN_ISSUES.md](./version/KNOWN_ISSUES.md)

## Documentation

| Document | Purpose |
|----------|---------|
| [TODO.md](./TODO.md) | Product requirements and implementation plan |
| [version/README.md](./version/README.md) | Version roadmap |
| [version/BUILD_VS_BUY.md](./version/BUILD_VS_BUY.md) | Build vs reuse |
| [version/0.2.0](./version/0.2.0) | MVP freeze checklist |
| [version/KNOWN_ISSUES.md](./version/KNOWN_ISSUES.md) | Environment & reliability blockers |

## Current version

**v0.2.0** — chrome_devtools default path, readiness preflight, smoke `--runs`, MVP gap closure.
