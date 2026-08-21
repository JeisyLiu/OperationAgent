# 版本路线图（→ MVP 0.2.0）

当前起点：`0.1.1`  
MVP 终点：`0.2.0`  
文档修订：纳入「自研 vs 复用」评测结论（默认 Agent = **browser-use**）

每个文件对应一个可独立交付、可验收的小版本。版本之间严格按依赖递进，**禁止跨层耦合**。

```text
0.1.1  工程脚手架 + 进程骨架
  ↓
0.1.2  数据层 + AI Settings（LLM 薄封装）
  ↓
0.1.3  账号池 + Browser Profile（仅登录需人机校验）
  ↓
0.1.4  内容池 + Content Variant
  ↓
0.1.5  发布队列 + Scheduler（MockAgent 跑通状态机）
  ↓
0.1.6  AgentAdapter + browser-use（默认）+ Runtime 薄封装
  ↓
0.1.7  TikTokChannel 真实发布闭环（无人值守）
  ↓
0.1.8  简易 UI + Pause/Stop + 稳定性
  ↓
0.2.0  MVP 冻结发布
```

## 解耦铁律（各版本共用）

| 边界 | 规则 |
|------|------|
| Account ≠ Device / Channel | 账号只绑 Profile，不含平台操作逻辑 |
| Content ≠ PublishJob | Asset / Variant / Job 三表分离 |
| Business ≠ Agent 产品 | 只依赖 `AgentAdapter`；默认 browser-use |
| Channel ≠ 点击细节 | Channel 只编排；页面操作交给 Agent |
| Runtime 薄封装 | 不重写 Playwright；OCR/PyAutoGUI 不进 MVP |
| 人机校验 | 仅首次登录（及登录失效重登）；发布全自动 |

## 自研 / 复用（速查）

详见 [BUILD_VS_BUY.md](./BUILD_VS_BUY.md)。

| 类型 | 内容 |
|------|------|
| **自研** | Settings、账号池、内容池、队列、Channel、UI、AgentAdapter 胶水 |
| **复用** | browser-use、Playwright、FastAPI、SQLAlchemy、SQLite、LLM SDK |
| **暂缓** | Hermes/OpenClaw、OCR/PyAutoGUI、CustomAgent |
| **不当底座** | Postiz/Mixpost 等官方 API 排程产品 |

## 文件说明

| 文件 | 目标一句话 |
|------|------------|
| [0.1.1](./0.1.1) | 可启动的空壳服务 |
| [0.1.2](./0.1.2) | 本地库 + AI Key 可测通 |
| [0.1.3](./0.1.3) | Profile 登录持久化 |
| [0.1.4](./0.1.4) | 视频入库 + 平台变体 |
| [0.1.5](./0.1.5) | Job 队列自动消费（Mock） |
| [0.1.6](./0.1.6) | browser-use Adapter 可跑通 |
| [0.1.7](./0.1.7) | TikTok 真发帖 SUCCESS |
| [0.1.8](./0.1.8) | UI 走通主流程 |
| [0.2.0](./0.2.0) | MVP DoD 全部勾选 |

详细产品设计见仓库根目录 `TODO.md`。
