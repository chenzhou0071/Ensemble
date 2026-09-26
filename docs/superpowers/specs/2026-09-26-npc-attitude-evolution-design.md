# NPC 好感度演化设计（Phase 1：队伍级）

> **状态：未来方向 / 未排期** —— 不属于 M1-M5 任何已锁定计划；当前 v1 实现不包含本设计。
> **采纳路径**：需要实施时，以本文档为输入走 writing-plans 生成实施计划；不采纳则长期作为设计资产留档。
> **前置依赖**：M2 图管线（intake / validate / post_turn）稳定。与 M3/M4/M5 并行不冲突（不修改其任何任务）。
> **日期**：2026-09-26

---

## 1. 背景与现状

好感度在当前系统中是"**管道全通、阀门未装**"状态（已全量核实）：

- **初始值**：模组 YAML `NpcDef.initial_attitude`（一份，全员共享；默认 50）
- **装载**：intake `snap.get("npc_attitudes") or {n.id: n.initial_attitude for n in module.npcs}`；**回合内只读**（规格 §4 不变量）
- **提示词消费**：gm_decide 上下文"当前态度 N"；NPC 子图"态度值：0 敌对 - 50 中立 - 100 友善"
- **持久化**：post_turn `append_state({"npc_attitudes": ...})` 快照落 L2，读档/分支/回放继承
- **变更逻辑**：全链路零处 —— `GmDecision` / `NpcReaction` 均无变化量字段，无任何赋值

后果：NPC 脾气各异但"江山易改"——贿赂、威胁不会改变长期观感。本设计补齐"变化规则"。

## 2. 目标与非目标

**目标**

- GM 语义判定 + 代码数值管辖：LLM 只说"谁变了、为什么"，代码决定"变多少、是否允许"
- 有界：单回合净变化 ≤ ±15，态度值域 [0, 100]（写死常量，无配置项）
- 可解释：每次变化携带 reason 落事件流
- 可回放：应用逻辑为 rules 层纯函数，既有回放基线逐字不变（**向后兼容是硬要求**）
- 变化**自下一回合起生效**：回合内态度只读的不变量不破坏（结算在 post_turn，回合末）

**非目标（本 Phase 明确不做）**

- 每人矩阵（→ §7 Phase 2 路线图）
- 前端展示（飘字/关系面板）——本设计只到事件层
- 离场 NPC 被修改（必须在场）
- 态度驱动的玩法硬效果（价格折扣、敌对开战等）与时间衰减/回归中立——独立未来增强
- 任何配置项（`Settings` 不新增字段）

## 3. 机制设计

### 3.1 GM 输出契约

`GmDecision` 新增字段（`schemas.py`）：

```python
class AttitudeDelta(BaseModel):
    npc_id: str
    delta: int            # 建议 -15..15；代码最终截断
    reason: str = ""


class GmDecision(BaseModel):
    ...
    attitude_deltas: list[AttitudeDelta] = Field(default_factory=list)   # 代码最多取前 2 条
```

`DECIDE_SYSTEM` 追加说明（与现有字段说明同风格）：

```
attitude_deltas(数组，元素 {"npc_id","delta"(整数),"reason"})：
仅当玩家行为在本回合实质影响了某在场 NPC 对你们的态度时给出，最多 2 条，否则空数组；
npc_id 只能用当前场景内列出的；delta 按行为严重程度取 -15..15，拿不准就不给。
```

### 3.2 硬边界纯函数（rules 层，写死常量）

`app/rules/attitude.py`：

```python
MAX_DELTAS_PER_TURN = 2            # 保序取前 2 条
MAX_DELTA_ABS = 15                 # 单条与净变化双重上限
ATTITUDE_MIN, ATTITUDE_MAX = 0, 100


def apply_attitude_deltas(
    current: dict[str, int],
    deltas: list[dict],            # decision["attitude_deltas"] 原始 JSON
    present_npcs: set[str],        # 当前场景在场 npc_id 集合
) -> tuple[dict[str, int], list[dict]]:
    """返回 (新态度表副本, 变更记录)。纯函数，不抛异常，不修改入参。

    语义（写死）：
    1. 取前 MAX_DELTAS_PER_TURN 条（保序）
    2. npc_id 不在 present_npcs → 丢弃该条（静默，与战斗 target 非法同口径）
    3. delta 非 int（含 bool）→ 丢弃该条；单条截断到 ±MAX_DELTA_ABS
    4. 同 npc 多条合并求和 → 净变化再截断到 ±MAX_DELTA_ABS
    5. old = current.get(npc_id, 50)；new = clamp(old + net, ATTITUDE_MIN, ATTITUDE_MAX)
    6. net == 0 或 new == old → 不更新、不记录
    7. 变更记录元素：{"npc_id", "old", "new", "delta"(净), "reason"}(取该 npc 首条 reason)
    """
```

