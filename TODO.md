# AI 单机运营自动化工具——产品需求、架构设计与 MVP 落地方案

## 一、项目目标

开发一个运行在用户本地电脑上的 AI 运营自动化工具。

核心目标不是接入各个平台的官方 API，而是通过**当前电脑已有的浏览器环境**，让 AI Agent 像真人一样完成社交媒体平台的运营操作。

用户只需要：

1. 配置 AI 模型 API Key；
2. 在本机浏览器中登录自己的平台账号；
3. 将账号加入本地账号池；
4. 将视频、图片、文案等内容加入内容池；
5. 创建发布任务或让 AI 自动规划任务；
6. 系统将任务放入发布内容消费队列；
7. Agent 调用浏览器操作能力完成实际发布；
8. 记录任务执行结果。

第一阶段只做**单机 MVP**，不做云端集群、不做多设备调度、不做复杂微服务。

---

# 二、产品核心定位

产品定位：

> **运行在用户自己电脑上的 AI Social Media Operator。**

它不是传统的社交媒体 API 管理平台，也不是简单的批量发帖机器人。

核心模式是：

```text
用户提供账号
      ↓
用户提供内容
      ↓
AI制定/执行运营任务
      ↓
任务进入消费队列
      ↓
Agent操作当前电脑浏览器
      ↓
完成发布
      ↓
验证结果
      ↓
记录执行状态
```

后续可以扩展评论读取、AI评论回复、私信处理、数据分析等能力。

---

# 三、核心设计原则

## 3.1 单机优先

第一阶段明确采用单机架构：

```text
本地应用
├── SQLite
├── 本地内容目录
├── 浏览器 Profile
├── AI Agent
└── Browser / Desktop Runtime
```

暂时不要引入：

* PostgreSQL
* Redis 集群
* Kafka
* Kubernetes
* Temporal
* 云端设备管理
* 分布式 Worker
* 多服务器调度

等产品验证成功以后再考虑。

---

# 四、核心模块

系统第一阶段包含以下模块：

```text
1. AI 配置
2. 账号池
3. 内容池
4. 发布消费队列
5. Agent Adapter
6. Browser / Desktop Runtime
7. 任务调度器
8. 执行记录
```

---

# 五、AI 配置模块

允许用户在本地配置 AI Provider。

至少支持：

```text
Provider
API Key
Base URL
Model
```

设计上不要将模型厂商写死。

统一抽象：

```text
LLMProvider
```

后续可以接入：

```text
OpenAI
Anthropic
Gemini
OpenAI Compatible API
本地模型
其他模型
```

API Key 必须只保存在本地，不上传服务器。

---

# 六、账号池

账号池负责管理用户拥有或明确授权的社交平台账号。

账号池与设备、平台执行逻辑解耦。

示例：

```text
Account
├── account_id
├── platform
├── account_name
├── browser_profile
├── persona
├── language
├── description
├── status
└── metadata
```

例如：

```text
TikTok
├── account_A
└── account_B

YouTube
└── account_C

Reddit
├── account_D
└── account_E
```

重要原则：

> **系统不保存平台账号密码。**

用户自己在浏览器 Profile 中完成登录。

账号池只记录该账号对应的浏览器 Profile。

例如：

```text
account_A
    ↓
chrome_profile/tiktok_001
```

### 人机协作边界（关键）

使用账号池发布内容时，**只有登录步骤可能需要用户完成人机校验**；发布链路其余步骤必须全自动。

```text
【仅首次 / 登录态失效时】
用户打开 Profile → 手动登录 → 完成平台人机校验（验证码等）
        ↓
登录态写入浏览器 Profile（Cookie / Session）
        ↓
【之后每一次发布】
创建 Job → 队列消费 → Agent 自动上传/填文案/发布/验证
        ↓
全程无需用户再做人机校验
```

约束说明：

1. **首次登录**：用户在本机浏览器中完成登录与人机校验；系统不代做、不破解验证码。
2. **日常发布**：复用已登录 Profile，上传、填标题/正文/标签、点击发布、结果验证全部由 Agent 自动完成。
3. **非首次**：只要登录态仍有效，用户不应再介入操作界面。
4. **例外**：仅当登录态过期、被踢下线或平台强制重新验证时，才再次打开 Profile 让用户登录并完成人机校验；完成后发布恢复全自动。
5. Agent 若在发布过程中遇到验证码/人机挑战，应立即停止并标记失败，提示用户重新完成登录校验——**不得尝试自动破解**。

---

# 七、浏览器 Profile

每个账号可以对应独立浏览器 Profile。

例如：

```text
profiles/
├── tiktok_001/
├── tiktok_002/
├── youtube_001/
├── reddit_001/
└── reddit_002/
```

用户第一次使用（**唯一需要用户做人机校验的环节**）：

```text
启动 Profile
↓
用户手动登录平台（含人机校验）
↓
保存登录状态到 Profile
↓
账号标记为 ACTIVE
```

之后发布任务：

```text
Worker 加载同一 Profile
↓
检测到已登录
↓
Agent 全自动完成发布
↓
用户无需再次操作浏览器
```

这样可以避免系统直接处理账号密码，并把人机校验成本收敛到「首次登录（及偶发重新登录）」。
---

