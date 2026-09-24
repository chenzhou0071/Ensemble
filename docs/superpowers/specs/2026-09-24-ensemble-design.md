# Ensemble · AI 跑团系统设计

| 项 | 值 |
|---|---|
| 日期 | 2026-09-24 |
| 状态 | 已评审，定稿（本文档为实施依据） |
| 代号 | Ensemble —— 多演员共演一台戏：AI 主持人为导演，NPC 子 agent 为演员 |

## 1. 背景与目标

Ensemble 是一个 AI 跑团（TRPG）系统：大模型担任主持人（GM），多个 NPC 由独立子 agent 扮演，1~N 名真人玩家通过 Web 参与。

项目目标（按优先级）：

1. 系统学习 LangGraph 多 agent 编排（subgraph / interrupt / Send / checkpointer / streaming），沉淀可讲解的架构经验；
2. 作为求职简历项目，具备可演示性与生产级设计点（预算熔断、降级路径、可观测性、测试策略）；
3. 可玩：自己或朋友能真实跑起一段有代入感的模组故事（加分项）。

## 2. 关键决策一览

| 维度 | 决策 |
|---|---|
| 玩家形态 | 1~N 真人 + AI GM + AI NPC；单人即 N=1，架构按多人设计 |
| 规则系统 | 轻量 COC 式：属性 + 技能 + d100 检定；骰子由服务端纯代码执行 |
| 骰子随机性 | 真随机（secrets 生成 seed）+ 可复现（seed 随 DiceRecord 存档）；读档默认重掷 |
| 记忆架构 | 可插拔 MemoryService；MVP = 事件日志 + 滚动摘要；二阶段 Graphiti 时序图谱 |
| 模型策略 | 分级路由：GM = 千问，NPC = DeepSeek，记忆提取 = 便宜档；统一 OpenAI 兼容协议 |
| 前端 | React + Vite + TypeScript |
| 内容形态 | 结构化原创模组（YAML）+ 存档续玩（多场战役） |
| 部署接入 | 腾讯云（或本机）docker-compose；邀请码加入；不建完整账号体系 |

## 3. 总体架构

```
React SPA ──HTTP / WebSocket──▶ FastAPI 接入层（房间、TurnBuffer 回合调度、事件推送）
                                 │
                    LangGraph 编排层（GM 主图 + NPC 子图）
                     │            │             │
              规则引擎(纯代码)   记忆服务(可插拔)   内容加载器(模组)
                     │            │             │
              SQLite 领域库    LangGraph Checkpoint（存档）
                                 │
                 LLM Provider 抽象（路由：GM=千问 / NPC=DeepSeek / extractor=小模型）
```

依赖方向单向：`api → graph → {rules, memory, content, llm, storage}`。

架构路线：**GM Supervisor 主图 + NPC 子图**（对比群聊黑板模式与阶段化流水线后的选择）。

## 4. 核心回合流程（v2）

```
玩家输入 ─▶ API 层 TurnBuffer（输入窗口）
              │ 全员提交 or 超时 → TurnInputs 一次性恢复图
              ▼
1. intake          归一化输入、记事件
2. gm_decide       千问；结构化输出（见 4.1）
3. validate        结构化校验，失败 repair 重试 1 次
4. resolve_checks  纯代码掷骰（DiceRecord 含 seed 与成功等级）
5. memory_query    失败降级为"无长期记忆"继续
6. npc_respond     NPC 子图 Send 并行；产出结构化反应 {npc_id, speech, action}，不推送前端
7. gm_narrate      千问；统一编排叙事顺序（GM 描述 + NPC 台词嵌入），流式推送
8. post_turn       落库、摘要更新、场景持久化、广播
9. wait_input      interrupt 挂起 → 打开下一轮输入窗口
```

### 4.1 gm_decide 结构化输出