### 3.3 应用点：post_turn（单点写入）

在 `build_post_turn_node`（M3 起签名 `(repo, memory, module=None)`，module 已注入）内：

1. `deltas = (state.get("decision") or {}).get("attitude_deltas", [])`
2. `present = set(module.scene(state["scene_id"]).npcs)`（module 为 None 时跳过适用性与应用，零行为变化）
3. `attitudes, changes = apply_attitude_deltas(state.get("npc_attitudes", {}), deltas, present)`
4. 有变更时：返回值 dict 携带新 `npc_attitudes` + 每条 `repo.add_event(..., type="attitude", payload=..., visibility="all")`
5. 既有 `append_state({"npc_attitudes": ...})` 快照**自动持久化**，无迁移

**为何选 post_turn**：单点写入、与快照同处、降级路径零特判（`decision_invalid` 时本就不进 post_turn）。被否方案：validate 直改（校验节点带副作用）、resolve 即时改（写入分散）。

### 3.4 事件契约

```python
repo.add_event(campaign_id, branch_id, turn_id, type="attitude",
               payload={"npc_id": ..., "old": ..., "new": ..., "delta": ..., "reason": ...},
               visibility="all")
```

- 与 `turn_start / check / narration / clue / combat` 同级，落 L2 事件流
- `visibility="all"`：有反馈才有玩法闭环；M4 的 visibility 过滤机制天然适用
- reason 仅随事件留档，**不进任何后续提示词**
- 前端展示不在本设计；未来从事件流取用，零后端改动

### 3.5 不动的部分

- intake 装载逻辑（已支持）、gm_decide 的"当前态度 N"上下文、NPC 子图提示词（态度只读影响语气）

## 4. 容错（写死）

| 场景 | 行为 |
| --- | --- |
| npc_id 非法/不在场 | 静默丢弃该条，回合不中断 |
| delta 非整数（含 bool/字符串） | 丢弃该条 |
| 全部丢弃 / 净变化为 0 | 不更新、不写事件 |
| 应用过程任何异常 | 不更新态度，回合照常收尾（态度功能独立于回合成败） |
| 旧 decision 无该字段 | `default_factory=list` → 零行为变化 |

## 5. 契约与影响面清单（实施时）

| 文件 | 变化 |
| --- | --- |
| `app/graph/schemas.py` | 新增 `AttitudeDelta`；`GmDecision` 加 `attitude_deltas`（默认空） |
| `app/rules/attitude.py` | 新文件：常量 + `apply_attitude_deltas` |
| `app/graph/nodes/turn.py` | post_turn 内应用 + 写 `attitude` 事件 |
| `app/graph/nodes/gm.py` | `DECIDE_SYSTEM` 追加字段说明 |
| 存储/迁移 | **无**（事件 payload 为 JSON；快照同构） |
| 回放 fixture | 既有全部不变；新增一条含态度变化的场景 |

## 6. 测试与验收口径（若实施）

- **rules**：clamp / 同 NPC 合并 / 在场过滤 / 非 int / 净 0 / 0 与 100 卡边 逐项单测；覆盖率 100%（rules 口径，规格 §11）
- **post_turn 集成**：变更有事件 + 快照含新值 + 返回的 turn 推进与既有行为一致
- **兼容（硬验收）**：全部既有回放基线逐字不变
- **正向回放**：新增场景 —— GM 输出 `delta=-10` → 事件 old=40/new=30 → 下一回合 GM 提示词态度为 30
- **容错**：注入非法 npc_id 与非法 delta → 丢弃、无事件、无异常

## 7. Phase 2 路线图（每人矩阵，只给要点，届时另文细化）

- 形状升级：`npc_attitudes: dict[npc_id, dict[character_id, int]]`；delta 契约加 `character_id`（或 `target: "party" | <id>`）
- 读档宽容迁移：旧格式（int）按"全员同值"展开
- 提示词：GM 看矩阵（每 NPC × 每角色）；NPC 子图取"对当前发言角色"的值
- 记忆：`memory_queries` 如"guard_1 对玩家的态度"升级为按角色检索
- UI：关系面板（M3 前端外延）
- 触发条件：Phase 1 稳定运行 + M3/M4 完成后评估（GM token 与校验复杂度显著上升）

## 8. 版本与状态

| 日期 | 状态 | 说明 |
| --- | --- | --- |
| 2026-09-26 | 未来方向（未排期） | 初稿；设计评审确认：机制 = GM 判定 + 代码硬边界；范围 = 两阶段（先队伍级） |
