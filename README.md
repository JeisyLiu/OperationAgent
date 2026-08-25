# OperationAgent

Local AI social media operator — runs entirely on your machine.

This is a **single-machine** app: one local process, SQLite database under `data/`, browser profiles, and browser-use Agent on disk. It is **not** a cloud backend.

## Requirements

- Python 3.11+
- Windows / macOS / Linux
- OpenAI-compatible API key (for browser-use tasks)

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts/init_db.py
copy .env.example .env
playwright install chromium
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/** for the local UI.

## Environment

`.env` example:

```text
APP_DATA_DIR=./data
AGENT_ADAPTER=browser_use
```

Use `AGENT_ADAPTER=mock` for queue testing without a real browser agent.

Reserved adapters (not wired in MVP): `openclaw` (stub only; returns a clear failure if selected).

## Account Skill + multi-account workflow

1. **Accounts** — configure Skill (tone, audience, taboos, extra prompt) per account
2. **Content** — upload Asset → select ACTIVE accounts → **Generate variants**
3. Review generated variants → **Enqueue selected** (publishable platforms only, e.g. TikTok)
4. Worker runs jobs automatically; non-publishable platforms can still generate/login-only variants

## First-time publish (no code)
2. **Accounts** — add a TikTok account → **Open profile** → log in manually (complete any captcha here) → **Mark active**.
3. **Content** — upload a video → create a TikTok variant with title/caption.
4. **Queue** — schedule a job with the variant ID and active account ID.
5. Wait for **SUCCESS** on Dashboard or Queue. View screenshots under **History**.

Login and captcha happen only during step 2. Publishing runs unattended.

## Smoke script

```bash
python scripts/smoke_publish.py --variant-id 1 --account-id 1
```

## Worker controls

- UI footer: **Pause** / **Stop** for the current agent run
- API: `GET /api/worker/status`, `POST /api/worker/pause`, `POST /api/worker/stop`

## Verify

```bash
curl http://127.0.0.1:8000/health
```

Expected: `{"status":"ok","version":"0.2.0"}`

## Key APIs

| Area | Endpoints |
|------|-----------|
| Settings | `GET/PUT /api/settings/ai`, `POST /api/settings/ai/test` |
| Accounts | `GET/POST /api/accounts`, `POST .../open-profile`, `.../mark-active` |
| Content | `GET/POST /api/content/assets`, upload, variants, `POST .../generate-variants` |
| Jobs | `GET/POST /api/jobs`, `POST /api/jobs/bulk`, cancel/retry/logs |
| Worker | `GET /api/worker/status`, pause/stop |
| Platforms | `GET /api/platforms` |

## Platforms

Supported platforms are defined in [`app/platforms/*.json`](app/platforms/). The UI shows a dropdown from this catalog instead of free-text platform names.

- **Login ready:** all enabled platforms in the catalog (TikTok, Douyin, Kuaishou, YouTube, X/Twitter, Instagram, Facebook, Reddit, Bilibili, RedNote, Zhihu, Weibo)
- **Publishing ready:** only platforms with a Channel implementation (currently **TikTok**)

To add a platform later: add a JSON file under `app/platforms/`, then implement a Channel when publishing is needed.

Invalid legacy accounts (bad platform slug) can be removed with `DELETE /api/accounts/{id}`.

## Local data layout

```text
data/
├── app.db
├── profiles/
├── content/
└── execution/
```

## Architecture

```text
UI → FastAPI /api/* → services → Channel.publish → AgentAdapter → Playwright/browser-use
```

See [version/BUILD_VS_BUY.md](./version/BUILD_VS_BUY.md) for build vs reuse boundaries.

## MVP 0.2.0 hypothesis

**Hypothesis:** A local browser-use operator can publish to TikTok from persisted Playwright profiles with acceptable reliability, without official APIs or a custom agent framework.

**Conclusion (MVP):** **Partially validated** — queue, profiles, Channel orchestration, failure classification, UI, and Pause/Stop are in place; real TikTok SUCCESS depends on your environment (logged-in profile, stable UI, model quality). Re-run `scripts/smoke_publish.py` locally to confirm on your machine.

We do **not** bypass captchas during publish. If login expires, re-open the profile and mark active, then retry the job.

## Documentation

| Document | Purpose |
|----------|---------|
| [TODO.md](./TODO.md) | Product requirements and implementation plan |
| [version/README.md](./version/README.md) | Version roadmap |
| [version/BUILD_VS_BUY.md](./version/BUILD_VS_BUY.md) | Build vs reuse |
| [version/0.2.0](./version/0.2.0) | MVP freeze checklist |

## Current version

**v0.2.0** — TikTok Channel publish loop, static UI, worker controls, MVP freeze.