# 八、内容池

内容池用于管理 AI 或用户准备好的内容资产。

支持：

```text
视频
图片
音频
文本
标题
描述
标签
缩略图
```

内容资产与具体平台发布任务解耦。

例如：

```text
ContentAsset #10001

video:
branchia_demo.mp4

base_caption:
"Building an AI-powered interactive story..."

language:
English

category:
Indie Game

status:
READY
```

注意：

> Content Asset 不是具体的平台帖子。

---

# 九、Content Variant

同一个内容可以针对不同平台生成不同版本。

例如：

```text
ContentAsset #10001
        │
        ├── TikTok Variant
        │   ├── 9:16
        │   ├── caption
        │   └── hashtags
        │
        ├── YouTube Variant
        │   ├── 9:16
        │   ├── title
        │   └── description
        │
        └── Reddit Variant
            ├── image/video
            └── post text
```

因此需要明确区分：

```text
Content Asset
Content Variant
Publish Job
```

三者不要混在一起。

---

# 十、发布内容消费队列

发布消费队列是第一阶段最核心的业务模块之一。

例如：

```text
18:00
TikTok
account_A
video_001

18:10
Reddit
account_D
post_002

18:30
YouTube
account_C
video_003
```

数据库中可以抽象为：

```text
PublishJob

id
content_variant_id
account_id
platform
browser_profile
scheduled_at
status
retry_count
created_at
started_at
completed_at
error_message
result
```

状态：

```text
PENDING
↓
CLAIMED
↓
EXECUTING
↓
VERIFYING
↓
SUCCESS
```

失败：

```text
EXECUTING
↓
FAILED
↓
RETRY
```

超过重试次数：

```text
DEAD
```

单机 MVP 使用：

```text
SQLite + Python Worker
```

即可。

不需要 Redis/Kafka。

---

# 十一、Agent 层

第一阶段**不要自行开发完整 Agent Framework**，也不优先自研「LLM + 工具循环」。

## 11.1 默认选型（评测后）

| 优先级 | 方案 | 用途 |
|--------|------|------|
| P0 默认 | **browser-use** | Python + Playwright，本地 Profile，Observe→Act 现成 |
| P1 备选 | Stagehand | Playwright 增强（act/observe/extract），TS/Python |
| P2 可选 | Hermes / OpenClaw | 完整个人 Agent Gateway，能力强但更重，作第二后端 |
| P3 尽量不做 | CustomAgentAdapter | 仅当 P0/P1 集成失败时的保底 |

系统只自研一层薄胶水：

```text
AgentAdapter
```

例如：

```python
class AgentAdapter:

    def execute(self, task):
        pass

    def pause(self):
        pass

    def stop(self):
        pass

    def get_status(self):
        pass
```

具体实现：

```text
BrowserUseAdapter      ← MVP 默认
StagehandAdapter       ← 备选
HermesAdapter          ← 可选后补
OpenClawAdapter        ← 可选后补
MockAgentAdapter       ← 队列联调
```

业务系统永远只调用：

```text
agent.execute(task)
```

而不要在业务层直接调用某一个 Agent 产品的具体 API。

## 11.2 明确不做

- 不自研 Agent 编排框架  
- 不把 Postiz / Mixpost 等**官方 API 排程工具**当执行底座（产品路径不同）  
- 不依赖云端「自动过验证码」能力作为正常发布路径  

---

# 十二、Browser / Desktop Runtime

Agent 与具体操作工具解耦。Runtime **只做薄封装**，不重写浏览器引擎。

统一抽象（便于换 backend；若 browser-use 已内置浏览器控制，Adapter 可直接委托，Runtime 仍保留接口边界）：

```text
ComputerRuntime

screenshot()
click()
type()
scroll()
press()
wait()
open()
close()
```

第一阶段优先：

```text
Playwright（含 persistent user_data_dir / Profile）
```

很多能力由 **browser-use / Stagehand 内部**完成，业务层不要平行再写一套点击脚本。

## 12.1 降级策略（延后，不进 MVP 主路径）

```text
DOM / Playwright / browser-use
        ↓（仅当 DOM 路径稳定失败）
OCR / OpenCV / Vision
        ↓
PyAutoGUI 坐标操作
```

MVP **默认不引入** OpenCV / PaddleOCR / PyAutoGUI，避免过早复杂化。  
不要一开始依赖固定坐标。

---

# 十三、Channel Adapter

平台渠道也需要解耦。

统一定义：

```text
Channel

publish()
read_comments()
reply_comment()
collect_metrics()
```

具体实现：

```text
TikTokChannel
YouTubeChannel
RedditChannel
InstagramChannel
XChannel
```

第一阶段只需要实现最核心的：

```text
publish()
```

后续再加入：

```text
read_comments()
reply_comment()
collect_metrics()
```

Channel 不应该关心：

```text
当前使用哪一个账号
当前使用哪一个浏览器 Profile
当前是哪一台设备
```

这些由上层任务系统提供。

---

# 十四、任务执行流程

完整流程（发布阶段默认**全自动**，不要求用户在场）：

