# Ensemble —— AI 跑团（TRPG）引擎

Ensemble 把桌上角色扮演游戏（TRPG）搬进浏览器：**LLM 担任 GM 主持人**，
**子 agent 扮演 NPC**，用 LangGraph 编排整场冒险。你输入行动，系统驱动
意图判定、d100 检定与流式叙事，像真人主持人一样把故事讲下去。

当前进度对应设计的 **M3 里程碑「可玩 Web」**：后端内核（M1/M2）之上，
补齐 FastAPI + WebSocket 服务与 React 前端，已可完整体验一局冒险
（开场 → 调查检定 → 线索 → 结局）。

## 特性

- **流式叙事（打字机效果）**：GM 输出的 token 实时推送到浏览器，边生成边阅读
- **d100 检定与骰子动画**：CoC-lite 规则（大成功 ~ 大失败六档），前端骰子翻牌动画 + 检定记录
- **NPC 子 agent**：每个 NPC 有独立人设（persona）与知识边界，只在被触发时出场
- **线索与结局**：线索解锁链、结局条件由模组 YAML 声明，GM 判定时触发全屏结局演出
- **断线重连**：事件带自增 seq，F5 刷新后全量重放叙事历史，接着玩
- **时间线分叉与回滚**：SQLite 上按分支组织存档，可将任意历史回合分叉出新线
- **成本控制**：模型 token 计费用（pricing 表），超单回合 token 预算或战役成本上限自动熔断暂停

## 技术栈

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 编排内核 | **LangGraph** | 状态图驱动回合流程（decide → checks → narrate），支持中断/恢复（interrupt / Command） |
| 后端服务 | **FastAPI** + uvicorn | REST（大厅/战役/时间线）+ 原生 WebSocket 端点 |
| 存储 | **SQLite** + SQLModel | 战役/分支/角色/线索落库；时间线即分支树 |
| LLM | 阿里云百炼 `qwen3.8-flash`（GM）/ DeepSeek `deepseek-flash`（NPC） | OpenAI 兼容接口，可经环境变量配置 |
| 前端 | **React 18** + **TypeScript** + **Vite** | 大厅/房间两视图，纯函数 reducer + zustand 状态层 |
| 测试 | pytest（后端）/ Vitest + Testing Library（前端） | 含真实 WS 协议的端到端验收 |
| 工程 | uv（Python）/ npm（Node） | Python 3.12+ / Node 20+ |

## 架构与流程

```
浏览器 (React)
  │   REST：模组列表 / 新建战役 / 存档 / 时间线 / 回滚
  └── WS：/ws/campaign/{id}?player_id=…&resume_from=…
          │
          ▼
FastAPI ──▶ SessionManager（每战役一个会话）
               │  驱动
               ▼
          LangGraph 图 ──▶ LLM（GM / NPC 子图）
               │
               ├─▶ 事件总线（自增 seq，环形缓冲）
               │        │ 广播 + 断线重放
               │        ▼
               │    浏览器事件流 ──▶ reducer ──▶ 叙事流 / 侧栏面板 / 骰子动画
               │
               └─▶ SQLite（分支时间线落库）
```

**一回合的生命周期**

1. **收集输入**：回合窗口打开，玩家输入经 WS 提交（单人：提交后防抖收口、挂机不超时；多人：等齐即收、超时自动推进）
2. **意图判定**：GM 结构化输出本回合意图（检定 / 场景移动 / NPC 触发 / 线索解锁）
3. **规则裁定**：d100 检定（困难/极难/大成功等六档），场景移动应用拓扑
4. **叙事生成**：GM 流式叙事，token 实时推送；损坏输出自动重试修复
5. **落库与广播**：回合快照写入分支时间线，权威状态（state）与事件全部经 WS 广播

**WS 事件类型**：`token`（叙事增量）、`dice`（检定）、`scene`（场景）、`turn`（相位）、
`state`（权威快照）、`clue`（线索）、`actor`（行动者）、`notice`（提示）、`error`（错误）。

## 目录结构

```
├── modules/                  # 模组（YAML 声明）：misty_hollow 示例冒险《雾霭镇的低语》
├── config/pricing.yaml       # 模型价格表（成本估算用）
├── docs/superpowers/         # 设计规格与实施计划（specs / plans）
├── backend/                  # FastAPI + LangGraph + SQLite（uv 管理）
│   ├── app/
│   │   ├── graph/            # LangGraph 图与节点（decide / narrate / 等）
│   │   ├── rules/            # 检定、角色、场景等规则层
│   │   ├── content/          # 模组加载与校验（YAML → 结构化模型）
│   │   ├── memory/           # 记忆与摘要（NPC 知识 / 历史查询）
│   │   ├── llm/              # LLM 客户端（含测试用 FakeLLM）
│   │   ├── api/              # REST 路由、WS 端点、会话管理
│   │   ├── storage/          # SQLite 模型与仓储
│   │   └── serve.py / cli.py # 生产入口 / 命令行入口
│   └── tests/                # 单元 + API + 端到端验收
└── frontend/                 # React + Vite + zustand（npm 管理）
    └── src/
        ├── api/              # REST / WS 客户端（断线重连）
        ├── stores/           # 事件 reducer + zustand store
        ├── views/            # Lobby（大厅）/ Room（房间）
        └── components/       # 叙事流、输入栏、面板、骰子与结局覆盖层
```

## 环境准备

- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- API keys：
  - `DASHSCOPE_API_KEY`（阿里云百炼，GM：qwen3.8-flash）
  - `DEEPSEEK_API_KEY`（NPC：deepseek-flash）

## 配置密钥（二选一）

仓库根提供模板 [`.env.example`](.env.example)（密钥 + 可选预算闸门）：

**方式 A：`.env` 文件（推荐，长期有效）**

```powershell
Copy-Item .env.example .env      # bash: cp .env.example .env
# 编辑 .env，把两个密钥占位符替换为真实值（.env 已被 git 忽略，不会提交）
```

**方式 B：临时环境变量（仅当前终端生效）**

```powershell
$env:DASHSCOPE_API_KEY = "sk-..."
$env:DEEPSEEK_API_KEY = "sk-..."
```

## 启动后端（端口 8000）

```powershell
cd backend
uv sync
uv run uvicorn app.serve:app --env-file ../.env --host 127.0.0.1 --port 8000
```

> `--env-file` 为 uvicorn 原生能力（`python-dotenv` 随 `uvicorn[standard]` 安装）；
> 路径相对当前目录，这里即仓库根的 `.env`。shell 中已设置的环境变量优先于文件内值，
> 用方式 B 时去掉 `--env-file ../.env` 即可。

## 启动前端（端口 5173）

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。前端已配置 `/api` 与 `/ws` 代理到 8000 端口。

## Docker 一键启动 / 服务器部署

```bash
cp .env.example .env      # 填入 DASHSCOPE_API_KEY / DEEPSEEK_API_KEY
docker compose up -d --build
# 浏览器打开 http://localhost/
```

数据存放在 `./data/ensemble.db`；腾讯云部署全流程见 `docs/deploy-tencent.md`。

## 单人验收清单（浏览器手测）

- [ ] 打开 http://localhost/ → 新建战役 → 提交行动即结算（无等待窗口）
- [ ] 结算叙事流式显示；结算期间输入框禁用，结算完自动恢复可输入
- [ ] 刷新页面 → 历史完整回放，可继续行动
- [ ] 换一个浏览器（或清空 localStorage）打开 → 大厅看不到已建战役
- [ ] 玩到结局 → 结局内容完整展示
- [ ] GM 暗骰不出现在骰子日志中

## 测试

```bash
cd backend; uv run pytest -q          # 后端全量（含真实 WS 协议端到端验收）
cd frontend; npm run test             # 前端组件 / 状态层测试
```

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ENSEMBLE_SQLITE_PATH` | `ensemble.db`（相对运行目录） | 数据库路径 |
| `ENSEMBLE_MODULES_DIR` | `../modules` | 模组目录（相对启动目录优先，找不到回退仓库根） |
| `ENSEMBLE_PRICING_PATH` | `config/pricing.yaml` | 价格表（同上） |
| `ENSEMBLE_TURN_TOKEN_CAP` | `30000` | 单回合 token 预算（超出暂停） |
| `ENSEMBLE_CAMPAIGN_COST_CAP_USD` | `10.0` | 战役成本上限（熔断暂停） |
| `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` | 无 | 模型密钥 |

## 设计文档

- 设计规格 `docs/superpowers/specs/`：
  - `2026-09-24-ensemble-design.md` —— 总体设计
  - `2026-09-29-async-queue-design.md` —— 异步任务队列
  - `2026-09-26-npc-attitude-evolution-design.md` —— NPC 好感度演化（未来方向）
- 实施计划 `docs/superpowers/plans/`：后端内核（M1–M2）/ 可玩 Web（M3）/ 多人联机与部署（M4）/ 增强（M5）

## 路线图

- [x] **M1–M2** 内核：LangGraph 图、规则层、存储层、CLI
- [x] **M3** 可玩 Web：FastAPI + WS + React 前端（当前）
- [ ] **M4** 单人化与容器化：提交即结算、暗骰、战役归属隔离、Docker 生产镜像（公网部署随 M5 完成后统一进行）
- [ ] **M5** 增强：Graphiti 记忆图、可观测性、奖惩骰、战斗子图（可选开关）

## 致谢

本项目站在开源社区的肩膀上，感谢以下项目与服务：

- [LangGraph](https://github.com/langchain-ai/langgraph) —— 状态图编排与中断恢复
- [FastAPI](https://fastapi.tiangolo.com/) / [uvicorn](https://www.uvicorn.org/) —— 服务与 WebSocket
- [SQLModel](https://sqlmodel.tiangolo.com/) / SQLite —— 数据层
- [React](https://react.dev/) / [Vite](https://vitejs.dev/) / [zustand](https://zustand-demo.pmnd.rs/) —— 前端与状态管理
- [pytest](https://pytest.org/) / [Vitest](https://vitest.dev/) / [Testing Library](https://testing-library.com/) —— 测试
- [uv](https://docs.astral.sh/uv/) —— Python 依赖与运行管理
- 阿里云百炼（Qwen）与 DeepSeek —— 模型服务
- 灵感来自《克苏鲁的呼唤》（Call of Cthulhu）与开源 TRPG 社区

## 声明

- 本项目为**个人学习与研究作品**，非商业项目，暂未附加开源许可证。
- 示例模组《雾霭镇的低语》及全部文本均为**虚构内容**，与现实中任何人物、
  团体、地点无关；部分内容由 LLM 生成，可能存在不稳定或不适宜的输出。
- 使用真实模型服务产生的 **API 费用由使用者自行承担**，请注意项目内置的
  预算熔断配置（见环境变量表）。