```json
{
  "intent_summary": "玩家想潜入城主府后院",
  "checks": [{"actor": "pc_1", "skill": "潜行", "difficulty": "hard"}],
  "proactive_npc_triggers": [{"npc_id": "guard_1", "trigger": "玩家翻墙被巡逻队看到"}],
  "scene_transition": {"to_scene": "manor_backyard", "reason": "翻墙成功"},
  "memory_queries": ["城主府布局", "guard_1 对玩家的态度"]
}
```

`scene_transition` 可为 null。**NPC 主动行为由 GM 统一裁决**：守卫盘问等"场景被动触发"也走 `proactive_npc_triggers`，GM 控制叙事节奏。

**叙事有序性**：NPC 台词**不独立推送前端**——`npc_respond` 产出结构化反应后，由 `gm_narrate` 统一编排顺序（GM 描述与 NPC 台词嵌入到叙事流的正确位置），再流式推送；前端按 speaker 标记渲染说话人（NPC 高亮/头像），玩家只看到一个有序叙事流。`dice / scene_changed / state` 等技术事件仍走独立事件通道（不参与叙事顺序）。

### 4.2 TurnBuffer ↔ interrupt 对接

- 状态机：`IDLE → COLLECTING(turn_id) → RESUME`
- **挂起检测**：API 层是图的唯一驱动者；每轮图执行结束检查 `get_state(config)`，停在 `wait_input`（interrupt 生效）则开窗 `COLLECTING`。
- **收集**：活跃玩家（= 已加入战役且在线）每人一条，后发覆盖前发（允许改主意）；全员提交或超时（默认 60s，配置化）→ 关窗；掉线与超时未交均记入 `skipped`。
- **恢复**：关窗后组装 `TurnInputs {turn_id, inputs: [{player_id, character_id, text, submitted_at}], skipped: []}`（按提交时间排序），调用 `graph.invoke(Command(resume=TurnInputs), config={thread_id: 当前分支的 thread_id})` 一次性恢复；`intake` 节点接收。
- **窗口外输入**：图 RUNNING 期间到达的行动进 `pending_next` 暂存，下一窗口开启时预填为已提交。
- **单人（N=1）**：提交后 2 秒防抖关窗（留编辑余地）。
- **测试用例**：单提交 / 双提交 / 超时 / 窗口外输入（四种场景）。

### 4.3 场景切换链（无竞态）

`gm_decide` 输出 `scene_transition` → 立即写入 `state.current_scene` → 下游节点（memory_query / npc_respond）**只读 state、不查 L2 领域库**，以新场景上下文工作（如进城主府立刻触发守卫）→ `gm_narrate` 叙事描述移动 → `post_turn` 持久化到领域库并广播 `scene_changed` 技术事件（前端切换场景与 NPC 区）。领域库是长期权威，本回合内以 state 为准。

**L2 加载时机（写死）**：回合开始由 `intake` 一次性把本回合所需 L2 动态状态加载进 state——当前场景指针、**全体 NPC 动态态度**、玩家角色卡摘要（数据量小，全量加载无压力）；此后直到 `post_turn` 写回为止，所有下游节点**只读 state、不查 L2 领域库**。`memory_query` 访问的是 L3 记忆服务（独立接口），不属于 L2 领域库，不受此约束；场景→NPC 的静态映射来自模组 Module（内存内容），场景切换无需任何库读取。

## 5. 状态模型

### 5.1 三层状态

- **L1 图内状态（LangGraph State）**：最近 N 回合消息窗口、`current_scene`、`active_npcs`、`pending_checks`、本轮 `TurnInputs`。
- **L2 领域状态（权威，纯代码管理）**：campaign / player / character / module_progress / event / dice_record / summary；结构化存储，LLM 不直接写。
- **L3 长期记忆（可插拔 MemoryService）**：MVP = 事件日志 + 滚动摘要 + 检索；二阶段 = Graphiti 时序图谱。

核心原则：**送给 LLM 的上下文是"检索 + 拼装"出来的，而非全量历史**——既是成本控制，也是记忆系统存在的理由。

### 5.2 骰子与可复现