```text
【一次性准备，需用户】
打开 Profile → 手动登录 + 人机校验 → 账号 ACTIVE
        ↓
【日常运营，全自动】
用户/AI创建发布任务
        ↓
PublishJob
        ↓
PENDING
        ↓
Scheduler
        ↓
选择 Account
        ↓
获取对应 Browser Profile（已含登录态）
        ↓
启动/连接浏览器
        ↓
校验仍处于登录态（未登录则 FAILED，提示用户重新登录）
        ↓
启动 Agent
        ↓
Agent观察页面
        ↓
Agent自动：上传 → 填文案 → 发布 → 验证
        ↓
确认发布成功
        ↓
SUCCESS
        ↓
保存执行记录
```

说明：Pause / Stop / Take Over 是**运维兜底能力**，不是正常发布流程的必经步骤。正常路径下用户完成首次登录后即可离开，由系统自动跑完队列。
失败：

```text
FAILED
 ↓
记录错误
 ↓
自动重试
 ↓
超过重试次数
 ↓
标记 DEAD
```

---

# 十五、Agent Task 的抽象

不要让 Agent 直接知道系统内部数据库结构。

例如系统最终传给 Agent 的任务应该类似：

```text
当前浏览器已经登录目标社交平台账号。

请完成以下任务：

目标：
发布指定视频。

视频：
{local_file_path}

标题：
{title}

正文：
{caption}

标签：
{hashtags}

要求：
1. 使用当前登录账号。
2. 完成视频上传。
3. 填写指定内容。
4. 完成发布。
5. 发布完成后确认结果。
6. 如果出现无法处理的异常，停止操作并返回异常信息。
```

Agent 只负责执行。

---

# 十六、Agent 必须采用 Observe → Act → Verify 模式

不要使用简单的：

```text
click()
sleep()
click()
sleep()
```

而应该：

```text
Observe
 ↓
Understand
 ↓
Act
 ↓
Observe
 ↓
Verify
 ↓
Next Action
```

例如：

```text
截图
↓
识别 Create
↓
点击 Create
↓
重新截图
↓
识别 Upload
↓
点击 Upload
↓
上传文件
↓
等待
↓
重新截图
↓
识别 Publish
↓
点击 Publish
↓
验证发布成功
```

这样平台页面发生变化时，Agent 有机会自行适应。

---

# 十七、任务调度

单机 MVP 使用简单 Scheduler。

例如每隔几秒：

```text
查询：
status = PENDING
scheduled_at <= NOW()
```

取出任务：

```text
CLAIM
↓
EXECUTE
```

需要避免同一任务被重复执行。

SQLite 中使用任务状态和事务控制即可。

---

# 十八、执行日志

每一个任务必须记录：

```text
Task ID
Account
Platform
Content
Start Time
End Time
Status
Retry Count
Error
Agent Result
```

最好保存执行截图：

```text
execution/
├── task_001/
│   ├── start.png
│   ├── step_001.png
│   ├── step_002.png
│   └── result.png
```

这样出现问题时可以回放。

---

# 十九、第一阶段 UI

不要做复杂后台。

建议简单桌面 Web UI：

```text
┌─────────────────────────────────────────┐
│ AI Operator                             │
├───────────┬─────────────────────────────┤
│           │                             │
│ Dashboard │       AI Assistant          │
│ Accounts  │                             │
│ Content   │  今天帮我发布这些内容        │
│ Queue     │                             │
│ History   │  [开始执行]                  │
│ Settings  │                             │
│           │                             │
├───────────┴─────────────────────────────┤
│ 当前任务                                │
│ TikTok / Account A                      │
│ 正在上传视频...                         │
│                                         │
│ [暂停] [停止]                           │
└─────────────────────────────────────────┘
```

---

# 二十、推荐技术栈

## 20.1 自研 vs 复用（定稿）

```text
【必须自研】运营业务层
  Settings / 账号池 / 内容池+Variant / 发布队列+状态机
  Channel 编排与失败分类 / 执行记录 / 产品 UI
  AgentAdapter 薄胶水

【直接复用，不自研】
  Agent 大脑：browser-use（默认）/ Stagehand（备选）
  浏览器：Playwright（多由 Agent 库携带）
  API：FastAPI + Uvicorn
  DB：SQLAlchemy + SQLite
  LLM SDK：OpenAI 兼容客户端或 LiteLLM
  调度：asyncio 轮询或 APScheduler（不要 Temporal/Celery）

【MVP 暂缓】
  Hermes / OpenClaw（可选第二 Adapter）
  OpenCV / PaddleOCR / PyAutoGUI
  CustomAgentAdapter

【不当底座】
  Postiz / Mixpost / BrightBean 等官方 API 排程产品
  （路径是 OAuth/API，不是本地浏览器 Operator）
```

## 20.2 第一版依赖清单

```text
Python
FastAPI
SQLite
SQLAlchemy
Playwright
browser-use          ← 默认 Agent
（可选）litellm
```

通过：

```text
AgentAdapter → BrowserUseAdapter
```

接入。

前端可以选择：

```text
React + Vite
```

或者为了极简：

```text
FastAPI + Jinja/简单前端
```

第一版不需要复杂前端框架也可以。

---

# 二十一、第一阶段明确不做

为了快速验证 MVP，暂时不要做：

