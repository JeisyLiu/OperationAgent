# 自研 vs 复用（Build vs Buy）

> 评测结论写入迭代计划；开发时以本文件为准，避免重复造轮子或路线跑偏。

---

## 1. 必须自研（产品差异化）

| 模块 | 原因 |
|------|------|
| AI Settings（本地 Key、脱敏、连通测试） | 本地单机产品配置面 |
| 账号池 + Profile 绑定 | Account ≠ Device/Channel；不存密码 |
| 内容池 + Content Variant | 与 Job 三分离 |
| 发布队列 + 状态机 + Worker | PENDING→…→SUCCESS/DEAD；单机认领 |
| Channel 编排（TikTok…） | 组装任务、校验结果、失败分类 |
| 执行日志 / 截图回放 | 按 Job 可审计 |
| 产品 UI 与首次登录引导 | 体验：「登录做人机 → 发布无人值守」 |
| `AgentAdapter` 薄胶水 | 屏蔽 browser-use 等具体 SDK |

---

## 2. 直接复用（不要自研）

| 能力 | 推荐开源 | 说明 |
|------|----------|------|
| Agent 大脑 | **browser-use**（默认） | Python + Playwright，本地任务最贴合 |
| Agent 备选 | Stagehand 风格 tool loop | Playwright + LLM 结构化动作；`AGENT_ADAPTER=stagehand` |
| 真 Chrome 备用 | Chrome DevTools CDP | 附着用户 Chrome；`AGENT_ADAPTER=chrome_devtools` |
| 浏览器驱动 | Playwright | persistent Profile；多由 Agent 库携带 |
| HTTP API | FastAPI + Uvicorn | |
| ORM / DB | SQLAlchemy + SQLite | 禁止一上来上 PG/Redis |
| LLM 多厂商 | OpenAI 兼容 SDK 或 LiteLLM | 薄封装即可 |
| 定时轮询 | asyncio / APScheduler | 不要 Temporal/Celery |

可选后补 Adapter（非 MVP 阻塞）：

- Hermes  
- OpenClaw（`AGENT_ADAPTER=openclaw`，CLI/HTTP 已接线）

明确延期（不进当前执行层）：

- MobileAdapter（ADB / UiAutomator2 / Appium）
- Sonic 云真机设备池  
- 触发条件：目标动作仅 App 内存在，且 Account 模型扩展为 Device Session

---

## 3. MVP 明确暂缓

| 项 | 原因 |
|----|------|
| CustomAgentAdapter（自研 LLM+工具循环） | 已由 `tool_loop` + stagehand/chrome_devtools 覆盖轻量循环 |
| OpenCV / PaddleOCR / PyAutoGUI | DOM 路径优先；降级留到 MVP 后 |
| Hermes/OpenClaw 作为默认 | 更重、集成面更大；作第二后端即可 |
| Sonic / ADB 云真机作为默认 | 与本机 Profile 产品路径不同；延期 |
| 多平台 Channel 并行开工 | 先 TikTok 闭环 |

---

## 4. 不当作执行底座

| 项目类型 | 例子 | 原因 |
|----------|------|------|
| 官方 API 社媒排程 | Postiz、Mixpost、BrightBean | OAuth/API 路径，不是本地浏览器 Operator |
| 纯脚本发帖工具 | AutoSocial 等 | 可参考 Profile/队列，不可替代 AI Agent 层 |

可作竞品/交互参考，**不要整仓替换本架构**。

---

## 5. 决策树（Agent 层）

```text
需要执行网页发布？
    ↓
实现 AgentAdapter
    ↓
默认 BrowserUseAdapter + 已登录 Profile
    ↓
不稳定？ → 试 StagehandAdapter
    ↓
仍不行？ → 再评估 Hermes/OpenClaw
    ↓
仍不行？ → 才考虑 CustomAgent（需书面记录原因）
```

---

## 6. 一句话

> **队列里发什么、用谁号、何时发、如何记 —— 自研。**  
> **网页上怎么点 —— 复用 browser-use（等），不自研 Agent Framework。**
