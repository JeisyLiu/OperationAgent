# OperationAgent

Local AI social media operator — runs entirely on your machine.

This is a **single-machine** app: one local process, SQLite database under `data/`, browser profiles, and optional browser-use Agent on disk. It is **not** a cloud backend.

## Requirements

- Python 3.11+
- Windows / macOS / Linux

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts/init_db.py
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Browser dependencies (0.1.3+)

```bash
playwright install chromium
```

## browser-use (0.1.6+, optional real Agent)

Set in `.env`:

```text
AGENT_ADAPTER=browser_use
```

Install browsers as above. See [version/BUILD_VS_BUY.md](./version/BUILD_VS_BUY.md).

## Verify

```bash
curl http://127.0.0.1:8000/health
```

Expected: `{"status":"ok","version":"0.1.6"}`

## Key APIs

| Area | Endpoints |
|------|-----------|
| Settings | `GET/PUT /api/settings/ai`, `POST /api/settings/ai/test` |
| Accounts | `GET/POST /api/accounts`, `POST .../open-profile`, `.../mark-active` |
| Content | `GET/POST /api/content/assets`, upload, variants |
| Jobs | `GET/POST /api/jobs`, cancel/retry/logs |

## Local data layout

```text
data/
├── app.db
├── profiles/
├── content/
└── execution/
```

## Documentation

| Document | Purpose |
|----------|---------|
| [TODO.md](./TODO.md) | Product requirements and implementation plan |
| [version/README.md](./version/README.md) | Version roadmap |
| [version/BUILD_VS_BUY.md](./version/BUILD_VS_BUY.md) | Build vs reuse |

## Current version

**v0.1.6** — Settings, accounts/profiles, content variants, mock job queue, BrowserUseAdapter glue.