```text
❌ 云端部署
❌ 多服务器
❌ 多设备集群
❌ Kafka
❌ Kubernetes
❌ PostgreSQL
❌ Redis 集群
❌ Temporal
❌ 官方平台 API 集成
❌ 复杂权限系统
❌ SaaS 多租户
❌ 计费系统
❌ 自动账号注册
❌ 自动破解验证码
❌ 绕过平台安全机制
```

重点只验证：

> **AI是否真的可以稳定地通过当前电脑浏览器完成社交媒体运营任务。**

---

# 二十二、MVP 第一阶段目标

只实现以下完整闭环：

```text
配置 API Key
      ↓
添加一个平台账号
      ↓
打开对应 Chrome Profile
      ↓
用户手动登录（含人机校验，仅此步需用户）
      ↓
加入账号池
      ↓
添加一个视频
      ↓
创建发布任务
      ↓
进入 Publish Queue
      ↓
Agent 获取任务
      ↓
操作当前浏览器（全自动，无需用户）
      ↓
完成发布
      ↓
验证
      ↓
记录 SUCCESS
```

验收口径补充：

> 首次登录完成后，同一账号再次发布时，用户不应再需要完成人机校验或手动点选发布流程。
第一阶段只需要成功支持：

```text
1台电脑
+
多个浏览器 Profile
+
2~3个平台
+
视频发布
+
任务队列
+
Agent自动执行
```

先把这个闭环做到稳定。

---

# 二十三、第二阶段

MVP 稳定以后，再增加：

```text
AI自动生成文案
AI自动生成平台不同版本
AI自动安排发布时间
评论读取
AI评论理解
AI生成回复
人工确认
自动回复
数据采集
```

形成：

```text
内容生产
 ↓
内容池
 ↓
内容变体
 ↓
发布队列
 ↓
Agent执行
 ↓
评论
 ↓
AI回复
 ↓
数据
 ↓
AI复盘
 ↓
下一轮内容
```

---

# 二十四、第三阶段

如果单机 MVP 被验证，再考虑：

```text
多设备
多机器
云端调度
Remote Worker
账号状态管理
并发任务
任务优先级
分布式 Queue
更多平台
```

到那个阶段再考虑：

```text
Redis
Kafka
PostgreSQL
Temporal
Docker
Kubernetes
```

目前全部不需要。

---

# 二十五、开发原则

整个项目必须保持以下原则：

### 1. Account 与 Device 解耦

```text
Account ≠ Device
```

### 2. Account 与 Channel 解耦

```text
Account ≠ Channel
```

### 3. Content 与 Publish Job 解耦

```text
Content ≠ Publish Job
```

### 4. Agent 与业务逻辑解耦

```text
Business Logic ≠ browser-use / Hermes / OpenClaw
```

只依赖 `AgentAdapter`。

### 5. Channel 与 Runtime 解耦

```text
TikTok ≠ Playwright
```

### 6. 所有自动化操作必须可记录

```text
Task
→ Action
→ Result
```

### 7. Agent 必须支持停止、暂停和人工接管

任何时候用户都应该能够：

```text
Pause
Stop
Take Over
```

注意：Take Over 仅用于异常兜底（如登录失效需重新人机校验），**正常发布路径不得依赖人工接管**。

### 8. 人机校验只发生在登录

```text
首次登录 / 登录态失效 → 允许且需要用户做人机校验
日常发布（上传、填表、发布、验证）→ 必须全自动
```
---

# 二十六、最终产品架构

最终 MVP 保持为：

```text
                         AI Operator（自研业务）
                              │
                    ┌─────────┴─────────┐
                    │                   │
               Task Manager        Content Manager
                    │                   │
                    ↓                   ↓
               Publish Queue       Content Pool
                    │
                    ↓
                 Scheduler
                    │
                    ↓
                Account Pool → Browser Profile
                    │
                    ↓
              Channel (TikTok…)     ← 自研编排
                    │
                    ↓
              AgentAdapter          ← 自研薄胶水
             ┌──────┴──────┐
             ↓             ↓
        browser-use    (Stagehand / Hermes / OpenClaw 可选)
             │
             ↓
        Playwright + Local Browser Profile
             │
             ↓
          TikTok / YouTube / Reddit …
```

核心原则：

> **自己只开发“运营业务层”和“资源/任务管理层”；Agent 大脑与浏览器驱动复用开源（默认 browser-use），不自研 Agent Framework，OCR/桌面坐标降级延后。**

第一阶段的核心不是把系统设计得多庞大，而是证明一个关键假设：

> **一个运行在用户本地电脑上的 AI Agent，能否可靠地消费运营任务，并通过浏览器完成实际社交媒体操作。**

只要这个假设成立，后面的自动内容生产、批量账号运营、评论回复、数据分析以及多设备扩展，都可以在这个架构上继续演进。

---

# 二十六点附、文档索引（迭代入口）

| 文档 | 用途 |
|------|------|
| `TODO.md`（本文） | 产品需求、架构、落地计划 |
| `version/README.md` | `0.1.1` → `0.2.0` 版本路线 |
| `version/BUILD_VS_BUY.md` | **自研 vs 复用**定稿 |
| `version/0.x.x` | 各版本待办与验收 |

---
---

# 二十七、落地执行计划（Implementation Plan）