- 实现：`seed = secrets.randbits(64)` → `rng = random.Random(seed)` → 掷骰。真随机与可复现兼得。
- `DiceRecord`：`{roll_id, campaign_id, branch_id, turn_id, actor, skill, difficulty, skill_value, roll, success_level, seed, created_at}`。
- 读档语义：默认重掷（"重新尝试"体验）；`seed` 留档供调试、回放与测试。
- 测试：注入固定 seed → 全链路确定性回放。

### 5.3 多人可见性

- 事件统一携带 `visibility: all | player:{id}`；服务端按玩家过滤后经 WS 推送，前端只负责渲染。
- 暗骰结果、私密线索只推送给对应玩家。

## 6. 单元划分与接口

### 6.1 仓库结构

```
ensemble/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI：HTTP + WS + TurnBuffer
│   │   ├── graph/        # LangGraph 主图、节点、NPC 子图
│   │   ├── rules/        # 规则引擎（纯函数）
│   │   ├── memory/       # 记忆服务接口 + 实现
│   │   ├── content/      # 模组 schema + 加载器 + 校验器
│   │   ├── storage/      # 领域库模型 + 仓储层
│   │   └── llm/          # provider 抽象 + 角色路由 + 用量记账
│   └── tests/
├── frontend/             # React + Vite + TS
├── modules/              # 模组内容（YAML）
├── config/               # pricing.yaml 等运行时配置
└── docker-compose.yml
```

### 6.2 后端单元

| 单元 | 职责 | 关键接口 | 测试要点 |
|---|---|---|---|
| `rules/` | 掷骰（seed→结果）、d100 检定与成功等级、角色卡模型 | `roll_check(skill, difficulty, seed) -> CheckResult` | 纯单测，零 IO 零 LLM，全分支覆盖 |
| `content/` | 模组 YAML → Pydantic 模型；加载时校验 | `load_module(path) -> Module` | 坏模组测校验器报错清晰 |
| `storage/` | 领域模型 + 仓储（Repository 协议，换 Postgres 只改实现） | Repository 协议 | 仓储契约测试 |
| `llm/` | `for_role(role)` 返回 OpenAI 兼容客户端（GM=千问 / NPC=DeepSeek / extractor=小模型）；统一超时重试；token/成本记账；预算检查 | `LLMClient.for_role()`、`Usage.record()` | 假客户端注入；记账断言 |
| `memory/` | 事件写入、检索、滚动摘要 | `MemoryService` 协议：`write_event / search / get_context / update_summaries` | MVP 实现 `JournalMemory`；Graphiti 为二阶段适配器，不改上层 |
| `graph/` | 编排核心：主图装配、state、节点集、NPC 子图、NPC registry | 主图 `compile()` + checkpointer | 节点级测试用假 LLM |
| `api/` | HTTP（战役/角色/存档）+ WS 事件流 + TurnBuffer 窗口状态机 | REST + `/ws/campaign/{id}` | TurnBuffer 状态机可独立测 |

### 6.3 关键边界约定

- **graph 只通过接口依赖其他单元**：rules 是纯函数直接调；memory / llm / storage 走协议注入，便于用假实现测试。
- **统一 WS 事件 schema**：`{seq, type: token|dice|actor|scene|state|turn|error, visibility: all|player:{id}, payload}`；`seq` 支持断线重连重放。
- **NPC 上下文组装**（子图入口）：`persona（模组）+ 动态态度（L2）+ 当前场景 + 相关记忆（memory_query 结果）+ 本人相关对话切片`——不是全量转录。
- **`graph/` 按域分文件**：`nodes/gm.py`（decide/validate/narrate）、`nodes/turn.py`（intake/resolve_checks/post_turn/wait_input）、`nodes/memory.py`、`npc.py`（子图）。

### 6.4 前端单元

- `api/`：HTTP + WS client（断线重连 + 按 seq 重放）
- `stores/`：zustand——房间、叙事流、角色卡、骰子队列、连接状态
- `Lobby`：新建/加入（邀请码）、存档列表
- `Room`：叙事流（打字机）、行动输入（自由文本 + 技能快捷）、在场 NPC 区（说话高亮）、角色卡侧栏、线索面板
- `DiceOverlay`：消费 dice 事件播动画，结束展示结果与成功等级
- 私密信息：服务端按 visibility 过滤，前端只管渲染

