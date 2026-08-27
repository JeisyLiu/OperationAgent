# Known issues (MVP 0.2.0)

## P0 — blocks「无人值守真实发布」

| Issue | Symptom | Mitigation |
|-------|---------|------------|
| Login session expired | Upload UI not found; WAITING_HUMAN / FAILED | Accounts →「登录并启用」→ retry job |
| Duplicate server / stale lock | Jobs stuck QUEUED | Close extra app windows; delete stale `data/.worker.lock` |
| Generic channel untested | Non-TikTok may fail verification | MVP smoke on **TikTok** first |
| Manual `uvicorn --reload` | Playwright `NotImplementedError` on Windows | Use `python -m app.launcher` only |

## P1 — UX

| Issue | Symptom | Mitigation |
|-------|---------|------------|
| LLM not configured | Skill generate / rewrite fails | Settings → enable LLM pool |
| `media_path=None` | Text-only posts may skip upload | Use video for TikTok MVP smoke |

## Smoke acceptance (fill after local runs)

```text
Date:
Machine:
Launcher: python -m app.launcher
Adapter: stagehand
Platform: TikTok
Runs: 3
SUCCESS: _ / 3
Platform visible: yes / no
```

```bash
python scripts/smoke_publish.py --variant-id N --account-id M --runs 3 --report data/smoke_report.json
```

## Not MVP blockers

- `.exe` installer packaging
- Auto captcha bypass
- Multi-platform simultaneous reliability