> 本文档前半部分为产品/架构设计；本节起为**可执行落地计划**。  
> 目标：用最小工程量打通「配置 → 账号 → 内容 → 队列 → Agent 发帖 → 验证 → 记录」闭环。  
> 建议节奏：约 **6～8 周** 完成 MVP；每周有可演示交付物。

---

## 27.1 总原则（执行约束）

| 约束 | 说明 |
|------|------|
| 单机优先 | 仅 SQLite + 本地进程；禁止引入 Redis/Kafka/PG/K8s |
| 先闭环后扩展 | 先 1 个平台（TikTok）跑通，再加 YouTube / Reddit |
| 业务层自研 | 只做运营业务与资源/任务管理；Agent/浏览器复用开源 |
| Agent 默认 browser-use | 经 `AgentAdapter` 接入；不绑死 Hermes/OpenClaw；不优先自研 CustomAgent |
| Runtime 薄封装 | 不重写 Playwright；OCR/PyAutoGUI 不进 MVP 主路径 |
| 人机校验仅登录 | 仅首次登录（及登录失效重登）需用户做人机校验；发布全自动 |
| 不做黑产能力 | 不破解验证码、不绕过风控、不自动注册账号 |
| 每阶段可演示 | 每阶段结束必须有可手工验收的 Demo |

版本待办与「自研/复用」清单见 [`version/`](./version/README.md)。
---

## 27.2 里程碑总览

版本待办文件见 [`version/`](./version/README.md)（当前 `0.1.1` → MVP `0.2.0`）。

```text
M0  工程脚手架          →  version/0.1.1
M1  数据层 + 核心 API   →  version/0.1.2
M2  账号池 + Profile     →  version/0.1.3
M3  内容池 + 变体       →  version/0.1.4
M4  队列 + Scheduler    →  version/0.1.5
M5  Runtime + Adapter   →  version/0.1.6
M6  首平台发布闭环      →  version/0.1.7
M7  UI + 稳定性打磨     →  version/0.1.8
MVP 冻结                →  version/0.2.0
```

**MVP 完成定义（DoD）：**

1. 用户配置 LLM API Key；
2. 创建浏览器 Profile，**首次**手动登录 TikTok（含人机校验）；
3. 账号入库并绑定 Profile；
4. 上传 1 个视频到内容池，生成 TikTok Variant；
5. 创建 PublishJob，到期后 Worker **无人值守**自动执行；
6. Agent 通过 Playwright **全自动**完成上传与发布（不再出现人机校验）；
7. 状态变为 SUCCESS，执行截图与日志可回看；
8. 用户可随时 Pause / Stop（兜底，非正常路径依赖）。
---

## 27.3 推荐目录结构

落地时按下列结构初始化仓库（与设计解耦层一致）：

```text
OperationAgent/
├── README.md
├── TODO.md
├── pyproject.toml / requirements.txt
├── .env.example
├── data/                          # gitignore：本地运行数据
│   ├── app.db
│   ├── content/                   # 内容文件
│   ├── profiles/                  # 浏览器 Profile
│   └── execution/                 # 任务截图与日志
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 入口
│   │   ├── config.py
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   ├── models.py
│   │   │   └── migrations/        # 可用 Alembic，或首版简单建表脚本
│   │   ├── api/                   # REST 路由
│   │   │   ├── settings.py
│   │   │   ├── accounts.py
│   │   │   ├── content.py
│   │   │   ├── jobs.py
│   │   │   └── history.py
│   │   ├── services/              # 业务服务
│   │   │   ├── account_service.py
│   │   │   ├── content_service.py
│   │   │   ├── job_service.py
│   │   │   └── settings_service.py
│   │   ├── scheduler/
│   │   │   └── worker.py          # PENDING → CLAIM → EXECUTE
│   │   ├── agent/
│   │   │   ├── base.py                 # AgentAdapter 抽象
│   │   │   ├── browser_use_adapter.py  # MVP 默认
│   │   │   ├── stagehand_adapter.py   # 可选
│   │   │   ├── hermes_adapter.py      # 可选后补
│   │   │   ├── openclaw_adapter.py    # 可选后补
│   │   │   └── mock_adapter.py        # 联调用 Mock
│   │   ├── runtime/
│   │   │   ├── base.py                 # ComputerRuntime 薄抽象
│   │   │   └── playwright_runtime.py   # Profile 启停/截图等
│   │   ├── channels/
│   │   │   ├── base.py            # Channel 抽象
│   │   │   ├── tiktok.py
│   │   │   ├── youtube.py
│   │   │   └── reddit.py
│   │   └── prompts/
│   │       └── publish_task.md    # 传给 Agent 的任务模板
│   └── tests/
├── frontend/                      # React+Vite 或 FastAPI 静态页（二选一）
│   └── ...
└── scripts/
    ├── init_db.py
    ├── launch_profile.py          # 打开某 Profile 供用户登录
    └── smoke_publish.py           # 端到端冒烟
```

---

## 27.4 数据模型落地清单

首版 SQLite 表（与设计一一对应，字段可微调）：

### `ai_settings`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | PK | |
| provider | TEXT | openai / anthropic / compatible… |
| api_key_enc | TEXT | 本地加密存储，禁止明文日志 |
| base_url | TEXT | |
| model | TEXT | |
| updated_at | DATETIME | |