## 7. 存档与读档语义

- **统一关联键 `campaign_id`**；每分支一个 thread：`thread_id = {campaign_id}@{branch_id}`（主分支 `branch_id = main`）。一个 campaign 默认一个主分支 = 一个 thread。
- **存档 = 双源**：① checkpointer thread 快照（L1 图状态）；② 领域库（L2 权威）。存档点 = `post_turn` 结束时的 turn 边界快照，形成**存档时间线**。
- **领域库 append-only + 版本化 + 分叉**：所有事件与状态变更带 `branch_id + turn_id`；当前值按"（分支内）目标 turn 之前的最新版本"查询；不做物理删除（event-sourcing-lite）。
- **分叉时间线**：`restore(turn_id)` 从该历史点**创建新分支并切换**——后续事件写入新 `branch_id`，原分支完整保留、可随时切回；`timeline` 默认展示当前分支，可列出全部分支。
- **两种操作区分**：
  - 断点续玩：恢复当前分支最新 checkpoint，不重掷（M2 出口标准）；
  - 读档回滚：选定历史 turn → 新建分支 + 恢复该 checkpoint + 按目标 turn 重建 L2，骰子默认重掷、seed 留档。
- **对外 API**：
  - `GET /campaigns/{id}/timeline`（分支与回合时间线，默认当前分支）
  - `POST /campaigns/{id}/restore {turn_id}`（从历史回合创建新分支并切换）
  - `POST /campaigns/{id}/switch {branch_id}`（切换到既有分支）

## 8. 错误处理与降级矩阵

| 节点 | 失败处理 | 回合是否推进 |
|---|---|---|
| validate（gm_decide 输出） | repair 重试 1 次（把校验错误反馈给模型） | 失败则不推进，提示重试 |
| resolve_checks | 纯代码 + 单测覆盖，理论不失败；真异常时同上 | 失败则不推进 |
| memory_query | 降级为"无长期记忆"继续 | 推进（记忆是增强非阻塞） |
| npc_respond 单个 NPC | 该 NPC 沉默占位，其余正常 | 推进 |
| gm_narrate | repair 重试 1 次 | 失败则不推进，pending 清空，玩家重来 |

统一原则：**失败不推进时回到 `wait_input`，本轮 pending 丢弃**——与"读档重掷"语义一致，简单可靠。

## 9. 成本控制与预算熔断

- 分级路由（GM=千问 / NPC=DeepSeek / 提取=便宜档）+ 上下文组装 + 按需 NPC 激活 + 滚动摘要压缩（token 阈值触发）。
- **定价表配置化**：`config/pricing.yaml` 存每模型 input/output 单价，模型价格变化只改 YAML。
- **用量记账**：每次 LLM 调用记录 `{role, model, tokens_in/out, cost_estimate, latency, turn_id}`；前端提供"本局成本"面板。
- **预算熔断（事前约束）**：每回合 token 上限 + 每局成本上限（配置化）。超阈值按**降级阶梯**逐级触发：
  - ① 记忆检索降档（只给最近摘要）
  - ② NPC 收缩到仅保留 gm_decide 指定的首位相关 NPC
  - ③ GM 换便宜模型兜底
  - ④ 超每局上限 → **战役熔断暂停**（UI 明示原因，手动恢复或调高预算）
- **检查点两处**：回合开始（gm_decide 前）+ 每次 LLM 调用前（`llm/` 单元内预算检查）；熔断状态挂在 campaign 上。

## 10. 可观测性

