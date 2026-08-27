# OperationAgent

Local AI social media operator — runs entirely on your machine.

## Prerequisite (only this)

- **Python 3.11+** installed and on PATH  
  Download: https://www.python.org/downloads/

Everything else (venv、pip 依赖、`.env`、数据库、Playwright 浏览器) is installed **automatically** on first start.

## One-click start

**Windows（推荐双击 / 右键用 PowerShell 运行）：**

```powershell
powershell -File scripts/start.ps1
```

**macOS / Linux：**

```bash
bash scripts/start.sh
```

或已有 venv 时：

```bash
python -m app.launcher
```

首次启动会自动：

1. 创建 `.venv`（若还没有）
2. `pip install -e .`
3. 复制 `.env.example` → `.env`
4. 初始化 `data/` 与 SQLite
5. 下载 Playwright Chromium（若缺失）
6. 启动服务并打开浏览器 UI

无需手动 `playwright install`，无需第二终端起 Chrome。

## First-time use

1. 应用打开 **http://127.0.0.1:8000/**
2. **Accounts** → 添加账号 → **登录并启用**（仅首次做人机）
3. **Content** → 上传 → 入队 → 等待 SUCCESS

## Environment

`.env` 首次自动生成。默认：

```text
APP_DATA_DIR=./data
AGENT_ADAPTER=stagehand
```

| `AGENT_ADAPTER` | 说明 |
|-----------------|------|
| `stagehand` | **默认**；与登录同一 `data/profiles/...` |
| `browser_use` | browser-use 自主路径 |
| `chrome_devtools` | CDP；程序按需自动起 Chrome |
| `mock` | 仅测队列 |

## Smoke（可选验收）

```bash
python scripts/smoke_publish.py --variant-id 1 --account-id 1 --runs 3 --report data/smoke_report.json
```

## What the program auto-manages vs what only you can do

| 自动 | 须用户 |
|------|--------|
| venv / pip 依赖 | 安装系统 Python |
| Playwright Chromium | 平台首次登录 / 验证码 |
| `.env`、数据库目录 | LLM API Key（若要用 AI 生成） |
| Worker 锁自愈、按需 CDP Chrome | — |

## Docs

| Document | Purpose |
|----------|---------|
| [version/0.2.0](./version/0.2.0) | MVP checklist |
| [version/KNOWN_ISSUES.md](./version/KNOWN_ISSUES.md) | Blockers |

**v0.2.0** — one-click bootstrap + stagehand default + login-and-activate.