### `accounts`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | PK | |
| platform | TEXT | tiktok / youtube / reddit |
| account_name | TEXT | |
| browser_profile | TEXT | 相对 `data/profiles/` 路径 |
| persona | TEXT | 可选 |
| language | TEXT | |
| description | TEXT | |
| status | TEXT | ACTIVE / DISABLED |
| metadata_json | TEXT | |
| created_at | DATETIME | |

### `content_assets`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | PK | |
| title | TEXT | |
| media_type | TEXT | video / image / text |
| file_path | TEXT | |
| base_caption | TEXT | |
| language | TEXT | |
| category | TEXT | |
| status | TEXT | DRAFT / READY |
| created_at | DATETIME | |

### `content_variants`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | PK | |
| asset_id | FK | |
| platform | TEXT | |
| title | TEXT | |
| caption | TEXT | |
| hashtags_json | TEXT | |
| media_path | TEXT | 可与 asset 相同或裁剪版 |
| extra_json | TEXT | 平台特有字段 |
| status | TEXT | READY |

### `publish_jobs`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | PK | |
| content_variant_id | FK | |
| account_id | FK | |
| platform | TEXT | 冗余便于查询 |
| browser_profile | TEXT | 冗余快照 |
| scheduled_at | DATETIME | |
| status | TEXT | PENDING/CLAIMED/EXECUTING/VERIFYING/SUCCESS/FAILED/RETRY/DEAD |
| retry_count | INT | 默认 0 |
| max_retries | INT | 默认 3 |
| error_message | TEXT | |
| result_json | TEXT | |
| created_at / started_at / completed_at | DATETIME | |

### `execution_logs`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | PK | |
| job_id | FK | |
| step | TEXT | |
| message | TEXT | |
| screenshot_path | TEXT | |
| created_at | DATETIME | |

**实现注意：**

- Job 认领用事务：`UPDATE … WHERE status='PENDING' AND id=?` 检查 `rowcount`，防止双执行。
- 不存平台密码；只存 Profile 路径。

---

## 27.5 分阶段任务清单

### M0｜工程脚手架（Week 0，1～2 天）

**目标：** 可运行的空壳服务。

- [ ] 初始化 Python 项目（`pyproject.toml` / venv / 依赖锁定）
- [ ] 安装核心依赖：FastAPI、SQLAlchemy、Playwright、uvicorn、pydantic-settings
- [ ] 创建目录结构与 `.gitignore`（`data/`、`.env`、`profiles/`）
- [ ] `GET /health` 返回 200
- [ ] 写 `README`：如何启动后端

**验收：** `uvicorn` 启动成功，health 正常。

---

### M1｜数据层 + Settings API（Week 1）

**目标：** 本地库可读写，AI 配置可保存。

- [ ] 实现 SQLAlchemy models + `init_db`
- [ ] Settings CRUD：保存/读取 Provider、API Key、Base URL、Model
- [ ] API Key 本地加密（如 Fernet + 本机密钥文件），响应中脱敏
- [ ] `LLMProvider` 抽象 + 一次真实连通性探测（chat 一句）
- [ ] 单元测试：settings 读写

**验收：** 配置 Key 后调用 `/settings/test` 成功返回模型回复。

**API 草案：**

```text
GET/PUT  /api/settings/ai
POST     /api/settings/ai/test
```

---

### M2｜账号池 + Browser Profile（Week 2）

**目标：** 账号与 Profile 绑定；**首次登录由用户完成人机校验**，登录态持久化后供后续全自动发布使用。

- [ ] Accounts CRUD（按 platform 过滤）
- [ ] `scripts/launch_profile.py`：用 Playwright 持久化 Context 打开指定 Profile 目录
- [ ] API：创建账号 → 返回 profile 路径 → 触发「打开浏览器登录」（唯一需用户交互的引导入口）
- [ ] API：标记账号 ACTIVE（用户确认已登录且人机校验完成后）
- [ ] 启动发布前可做「是否仍登录」探测（未登录则阻断并提示重新 `open-profile`）
- [ ] 禁止任何密码字段入库

**验收：** 打开 Profile → 用户完成首次登录与人机校验 → 关闭后再次打开**无需再登录**；二次打开过程中用户无需操作。
**API 草案：**

```text
GET/POST     /api/accounts
GET/PATCH    /api/accounts/{id}
POST         /api/accounts/{id}/open-profile
POST         /api/accounts/{id}/mark-active
```

---

### M3｜内容池 + Content Variant（Week 3）

**目标：** 视频入库，可生成平台变体（首版可手工填写，不必 AI 生成）。

- [ ] 上传视频到 `data/content/`，写 `content_assets`
- [ ] 创建/编辑 Variant（platform、title、caption、hashtags）
- [ ] Asset / Variant / Job 三者模型分离，禁止混表
- [ ] 列表与详情 API

**验收：** 上传 1 个 mp4，为 TikTok 创建 Variant，状态 READY。

**API 草案：**

```text
GET/POST     /api/content/assets
POST         /api/content/assets/{id}/upload
GET/POST     /api/content/variants
GET/PATCH    /api/content/variants/{id}
```

---

### M4｜发布队列 + Scheduler Worker（Week 4）