- **LangSmith tracing**（LangGraph 原生集成）：节点级回放，学习工具 + 简历点。
- **本地降级**：LangSmith 不可用时 trace 写本地 JSONL，最小字段对齐 run 格式（`run_id / parent_run_id / name / run_type / inputs / outputs / start_time / end_time / error`）；开发环境零网络依赖，联网后可按需上传。
- **`/metrics` JSON 端点**（不引入 Prometheus），四个核心指标：① 每回合延迟 ② LLM 调用成功率 ③ 降级触发次数 ④ NPC 激活数量分布。数据来源 = 用量记账表（持久）+ 进程内运行时计数器（重启清零，明确声明）。
- 结构化日志 + WS `error` 事件通道。

## 11. 测试策略

分层（前两层不碰网络）：

1. `rules / content / storage / JournalMemory`：纯 pytest 单测，全分支；
2. graph 节点级：**FakeLLM**（可编程响应 + 调用记录）测编排逻辑——路由、降级、Send 并行、interrupt/resume；
3. graph 集成：**录制回放**——LLM 响应 + 骰子 seed 录成 fixture，整图确定性跑通完整回合 / 整局脚本；
4. api：TurnBuffer 状态机四场景（单提交/双提交/超时/窗口外）+ WS 集成测试；
5. 前端：DiceOverlay / 叙事流组件测试 + 端到端手测清单。

**Fixture 管理**：

- 路径：`tests/fixtures/{module}/{scenario}/turn_{n}.json`；每个文件记录该回合 LLM 响应与骰子 seed。
- pytest `--record` 模式重录（需真实 key + 网络）；回放模式**零网络零 key**；LLM 升级后重录即新基线。

**覆盖率口径（实施验收）**：

- rules 100%；
- content 校验器：每条规则正/反用例；
- storage：仓储契约测试全通过；
- graph：所有路由分支 + 每条降级路径 ≥1 用例；
- api TurnBuffer：四种场景。

## 12. 模组内容格式（骨架）

```yaml
meta:      { id, title, author, version, system: coc-lite }
opening:   { narration, scene_id, player_goal }
scenes:    [ { id, name, description, npcs: [], exits: [], clues: [] } ]
npcs:      [ { id, name, persona, knowledge: [], initial_attitude } ]
clues:     [ { id, content, unlocks: [] } ]
endings:   [ { id, condition } ]
```

加载器做**静态可达性校验**：所有引用存在（NPC/线索/场景）、场景图连通、每个结局从开局可达。完整字段表在实施计划中细化。

## 13. 里程碑

| 里程碑 | 内容 | 出口标准 |
|---|---|---|
| M1 地基 | 仓库骨架、pyproject、docker-compose、rules + 单测、content 加载器 + 校验、storage 模型 + 仓储 | pytest 全绿 |
| M2 单机闭环 | llm 路由与记账、主图 + NPC 子图 + 降级、JournalMemory、CLI 可玩 | CLI 完成回合循环；杀进程后能断点续玩 |
| M3 可玩 Web | FastAPI + WS、TurnBuffer(N=1)、React 房间页 + 骰子动画 + 角色卡 + 打字机、示例模组 | 浏览器里跑完示例模组一条结局线 |
| M4 多人部署 | 全员窗口/超时、visibility、邀请码、腾讯云部署 | 两个浏览器联机玩一回合 |
| M5 增强（可选） | Graphiti 适配器、LangSmith/成本面板、奖惩骰、战斗子图 | 按项定义 |

## 14. 明确不做（YAGNI）

语音 TTS/STT；地图/战棋；完整 COC 规则书（战斗轮、成长、疯狂表——只保留轻量检定核心）；账号密码体系（邀请码即可）；模组编辑器/模组市场；手机端适配；实时抢麦（回合缓冲已替代）；多语言。

## 15. 假设与依赖

- Python 3.12+；后端包管理 uv；LangGraph + langgraph-checkpoint-sqlite。
- 千问（DashScope OpenAI 兼容端点）+ DeepSeek API key。
- Node 20+（Vite 标准脚手架）；前端 React + Vite + TS + zustand。
- Docker：本地与腾讯云同一套 docker-compose。
- LangSmith 可选（不可用时本地 JSONL 降级）。
- 示例模组：原创小镇神秘事件题材，同时作为测试 fixture 与演示内容。