**目标：** 无 Agent 也能把 Job 状态机跑通（用 MockAdapter）。

- [ ] PublishJob 创建（绑定 account + variant + scheduled_at）
- [ ] Worker 循环：查询 `PENDING AND scheduled_at <= now`
- [ ] 状态机：PENDING → CLAIMED → EXECUTING → SUCCESS / FAILED → RETRY → DEAD
- [ ] 重试退避（如 1m / 5m / 15m）
- [ ] `MockAgentAdapter`：写假日志与截图目录，模拟成功/失败
- [ ] 执行记录写入 `execution_logs` + `data/execution/{job_id}/`

**验收：** 创建 2 个 Job，Worker 自动认领并完成；失败 Job 可重试至 DEAD。

**API 草案：**

```text
GET/POST     /api/jobs
GET          /api/jobs/{id}
POST         /api/jobs/{id}/cancel
POST         /api/jobs/{id}/retry
GET          /api/jobs/{id}/logs
```

---

### M5｜Computer Runtime + AgentAdapter（Week 5）

**目标：** 以 **browser-use** 为默认真实 Adapter；业务只依赖 `AgentAdapter`；完成「已登录 Profile → 观察/截图」级能力。

- [ ] `AgentAdapter`：`execute(task)` / `stop()` / `pause()` / `get_status()`
- [ ] `BrowserUseAdapter`（默认）：绑定 persistent Profile + 本地 LLM 配置
- [ ] `ComputerRuntime` 薄接口 + `PlaywrightRuntime`（Profile 启停/截图目录约定；可与 browser-use 共享 session）
- [ ] 保留 `MockAgentAdapter` 供回归
- [ ] 任务 Prompt 模板（见第十五节），只传业务语义，不传 DB 结构
- [ ] 执行中持续落盘 step 截图
- [ ] **不做**：CustomAgent 主路径；OCR/PyAutoGUI

**验收：** 给定「打开已登录站点并截图/完成简单页面操作」任务，BrowserUseAdapter 可跑通。

**选型决策（已定默认，仅失败时降级）：**

```text
P0  browser-use
P1  Stagehand（browser-use 集成失败或不稳时）
P2  Hermes / OpenClaw（可选第二后端）
P3  CustomAgentAdapter（尽量不做）
```

---

### M6｜首平台发布闭环 —— TikTok（Week 6）

**目标：** 真机真账号在**用户不在场**的情况下完成一次视频发布（前提：该账号已完成首次登录）。

- [ ] `TikTokChannel.publish()`：编排「准备 Runtime → 组装 Agent Task → execute → verify」
- [ ] 发布路径全自动：上传、填文案、发布、验证均不弹人工步骤
- [ ] Verify：根据页面文案/URL/截图确认发布成功
- [ ] 失败分类：登录失效 / 上传超时 / 页面改版 / 发布中出现人机挑战 / 未知 → 写入 error_message
- [ ] 登录失效或发布中出现人机挑战：Job 标记 FAILED，**停止自动尝试**，提示用户重新 `open-profile` 完成登录校验
- [ ] 端到端脚本 `scripts/smoke_publish.py`（执行期间不要求人工点击）

**验收：** 账号已 ACTIVE 后，从创建 Job 到 TikTok 出现真实视频全程无人值守；Job = SUCCESS；截图可回放。
**平台顺序（严格）：**

```text
1) TikTok 视频发布   ← 本里程碑必达
2) YouTube Shorts    ← 可选加时 3～5 天
3) Reddit 图文/视频  ← 可选再加 3～5 天
```

---

### M7｜简易 UI + 稳定性（Week 7～8）

**目标：** 非开发者也能点完主流程。

**UI（建议 React + Vite；若赶工可用 FastAPI + 简单 HTML）：**

- [ ] 左侧导航：Dashboard / Accounts / Content / Queue / History / Settings
- [ ] Settings：配置 AI Key
- [ ] Accounts：添加账号、打开 Profile、标记已登录
- [ ] Content：上传视频、编辑 Variant
- [ ] Queue：创建任务、查看状态、暂停/停止当前任务
- [ ] History：查看日志与截图
- [ ] 底部「当前任务」状态条

**稳定性：**

- [ ] Worker 崩溃恢复：CLAIMED/EXECUTING 超时回收为 RETRY
- [ ] 单 Worker 锁文件，避免多进程抢同一 Job
- [ ] Pause / Stop / Take Over 基本可用（Take Over = 停止 Agent，保留浏览器给用户）
- [ ] 基础日志（文件 + 控制台）
- [ ] README 完整：安装、登录、首次发布教程

**验收：** 按 README 无代码操作完成一次 TikTok 发布；连续 3 次成功率 ≥ 2/3。

---

## 27.6 每周交付物检查表

| 周 | 必须演示 |
|----|----------|
| W0 | Health API |
| W1 | 保存 Key 并测试模型连通 |
| W2 | Profile 登录保持 |
| W3 | 视频入库 + Variant |
| W4 | Mock 队列自动跑完 Job |
| W5 | 浏览器截图任务 |
| W6 | TikTok 真实发布 SUCCESS |
| W7～8 | UI 走通全流程 + 稳定性 |

---

## 27.7 接口与模块依赖顺序（开发顺序强制）

```text
config / db
    ↓
settings + LLMProvider
    ↓
accounts + profiles
    ↓
content + variants
    ↓
jobs + scheduler (+ MockAdapter)
    ↓
runtime (Playwright)
    ↓
AgentAdapter (真实)
    ↓
TikTokChannel.publish
    ↓
UI
```

**禁止：** 在 M4 完成前深入写平台 Channel 细节；在 M5 前把 Hermes API 写进业务 Service。

---

## 27.8 Agent 任务模板（落地版）

文件：`backend/app/prompts/publish_task.md`

占位符由 JobService 填充：

```text
当前浏览器已经登录目标社交平台账号。

请完成以下任务：

目标：发布指定视频到 {platform}。

视频本地路径：{media_path}
标题：{title}
正文：{caption}
标签：{hashtags}

执行要求：
1. 只使用当前已打开且已登录的浏览器会话。
2. 采用 Observe → Act → Verify 循环，每步操作后重新观察页面。
3. 完成上传、填写文案、发布。
4. 发布成功后返回：status=SUCCESS，并附上可见的成功依据（URL 或页面文案）。
5. 若遇到登录失效、人机校验/验证码、无法识别的阻断，立即停止，返回 status=FAILED 与原因。
6. 不要尝试破解验证码或绕过安全机制；人机校验只应由用户在首次（或重新）登录时完成。
7. 正常发布路径中不要等待人工确认或 Take Over。
```

---

## 27.9 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 平台页面频繁改版 | 发布失败 | 交给 browser-use Observe-Act-Verify；失败截图；必要时 Take Over |
| browser-use 集成/不稳定 | 延期 | 切 Stagehand；仍经 AgentAdapter；避免立刻自研 CustomAgent |
| 登录态丢失 / 二次人机校验 | 发布中断 | FAILED 并引导用户重新登录；不自动破解；登录恢复后继续全自动 |
| 发布流程中突然弹出验证码 | 无法无人值守 | 立即停止并提示重登；不把人工点发布做成常态 |
| Playwright/DOM 点不到控件 | 卡住 | 先调 prompt/等待策略；OCR/PyAutoGUI 仅作 MVP 后降级 |
| 单机 Worker 重复执行 | 双发 | SQLite 事务认领 + 进程锁 |
| 误用官方 API 排程开源项目 | 路线跑偏 | 坚持浏览器 Operator；Postiz 等仅作竞品参考 |
| 法律/ToS 风险 | 合规 | 仅操作用户自有已登录账号；文档声明用户责任 |
---

## 27.10 MVP 明确砍掉（执行时不要做）

- AI 自动生成多平台文案 / 自动排期（放第二阶段）
- 评论读取与回复
- 多 Agent 并发多窗口狂发
- 官方 API
- 分布式、Docker 编排、云端设备
- 精美复杂后台、权限、计费

---

## 27.11 第二阶段预留（MVP 后再排期）

仅作 backlog，不进入当前 Sprint：

1. AI 根据 Asset 生成各平台 Variant  
2. AI 建议发布时间写入 Queue  
3. `read_comments` / `reply_comment`  
4. 人工确认后自动回复  
5. 简单数据采集与复盘报告  
6. YouTube / Reddit / Instagram / X Channel 补齐  

---

## 27.12 立即开始的第一步（Today）

按顺序执行，勿跳步：

1. **初始化仓库结构**（M0 / `0.1.1`）：Python 项目 + FastAPI + `GET /health`
2. **建表脚本**（M1 / `0.1.2`）：`accounts / content_* / publish_jobs / execution_logs / ai_settings`
3. **写 `launch_profile.py`**：尽早验证 Playwright 持久化登录（降低后期风险）
4. **锁定默认 Agent**：`browser-use` + `AgentAdapter`；另开一页冒烟「已登录 Profile 打开目标站」

完成以上 4 项后，再进入 Accounts / Content / Queue 的业务开发。

---

## 27.13 进度追踪（勾选区）

### Phase 状态

- [ ] M0 脚手架完成
- [ ] M1 Settings + DB 完成
- [ ] M2 账号池 + Profile 完成
- [ ] M3 内容池 + Variant 完成
- [ ] M4 队列 + Scheduler + Mock 完成
- [ ] M5 Runtime + AgentAdapter 完成
- [ ] M6 TikTok 真实发布闭环完成
- [ ] M7 UI + 稳定性完成 → **MVP 发布**

### MVP 验收勾选

- [ ] 配置 API Key 并测试通过
- [ ] Profile 登录 TikTok 且持久化
- [ ] 视频进入内容池并有 TikTok Variant
- [ ] Job 到期自动执行
- [ ] 真实平台出现发布内容
- [ ] SUCCESS + 截图日志可查
- [ ] Pause / Stop 可用
- [ ] README 可让新人独立跑通

---

**一句话执行方针：**

> 自研业务与队列，复用 browser-use 做浏览器操作；先用 Mock 跑稳状态机，再无人值守打通 TikTok；UI 放闭环之后。  
> **产品体验铁律：人机校验只出现在首次（或重新）登录；账号池驱动的发布必须全自动。**  
> **工程铁律：不自研 Agent Framework；OCR/坐标点击不进 MVP；官方 API 排程工具不当底座。**
