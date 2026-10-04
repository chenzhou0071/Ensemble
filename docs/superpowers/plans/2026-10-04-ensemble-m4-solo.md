# Ensemble M4（单人版）实施计划：即时结算 / 暗骰 / 战役归属 / 部署

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Ensemble 从"多人桌机制"收敛为"单人一局"：提交即结算（无窗口/无超时/无防抖）、每人只能看到并游玩自己浏览器创建的战役、GM 暗骰对玩家不可见；并用同一套 docker-compose 部署到腾讯云（或本机），公网单人可玩为出口标准。

**Architecture:** ① `TurnBuffer` 瘦身为纯输入暂存（open/submit/close），`SessionManager.handle_submit` 在收到提交时立即收口并后台驱动图，删除窗口定时器/超时/防抖与相关配置；② 前端 localStorage 生成 `client_id`，创建战役写入 `Campaign.owner_client_id`，列表/详情/WS 三个入口按 `owner in ("", client_id)` 过滤（空 owner = 升级前历史档，兼容可见）；③ 暗骰沿用 `CheckRequest.secret` → `DiceRecordRow.secret` → 事件 `visibility="gm"` 链路，实时推送与重连回放两侧过滤；④ 容器化与腾讯云部署从旧计划平移（单人口径）。

**Tech Stack:** FastAPI、SQLModel + SQLite（轻量迁移）、LangGraph、React + Vite + TS + zustand、Docker Compose + nginx、腾讯云轻量应用服务器。

**依赖前置:** M1、M2、M3 全部完成且测试全绿（本计划直接引用其接口、夹具与文件）。

## Global Constraints

（规格摘录——每个任务都隐式包含本节）

- Python 3.12+；后端依赖管理 `uv`；Node 20+；前端测试用 Vitest + Testing Library。
- 所有后端测试零网络、零 API key（FakeLLM 工厂注入）；异步测试依赖 `pytest-asyncio`（`asyncio_mode = "auto"`，M3-10 已配置）。
- **单人模型**：一个战役恰有一个玩家（`create_campaign` 即建此人）；不存在邀请/加入/多人窗口逻辑，任何"等待人齐""超时推进"的机制都不得再引入。
- `TurnBuffer` 不再持有任何时间概念：提交即收口；驱动为后台任务（`RoomSession.drive_task`），同会话内驱动严格串行（下一次由上一次收口时派发）。
- 数据库变更一律走 `migrate_schema`（PRAGMA 检查 + ALTER ADD COLUMN，幂等），不破坏历史数据语义。
- 每个任务结束提交一次（本地 commit）；**不推送**（用户确认后才推送）。
- 中文 UI 文案与注释；前端 TS strict，类型注解齐全。

## 与旧计划的关系

- 旧计划 `docs/superpowers/plans/2026-09-24-ensemble-multiplayer-deploy.md` 已标注作废（2026-10-04）：邀请码/多人窗口/玩家栏/联机 E2E 全部取消；其中仍有效的 **暗骰可见性**（原文 Task M4-5）与 **Docker/腾讯云部署**（原文 Task M4-6）两节平移进本计划（任务 M4-2、M4-4）。
- `docs/superpowers/plans/2026-09-24-ensemble-enhancements.md`（M5）中的 M4 任务号引用已同步修正到本计划编号。

## 决策记录（用户 2026-10-04 拍板）

1. **统一阻塞**：不需要等待窗口/超时——单人提交即结算。结算期间到达的输入顺延到下一轮（`pending_next`），收口后自动进入下一轮结算，不丢失、不要求重新输入。
2. **战役归属**：每人只能看到/游玩自己创建的战役；浏览器 `client_id`（localStorage 持久化）为归属键；无主历史档（升级前数据，`owner_client_id=""`）对任何浏览器可见（保护用户已有存档不消失），新建战役一律带 owner。
3. **暗骰**：GM 可声明 `secret=true` 的检定——L2 完整落库，玩家通道（实时 + 回放 + 重连）不可见；无 GM 客户端，暗骰事件供未来 God 视角复用。
4. **部署**：docker-compose 单人栈（backend + frontend/nginx），公网单人可玩为 M4 出口标准。

## 文件结构（M4 新增/修改总览）

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `backend/app/api/turn_buffer.py` | 改 | 瘦身：去窗口/超时/防抖/时间参数 |
| `backend/app/api/session.py` | 改 | 提交即收口驱动；去定时器；暗骰推送过滤 |
| `backend/app/config.py` | 改 | 删 `turn_window_seconds` / `single_player_debounce_seconds` |
| `backend/app/storage/models.py` | 改 | `DiceRecordRow.secret`、`Campaign.owner_client_id` |
| `backend/app/storage/db.py` | 改 | `migrate_schema` + `_ensure_column`（幂等补列），`init_db` 调用 |
| `backend/app/storage/repo.py` | 改 | `add_dice_record(secret=)`、`create_campaign(owner_client_id=)` |
| `backend/app/graph/schemas.py` | 改 | `CheckRequest.secret` |
| `backend/app/graph/nodes/turn.py` | 改 | `resolve_checks` 透传 secret（暗骰不进玩家流） |
| `backend/app/graph/nodes/gm.py` | 改 | `DECIDE_SYSTEM` 暗骰说明；`_check_lines` 暗骰标注 |
| `backend/app/api/routes.py` | 改 | 战役列表/详情按 `client_id` 过滤；创建带 owner |
| `backend/app/api/ws.py` | 改 | WS 连接校验战役归属 |
| `frontend/src/client.ts` | 增 | `getClientId()`：localStorage 持久化的浏览器标识 |
| `frontend/src/api/rest.ts` | 改 | `campaigns/campaign/createCampaign` 带 `client_id` |
| `frontend/src/api/ws.ts` | 改 | WS URL 带 `client_id` |
| `frontend/src/views/Lobby.tsx` | 改 | 传 `client_id` |
| `frontend/src/views/Room.tsx` | 改 | WsClient 传 `client_id` |
| `backend/tests/...` | 增/改 | 即时结算、迁移、暗骰、归属、WS E2E 适配 |
| `frontend/src/...` | 增/改 | client 测试与既有测试适配 |
| `backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx.conf`、`docker-compose.yml` | 增/改 | 生产镜像与编排（平移） |
| `.env.example`、`docs/deploy-tencent.md` | 增 | 部署密钥模板与腾讯云指南 |
| `README.md` | 改 | 单人验收清单 |

---

### Task M4-1: 单人即时结算（提交即结算）

**Files:**
- Modify: `backend/app/api/turn_buffer.py`（整文件重写）
- Modify: `backend/app/api/session.py`（`RoomSession`、`_assemble`、`handle_submit`、`_open_window`、`on_branch_switch`、`close`、`_drive`）
- Modify: `backend/app/config.py`（删两个窗口配置字段）
- Modify: `backend/tests/api/test_turn_buffer.py`（整文件重写）
- Modify: `backend/tests/api/test_session.py`（替换 1 个用例、新增 2 个用例、fixture 去参）
- Modify: `backend/tests/api/test_ws.py`、`backend/tests/api/test_ws_ending_e2e.py`（fixture 去参）
- Modify: `backend/tests/test_config.py`（去 `turn_window_seconds` 断言）

**Interfaces:**
- Consumes: `TurnBuffer`（M3-9）、`SessionManager`/`RoomSession`（M3-10）、`EventBus`（M3-8）、`Command`/`graph.stream`（M3）
- Produces：
  - `TurnBuffer.open(turn_id: int, active_players: list[str]) -> None`：开窗（无 `now`；不再返回 epoch）
  - `TurnBuffer.submit(player_id: str, entry: dict) -> str`：`"accepted" | "deferred" | "ignored"`（无 `now`）
  - `TurnBuffer.close() -> dict`：产出 `{"turn_id", "inputs", "skipped"}`（语义不变）
  - 删除的 API（本计划内任何地方不得再引用）：`TurnBuffer.window_seconds` / `single_player_debounce_seconds` / `last_submit_ts` / `epoch` / `should_close` / `all_submitted`；`RoomSession.window_task` / `window_started` / `driving`；`SessionManager._window_timer` / `_TICK_SECONDS`；`Settings.turn_window_seconds` / `Settings.single_player_debounce_seconds`
  - `SessionManager.handle_submit`：`"accepted"` 时**立即** `buffer.close()` 并派发后台驱动任务（`asyncio.create_task`），不再等防抖/定时器
  - `RoomSession.drive_task: asyncio.Task | None`：进行中的驱动任务（提交派发 / 收口后顺延派发均写此字段）；`close()` 与 `on_branch_switch()` 中 cancel 未完成任务
  - `_open_window`：open 后若 `buffer.submissions` 非空（结算期间顺延的提交）→ 立即收口并派发驱动

- [ ] **Step 1: 重写 `backend/tests/api/test_turn_buffer.py`（新语义）**

整文件替换为：

```python
from app.api.turn_buffer import TurnBuffer


def entry(p, text):
    return {"player_id": p, "character_id": f"pc_{p}", "text": text,
            "submitted_at": ""}


def test_submit_then_close_yields_payload():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    assert buf.phase == "collecting"
    assert buf.submit("p1", entry("p1", "进门")) == "accepted"
    payload = buf.close()
    assert payload["turn_id"] == 1 and payload["skipped"] == []
    assert payload["inputs"][0]["text"] == "进门"
    assert buf.phase == "idle"


def test_resubmit_overwrites_before_close():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    buf.submit("p1", entry("p1", "第一次"))
    buf.submit("p1", entry("p1", "改主意了"))
    payload = buf.close()
    assert [i["text"] for i in payload["inputs"]] == ["改主意了"]


def test_submit_between_windows_deferred_to_next():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    buf.submit("p1", entry("p1", "第一回合"))
    buf.close()
    assert buf.submit("p1", entry("p1", "抢在下一轮前")) == "deferred"
    buf.open(2, ["p1"])
    payload = buf.close()
    assert payload["turn_id"] == 2
    assert [i["text"] for i in payload["inputs"]] == ["抢在下一轮前"]


def test_unknown_player_ignored():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    assert buf.submit("ghost", entry("ghost", "x")) == "ignored"
    assert buf.close()["skipped"] == ["p1"]
```

（旧文件中 `should_close`/防抖/超时/epoch 相关用例随机制删除。）

- [ ] **Step 2: 替换/新增 `backend/tests/api/test_session.py` 用例**

fixture `room` 的 `Settings(...)` 去掉 `single_player_debounce_seconds=0.1,` 与 `turn_window_seconds=3.0)` 两行（其余参数保留）。

删除 `test_single_player_window_never_auto_closes_on_timeout`（窗口超时机制已不存在）。

在文件末尾追加：

```python
async def test_submit_settles_immediately(room):
    """提交即结算：handle_submit 返回时本回合已收口（无防抖/定时器等待），
    结算完成后自动开启下一轮输入窗口。"""
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。",
                              TURN_DECIDE, "你蹲下查看井边。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    assert session.buffer.phase == "collecting"

    sub = session.bus.subscribe("__test__")      # 先订阅再提交：actor 广播不遗漏
    try:
        status = await manager.handle_submit(campaign.id, player.id, "我绕到喷泉后面")
        assert status == "accepted"
        assert session.buffer.phase == "idle"    # 已收口：无需等待任何窗口
        events = await collect_until(sub, lambda evts: any(
            e.type == "turn" and e.payload.get("phase") == "collecting"
            and e.payload.get("turn_id") == 2 for e in evts))
    finally:
        session.bus.unsubscribe(sub)
    assert any(e.type == "state" for e in events)
    assert any(e.type == "actor" for e in events)
    assert session.buffer.phase == "collecting"  # 结算完自动开下一窗口
    await manager.close()


async def test_submission_during_settlement_defers_to_next_turn(room):
    """结算期间再次提交：顺延到下一轮并自动结算（不覆盖、不丢弃、不需重新输入）。"""
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。",
                              TURN_DECIDE, "你蹲下查看井边。",
                              TURN_DECIDE, "你继续探查。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    assert session.buffer.phase == "collecting"

    sub = session.bus.subscribe("__test__")
    try:
        assert await manager.handle_submit(campaign.id, player.id, "第一轮行动") == "accepted"
        # 此刻驱动已派发（后台任务尚未跑完）：立即提交第二条 → 必须顺延而非覆盖
        assert await manager.handle_submit(campaign.id, player.id, "抢跑") == "deferred"
        events = await collect_until(sub, lambda evts: any(
            e.type == "turn" and e.payload.get("phase") == "collecting"
            and e.payload.get("turn_id") == 3 for e in evts))
    finally:
        session.bus.unsubscribe(sub)
    assert session.buffer.phase == "collecting"
    await manager.close()


async def test_idle_room_never_drives_without_input(room):
    """无提交则系统静止：没有超时空跑，回合不推进（防挂机烧钱）。"""
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)

    await asyncio.sleep(0.3)
    snap = session.graph.get_state(session.config)
    assert int((snap.values or {}).get("turn_id", 0)) == 1
    assert session.buffer.phase == "collecting"
    await manager.close()
```

- [ ] **Step 3: 验证失败（RED）**

Run: `cd backend; uv run pytest tests/api/test_turn_buffer.py tests/api/test_session.py -q`
Expected: FAIL ——
- `test_turn_buffer.py`：`TypeError: open() missing 1 required positional argument: 'now'`（旧实现仍要求 `now`；`submit` 同理）
- `test_session.py`：`assert session.buffer.phase == "idle"` 失败（旧实现提交后仍在防抖窗口 `collecting`）；`test_submission_during_settlement_defers_to_next_turn` 第二条提交返回 `"accepted"`（覆盖）而非 `"deferred"`

- [ ] **Step 4: 重写 `backend/app/api/turn_buffer.py`**

整文件替换为：

```python
"""单人回合缓冲：暂存本回合输入，收口时产出 interrupt resume payload。

单人即结算：提交即由 SessionManager 收口驱动，无需窗口/超时/防抖；
结算期间到达的输入顺延到下一轮（pending_next）。
"""
from dataclasses import dataclass, field


@dataclass
class TurnBuffer:
    phase: str = "idle"                        # idle | collecting
    turn_id: int | None = None
    active_players: list[str] = field(default_factory=list)
    submissions: dict[str, dict] = field(default_factory=dict)
    pending_next: dict[str, dict] = field(default_factory=dict)

    def open(self, turn_id: int, active_players: list[str]) -> None:
        self.phase = "collecting"
        self.turn_id = turn_id
        self.active_players = list(active_players)
        self.submissions = dict(self.pending_next)   # 窗口间隙的提交顺延入本轮
        self.pending_next = {}

    def submit(self, player_id: str, entry: dict) -> str:
        if player_id not in self.active_players:
            return "ignored"
        if self.phase == "collecting":
            self.submissions[player_id] = entry     # 后发覆盖前发
            return "accepted"
        self.pending_next[player_id] = entry
        return "deferred"

    def close(self) -> dict:
        """收口并产出 interrupt resume payload（TurnInputs.model_dump() 结构）。"""
        inputs = [self.submissions[p] for p in self.active_players
                  if p in self.submissions]
        skipped = [p for p in self.active_players if p not in self.submissions]
        payload = {"turn_id": self.turn_id, "inputs": inputs, "skipped": skipped}
        self.phase = "idle"
        self.turn_id = None
        self.submissions = {}
        return payload
```

- [ ] **Step 5: 改造 `backend/app/api/session.py`**

1. 删除模块常量 `_TICK_SECONDS = 0.05`（连同其上一行注释，如有）。
2. `RoomSession` 字段区：删除 `driving: bool = False`；`window_task: asyncio.Task | None = None` 与 `window_started: float = 0.0` 两行替换为：

```python
    drive_task: asyncio.Task | None = None
```

3. `_assemble` 中 `TurnBuffer(window_seconds=..., single_player_debounce_seconds=(...))` 替换为：

```python
            buffer=TurnBuffer(),
```

4. `on_branch_switch` 中旧任务取消逻辑：

```python
                if old.window_task is not None and not old.window_task.done():
                    old.window_task.cancel()
```

替换为：

```python
                if old.drive_task is not None and not old.drive_task.done():
                    old.drive_task.cancel()
```

5. `close()` 中：

```python
            if session.window_task is not None and not session.window_task.done():
                session.window_task.cancel()
```

替换为：

```python
            if session.drive_task is not None and not session.drive_task.done():
                session.drive_task.cancel()
```

6. `handle_submit` 的 `"accepted"` 分支替换为（新增收口与派发）：

```python
        status = session.buffer.submit(player_id, entry)
        if status == "accepted":
            session.bus.push("actor", {"player_id": player_id, "text": entry["text"]})
            # 单人即结算：提交即收口，后台驱动（不再等待窗口/防抖/超时）
            payload = session.buffer.close()
            session.drive_task = asyncio.create_task(
                self._drive(session, Command(resume=payload,
                                             update={"branch_id": session.branch_id})))
        elif status == "deferred":
```

（`elif status == "deferred":` 原通知逻辑保持不变。）

7. `_drive` 中删除两处驱动标记（`session.driving = True` 与 `finally: session.driving = False`），收口为：

```python
        try:
            await asyncio.to_thread(_run)
        finally:
            pass
```

改为：

```python
        await asyncio.to_thread(_run)
```

8. `_open_window` 与 `_window_timer` 两段整体替换为：

```python
    def _open_window(self, session: RoomSession) -> None:
        players = [p.id for p in session.repo.list_players(session.campaign_id)]
        snap = session.graph.get_state(session.config)
        turn_id = int((snap.values or {}).get("turn_id", 0))
        session.buffer.open(turn_id, players)
        session.bus.push("turn", {"phase": "collecting", "turn_id": turn_id})
        if session.buffer.submissions:      # 结算期间的顺延提交：立即驱动下一轮
            payload = session.buffer.close()
            session.drive_task = asyncio.create_task(
                self._drive(session, Command(resume=payload,
                                             update={"branch_id": session.branch_id})))
```

（原 `_window_timer` 方法整体删除。）

- [ ] **Step 6: 清理 `backend/app/config.py` 与两个 WS 测试 fixture**

`backend/app/config.py` 的 `Settings` 中删除两行：

```python
    turn_window_seconds: int = 60
```
```python
    single_player_debounce_seconds: float = 2.0
```

`backend/tests/api/test_ws.py` 与 `backend/tests/api/test_ws_ending_e2e.py` 的 `Settings(...)` 构造中均删除：

```python
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=3.0)
```

（`test_ws_ending_e2e.py` 为 `turn_window_seconds=10.0)`，同样删除这两行。）

`backend/tests/test_config.py` 第 7 行：

```python
    assert s.gm_model == "qwen3.8-flash" and s.turn_window_seconds == 60
```

改为：

```python
    assert s.gm_model == "qwen3.8-flash"
```

- [ ] **Step 7: 验证通过（GREEN）+ 全量回归**

Run: `cd backend; uv run pytest tests/api/test_turn_buffer.py tests/api/test_session.py tests/api/test_ws.py tests/test_config.py -q`
Expected: PASS —— 新用例全绿；`test_ws.py` 往返测试不受影响（提交后结算更快，`collecting turn_id=2` 仍会被推送）

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 后端全量测试全绿（本任务预计只动上列文件；若 `test_ws_ending_e2e.py` 因时序变化偶发失败，先重跑确认是否为既有假阴性）

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/turn_buffer.py backend/app/api/session.py backend/app/config.py backend/tests/api/test_turn_buffer.py backend/tests/api/test_session.py backend/tests/api/test_ws.py backend/tests/api/test_ws_ending_e2e.py backend/tests/test_config.py
git commit -m "refactor(api): solo immediate settlement, drop turn window and debounce"
```

---

### Task M4-2: 暗骰与事件可见性（含迁移基建）

**Files:**
- Modify: `backend/app/storage/models.py`（`DiceRecordRow.secret`）
- Modify: `backend/app/storage/db.py`（`_ensure_column` + `migrate_schema`；`init_db` 调用）
- Modify: `backend/app/storage/repo.py`（`add_dice_record(..., secret=)`）
- Modify: `backend/app/graph/schemas.py`（`CheckRequest.secret`）
- Modify: `backend/app/graph/nodes/turn.py`（`resolve_checks` 透传 secret；暗骰不进玩家流）
- Modify: `backend/app/graph/nodes/gm.py`（`DECIDE_SYSTEM` 暗骰说明；`_check_lines` 暗骰标注）
- Modify: `backend/app/api/session.py`（`_backfill` 骰子推送可见性；`resync_payload` 过滤）
- Test: `backend/tests/storage/test_migration.py`（新建）、`backend/tests/graph/test_resolve_checks.py`（追加）、`backend/tests/graph/test_gm_narrate.py`（追加）、`backend/tests/graph/test_gm_decide.py`（追加）、`backend/tests/api/test_secret_dice.py`（新建）

**Interfaces:**
- Consumes: `CheckRequest`/`GmDecision`/`parse_decision_json`（M2-11）、`resolve_checks`（M2-13，现含结局纠偏与骰子流式推送）、`add_dice_record`（M2-9，现返回 `int` id）、`stream_writer`（M3）、`EventBus`（M3-8）、`_backfill`/`resync_payload`（M3-10）
- Produces：
  - `DiceRecordRow.secret: bool = False`；`add_dice_record(..., seed: int, secret: bool = False) -> int`（保留返回 id）
  - `migrate_schema(engine: Engine) -> None`；`_ensure_column(conn, table, column, ddl) -> None`：旧库幂等补列；`init_db = create_all + migrate_schema`
  - `CheckRequest.secret: bool = False`：GM 可要求"玩家角色察觉不到的暗骰"；经 `GmDecision.model_dump()` 进入 `decision["checks"]`（缺省 false，向后兼容）
  - `resolve_checks`：暗骰 `check` 事件 `visibility="gm"`、`check_results` 元素带 `"secret"`、**不写实时 dice 流**（`writer` 跳过——实时通道无法按订阅者过滤）；**保留**既有结局纠偏块
  - `_backfill` 骰子重放：`visibility="gm" if row.secret else "all"`；`resync_payload`：dice 列表剔除暗骰
  - `DECIDE_SYSTEM`：checks 字段说明含 `"secret"(bool，可选，默认 false)` + 规则第 9 条；`_check_lines`：暗骰行尾追加"（暗骰：不得在叙事中直接暴露……）"

- [ ] **Step 1: 写失败测试（五处）**

`backend/tests/storage/test_migration.py`（新建）：

```python
"""轻量迁移：历史库（缺列）经 init_db 后可用新字段，且幂等。"""
import sqlite3

from sqlmodel import Session

from app.storage.db import init_db, make_engine
from app.storage.models import DiceRecordRow


def test_init_db_migrates_legacy_dice_record_table(tmp_path):
    db = tmp_path / "legacy_dice.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE dicerecordrow ("
        "id INTEGER NOT NULL PRIMARY KEY, campaign_id VARCHAR NOT NULL,"
        "branch_id VARCHAR NOT NULL, turn_id INTEGER NOT NULL, actor VARCHAR NOT NULL,"
        "skill VARCHAR NOT NULL, skill_value INTEGER NOT NULL,"
        "difficulty VARCHAR NOT NULL, roll INTEGER NOT NULL, level VARCHAR NOT NULL,"
        "seed INTEGER NOT NULL, created_at DATETIME NOT NULL)")
    conn.execute("INSERT INTO dicerecordrow VALUES "
                 "(1, 'c1', 'c1@main', 1, 'pc_1', '侦查', 50, 'regular', 23, 'hard',"
                 " 7, '2026-01-01 00:00:00')")
    conn.commit()
    conn.close()

    engine = make_engine(str(db))
    init_db(engine)
    init_db(engine)                                    # 幂等：重复调用不报错

    with Session(engine) as s:
        row = s.get(DiceRecordRow, 1)
        assert row is not None and row.secret is False  # 历史行补列为默认 false


def test_init_db_fresh_database_has_secret_column(tmp_path):
    engine = make_engine(str(tmp_path / "fresh.db"))
    init_db(engine)
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(dicerecordrow)")}
    assert "secret" in cols
```

`backend/tests/graph/test_resolve_checks.py` 末尾追加：

```python
def test_secret_check_marks_record_and_event(node, repo, campaign):
    """暗骰：落库 secret=True、check 事件 visibility="gm"、结果带 secret 标。"""
    upd = node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular", "secret": True}]}))
    assert upd["check_results"][0]["secret"] is True
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 1 and rows[0].secret is True
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])
    assert events[0].visibility == "gm"


def test_regular_check_defaults_to_visible(node, repo, campaign):
    """未标暗骰：行为与现状完全一致（secret=False、事件 all）。"""
    node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular"}]}))
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert rows[0].secret is False
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])
    assert events[0].visibility == "all"
```

`backend/tests/graph/test_gm_narrate.py` 末尾追加：

```python
def test_prompt_marks_secret_check(campaign, mini_module):
    """暗骰标注进叙事提示词：不得直接暴露其检定与结果。"""
    client, built = make_client(["有效叙事。"])
    state = base_state(campaign, check_results=[{
        "actor": "pc_1", "skill": "聆听", "roll": 30, "skill_value": 50,
        "level": "regular", "success": True, "seed": 2, "secret": True}])
    build_narrate_node(client, mini_module)(state)
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "暗骰" in prompt and "不得在叙事中直接暴露" in prompt
```

`backend/tests/graph/test_gm_decide.py` 末尾追加：

```python
def test_decide_system_documents_secret_dice():
    """暗骰契约：checks 元素可带 secret；其检定与结果不得在叙事中直接暴露。"""
    assert "secret" in DECIDE_SYSTEM and "暗骰" in DECIDE_SYSTEM
```

`backend/tests/api/test_secret_dice.py`（新建）：

```python
"""暗骰可见性：玩家通道收不到 secret 骰子事件，但 L2 落库完整、重连回放过滤。"""
import asyncio
from dataclasses import asdict
from pathlib import Path

import pytest

from app.api.app import AppDeps
from app.api.session import SessionManager
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')


def decide(char_id: str, skill: str, secret: bool) -> str:
    flag = "true" if secret else "false"
    return ('{"intent_summary": "行动", "checks": ['
            f'{{"actor": "{char_id}", "skill": "{skill}", "difficulty": "regular",'
            f' "secret": {flag}}}],'
            ' "proactive_npc_triggers": [], "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


@pytest.fixture
def solo(tmp_path):
    engine = make_engine(str(tmp_path / "secret.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "secret.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        extractor_model="qwen-extract")   # 摘要隔离：后台线程不抢脚本
    campaign = repo.create_campaign("misty_hollow", "暗骰")
    player = repo.add_player(campaign.id, "张三")
    char = make_default_character(player.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    return repo, settings, campaign, player, char


async def collect(sub, predicate, timeout=8.0):
    """以玩家身份订阅后收集事件；超时未见 predicate 即失败。"""
    events = []
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            evt = await asyncio.wait_for(sub.queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        events.append(evt)
        if predicate(events):
            return events
    raise AssertionError(f"condition not met; got {[e.type for e in events]}")


def collecting_turn(turn_id: int):
    return lambda evts: any(e.type == "turn" and e.payload.get("phase") == "collecting"
                            and e.payload.get("turn_id") == turn_id for e in evts)


async def test_secret_dice_hidden_from_players_but_kept_in_l2(solo):
    repo, settings, campaign, player, char = solo
    factory = script_factory([
        OPENING_DECIDE, "雾气笼罩着广场。",
        decide(char.id, "聆听", secret=True), "你听见井底传来若有若无的水声。",
        decide(char.id, "侦查", secret=False), "你在井边石缝里找到一枚铜扣。",
    ])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)

    sub = session.bus.subscribe(player.id)      # 以玩家身份订阅：只应收到可见事件
    try:
        assert await manager.handle_submit(campaign.id, player.id, "我侧耳倾听井底") == "accepted"
        round1 = await collect(sub, collecting_turn(2))
        assert not any(e.type == "dice" for e in round1)      # 暗骰不达玩家

        rows = repo.list_dice_records(campaign.id, campaign.active_branch_id)
        assert len(rows) == 1 and rows[0].secret is True      # 但 L2 完整落库
        events = repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])
        assert events[0].visibility == "gm"

        assert await manager.handle_submit(campaign.id, player.id, "我检查井边石缝") == "accepted"
        round2 = await collect(sub, collecting_turn(3))
        dice = [e for e in round2 if e.type == "dice"]
        assert len(dice) == 1 and dice[0].payload["skill"] == "侦查"   # 明骰照常可见

        snap = manager.resync_payload(session)                # 重连回放不含暗骰
        assert [d["skill"] for d in snap["dice"]] == ["侦查"]
    finally:
        session.bus.unsubscribe(sub)
        await manager.close()
```

- [ ] **Step 2: 验证失败（RED）**

Run: `cd backend; uv run pytest tests/storage/test_migration.py tests/graph/test_resolve_checks.py tests/graph/test_gm_decide.py tests/graph/test_gm_narrate.py tests/api/test_secret_dice.py -q`
Expected: FAIL ——
- `test_migration.py`：`AttributeError: 'DiceRecordRow' object has no attribute 'secret'`（或建旧表后 `secret` 列不存在）
- `test_resolve_checks.py`：`KeyError: 'secret'`（结果无该键）
- `test_gm_decide.py` / `test_gm_narrate.py`：断言失败（提示词无暗骰文案）
- `test_secret_dice.py`：玩家通道收到了暗骰 `dice` 事件（旧代码无过滤）

- [ ] **Step 3: 实现存储层（models / db / repo）**

`backend/app/storage/models.py` 的 `DiceRecordRow` 在 `seed` 之后插入一行：

```python
    seed: int
    secret: bool = False          # 暗骰：L2 保留，但不对玩家可见
    created_at: datetime = Field(default_factory=_now)
```

`backend/app/storage/db.py`：文件头部 import 保持 `Engine` 类型可用（现有 `from sqlalchemy.engine import Engine` 已具备），在 `init_db` 之前新增两个函数并改写 `init_db`：

```python
def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """旧表缺列时补列（SQLModel.create_all 不会修改已存在的表）。"""
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    if rows and column not in {r[1] for r in rows}:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def migrate_schema(engine: Engine) -> None:
    """轻量迁移清单：每列一行，幂等可重复执行。"""
    with engine.begin() as conn:
        _ensure_column(conn, "dicerecordrow", "secret",
                       "secret BOOLEAN NOT NULL DEFAULT 0")


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    migrate_schema(engine)
```

`backend/app/storage/repo.py` 的 `add_dice_record` 整体替换（**保留返回 int 与 flush 结构**）：

```python
    def add_dice_record(self, campaign_id: str, branch_id: str, turn_id: int, actor: str,
                        skill: str, skill_value: int, difficulty: str, roll: int,
                        level: str, seed: int, secret: bool = False) -> int:
        with Session(self.engine) as s:
            row = DiceRecordRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                                actor=actor, skill=skill, skill_value=skill_value,
                                difficulty=difficulty, roll=roll, level=level, seed=seed,
                                secret=secret)
            s.add(row)
            s.flush()
            rid = int(row.id)
            s.commit()
            return rid
```

- [ ] **Step 4: 实现图与提示词（schemas / turn / gm）**

`backend/app/graph/schemas.py` 的 `CheckRequest`：

```python
class CheckRequest(BaseModel):
    actor: str
    skill: str
    difficulty: CheckDifficulty = CheckDifficulty.REGULAR
    secret: bool = False          # true=暗骰：玩家角色无从察觉，叙事不得直接暴露
```

`backend/app/graph/nodes/turn.py` 的 `build_resolve_checks_node` 整体替换（**保留结局纠偏块与 writer 结构**）：

```python
def build_resolve_checks_node(repo):
    def resolve_checks(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        checks = (state.get("decision") or {}).get("checks", [])
        writer = stream_writer()
        results = []
        for chk in checks:
            actor, skill = chk["actor"], chk["skill"]
            secret = bool(chk.get("secret"))
            skill_value = _skill_value(state, actor, skill)
            seed = new_seed()
            r = roll_check(actor, skill, skill_value,
                           CheckDifficulty(chk.get("difficulty", "regular")), seed)
            rid = repo.add_dice_record(campaign_id, branch_id, turn_id, r.actor, r.skill,
                                       r.skill_value, str(r.difficulty), r.roll, str(r.level),
                                       r.seed, secret=secret)
            # 骰子先出：明骰掷后立即经流式通道推送（先于叙事 token；收口快照按 id 去重兜底）；
            # 暗骰不进实时流——流式通道无法按订阅者过滤，其可见性由收口快照统一兜底
            if not secret:
                writer({"dice": {"id": rid, "actor": r.actor, "skill": r.skill,
                                 "skill_value": r.skill_value, "difficulty": str(r.difficulty),
                                 "roll": r.roll, "level": str(r.level),
                                 "success": r.success, "seed": r.seed}})
            verdict = "成功" if r.success else "失败"
            repo.add_event(campaign_id, branch_id, turn_id, type="check",
                           payload={"text": f"{actor} 的「{skill}」检定：{r.roll}/{r.skill_value} "
                                            f"→ {r.level}（{verdict}）",
                                    "roll": r.roll, "level": str(r.level), "success": r.success,
                                    "secret": secret},
                           visibility="gm" if secret else "all")
            results.append({"actor": r.actor, "skill": r.skill, "roll": r.roll,
                            "skill_value": r.skill_value, "level": str(r.level),
                            "success": r.success, "seed": r.seed,
                            "difficulty": str(r.difficulty), "secret": secret})
        upd: dict = {"check_results": results}
        # 结局动作的检定失败 → 本回合不收束（decide 判定时尚未掷骰，此处按结果纠正，
        # 防"检定失败但结局盲发"；叙事与路由随之按未收束走）
        decision = state.get("decision") or {}
        if decision.get("ending_reached") and any(not r["success"] for r in results):
            upd["decision"] = {**decision, "ending_reached": None}
        return upd

    return resolve_checks
```

`backend/app/graph/nodes/gm.py` 两处：

`DECIDE_SYSTEM` 的 checks 字段行与规则区结尾（**在现行文本基础上做最小增量，勿重写全文**）：

```python
    'checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme),"secret"(bool，可选，默认 false)})、'
```

```python
    "8. 玩家与 NPC 的社交行动即使检定失败，也要让该 NPC 在场回应（冷淡、回避、暗示皆可），不得让场面停滞或写成拒绝交流。\n"
    "9. secret=true 表示玩家角色无从察觉的暗骰（如暗中进行的观察或聆听）；其检定与结果不得在叙事中直接暴露。"
```

`_check_lines` 整体替换：

```python
def _check_lines(state: GameState) -> str:
    lines = []
    for c in state.get("check_results", []):
        verdict = "成功" if c.get("success") else "失败"
        note = ("（暗骰：不得在叙事中直接暴露该检定与结果，只可化为隐约的线索或不安感）"
                if c.get("secret") else "")
        lines.append(f"- {_char_name(state, c.get('actor'))}的「{c['skill']}」："
                     f"{c['roll']}/{c['skill_value']} → {c['level']}（{verdict}）{note}")
    return "\n".join(lines) or "（本回合无检定）"
```

- [ ] **Step 5: 实现会话推送过滤（session）**

`backend/app/api/session.py` 两处：

`_backfill` 中骰子重放推送：

```python
            session.bus.push("dice", _dice_payload(row))
```

替换为：

```python
            session.bus.push("dice", _dice_payload(row),
                             visibility="gm" if row.secret else "all")
```

`resync_payload` 中 records 读取：

```python
        rows = session.repo.list_dice_records(session.campaign_id, session.branch_id)
```

替换为：

```python
        rows = [r for r in session.repo.list_dice_records(session.campaign_id,
                                                          session.branch_id)
                if not r.secret]
```

- [ ] **Step 6: 验证通过（GREEN）+ 全量回归**

Run: `cd backend; uv run pytest tests/storage tests/graph tests/api -q`
Expected: PASS —— 新用例全绿；`resolve_checks`/`gm_narrate`/`gm_decide` 既有用例不受影响（无 secret 时行为与提示词增量不破坏既有断言）

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 后端全量测试全绿

- [ ] **Step 7: Commit**

```bash
git add backend/app/storage/models.py backend/app/storage/db.py backend/app/storage/repo.py backend/app/graph/schemas.py backend/app/graph/nodes/turn.py backend/app/graph/nodes/gm.py backend/app/api/session.py backend/tests/storage/test_migration.py backend/tests/graph/test_resolve_checks.py backend/tests/graph/test_gm_narrate.py backend/tests/graph/test_gm_decide.py backend/tests/api/test_secret_dice.py
git commit -m "feat(api): secret dice with GM-only visibility, schema migration harness"
```

---

### Task M4-3: 战役归属隔离（每人只见自己的战役）

**Files:**
- Modify: `backend/app/storage/models.py`（`Campaign.owner_client_id`）
- Modify: `backend/app/storage/db.py`（`migrate_schema` 追加一行）
- Modify: `backend/app/storage/repo.py`（`create_campaign(owner_client_id=)`）
- Modify: `backend/app/api/routes.py`（创建带 owner；列表/详情过滤）
- Modify: `backend/app/api/ws.py`（WS 连接校验归属）
- Create: `frontend/src/client.ts`
- Modify: `frontend/src/api/rest.ts`、`frontend/src/api/ws.ts`、`frontend/src/views/Lobby.tsx`、`frontend/src/views/Room.tsx`
- Test: `backend/tests/storage/test_migration.py`（追加）、`backend/tests/api/test_campaign_ownership.py`（新建）、`frontend/src/__tests__/client.test.ts`（新建）、`frontend/src/api/__tests__/rest.test.ts`、`frontend/src/api/__tests__/ws.test.ts`、`frontend/src/views/__tests__/Lobby.test.tsx`、`frontend/src/views/__tests__/Room.test.tsx`（适配）

**Interfaces:**
- Consumes: `Campaign`（M2）、`migrate_schema`/`_ensure_column`（M4-2）、`SqliteRepository`（M2）、WS 端点（M3-11）、`api`/`WsClient`（M3-12~16）
- Produces：
  - `Campaign.owner_client_id: str = Field(default="", index=True)`（空 = 升级前历史档）
  - `migrate_schema` 清单追加：`campaign.owner_client_id`
  - `SqliteRepository.create_campaign(module_id: str, title: str, owner_client_id: str = "") -> Campaign`
  - `POST /api/campaigns` body 新增 `client_id: str = ""`；创建时写 owner（响应不变）
  - `GET /api/campaigns?client_id=`：`owner in ("", client_id)`（缺省 client_id → 只返回无主档，无后门）
  - `GET /api/campaigns/{id}?client_id=`：`owner not in ("", client_id)` → 404
  - WS `/ws/campaign/{id}?player_id=&resume_from=&client_id=`：归属不匹配 → close 4404（在 `ensure_started` 之前，不触发任何图驱动）
  - 前端 `getClientId(): string`：localStorage key `ensemble.client_id`；16 字节 hex；`crypto.getRandomValues` 优先（纯 IP HTTP 部署非安全上下文亦可用），不可用则退化为 `Math.random`
  - 前端 `api.campaigns(clientId)` / `api.campaign(id, clientId)` / `api.createCampaign(moduleId, title, playerName, clientId)`；`new WsClient(campaignId, playerId, clientId, handlers)`

- [ ] **Step 1: 写失败测试（后端两处 + 前端四处）**

`backend/tests/storage/test_migration.py`：import 区改为

```python
from app.storage.models import Campaign, DiceRecordRow
```

文件末尾追加：

```python
def test_init_db_migrates_legacy_campaign_owner_column(tmp_path):
    db = tmp_path / "legacy_owner.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE campaign ("
        "id VARCHAR NOT NULL PRIMARY KEY, module_id VARCHAR NOT NULL,"
        "title VARCHAR NOT NULL, active_branch_id VARCHAR NOT NULL,"
        "created_at DATETIME NOT NULL)")
    conn.execute("INSERT INTO campaign VALUES "
                 "('c1', 'misty_hollow', '旧战役', 'c1@main', '2026-01-01 00:00:00')")
    conn.commit()
    conn.close()

    engine = make_engine(str(db))
    init_db(engine)
    init_db(engine)                                     # 幂等

    with Session(engine) as s:
        row = s.get(Campaign, "c1")
        assert row is not None and row.owner_client_id == ""   # 历史行补列为默认空
```

`backend/tests/api/test_campaign_ownership.py`（新建）：

```python
"""战役归属：列表/详情/WS 三入口按 client_id 隔离；无主历史档兼容可见。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


@pytest.fixture
def world(tmp_path):
    engine = make_engine(str(tmp_path / "own.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "own.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        extractor_model="qwen-extract")
    app = create_app(AppDeps(settings=settings, repo=repo,
                             model_factory=script_factory(
                                 [OPENING_DECIDE, "雾气笼罩着广场。"] * 4)))
    return TestClient(app), repo


def create(c, title: str, client_id: str) -> str:
    return c.post("/api/campaigns",
                  json={"module_id": "misty_hollow", "title": title,
                        "player_name": "张三", "client_id": client_id}
                  ).json()["campaign_id"]


def test_list_shows_only_own_campaigns(world):
    c, _ = world
    alice = create(c, "爱丽丝的档", "alice")
    create(c, "鲍勃的档", "bob")
    rows = c.get("/api/campaigns?client_id=alice").json()
    assert [r["id"] for r in rows] == [alice]


def test_legacy_ownerless_campaign_visible_to_all(world):
    """升级前的历史档（无 owner）：任何浏览器可见（保护已有存档不消失）。"""
    c, repo = world
    legacy = repo.create_campaign("misty_hollow", "旧档").id     # 未传 owner
    assert [r["id"] for r in c.get("/api/campaigns?client_id=alice").json()] == [legacy]
    assert [r["id"] for r in c.get("/api/campaigns?client_id=bob").json()] == [legacy]


def test_list_without_client_id_hides_owned_campaigns(world):
    """缺省 client_id 只能看到无主档：owner 档不泄露给未标识客户端。"""
    c, _ = world
    create(c, "爱丽丝的档", "alice")
    assert c.get("/api/campaigns").json() == []


def test_detail_rejects_foreign_client(world):
    c, _ = world
    alice = create(c, "爱丽丝的档", "alice")
    assert c.get(f"/api/campaigns/{alice}?client_id=alice").status_code == 200
    assert c.get(f"/api/campaigns/{alice}?client_id=bob").status_code == 404
    assert c.get(f"/api/campaigns/{alice}").status_code == 404


def test_ws_rejects_foreign_client(world):
    c, repo = world
    bob = create(c, "鲍勃的档", "bob")
    player = repo.list_players(bob)[0]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(
                f"/ws/campaign/{bob}?player_id={player.id}&client_id=alice") as ws:
            ws.receive_text()


def test_ws_accepts_owner_client(world):
    """归属者连 WS：进入正常事件流（收到开场结算后的 collecting 窗口）。"""
    c, repo = world
    bob = create(c, "鲍勃的档", "bob")
    player = repo.list_players(bob)[0]
    with c.websocket_connect(
            f"/ws/campaign/{bob}?player_id={player.id}&client_id=bob") as ws:
        for _ in range(50):
            evt = json.loads(ws.receive_text())
            if evt["type"] == "turn" and evt["payload"].get("phase") == "collecting":
                return
        raise AssertionError("no collecting window before stream end")
```

`frontend/src/__tests__/client.test.ts`（新建）：

```ts
import { beforeEach, describe, expect, it } from "vitest";

import { getClientId } from "../client";

beforeEach(() => localStorage.clear());

describe("getClientId", () => {
  it("generates and persists a hex id", () => {
    const first = getClientId();
    expect(first).toMatch(/^[0-9a-f]{32}$/);
    expect(getClientId()).toBe(first);                 // 再次调用：复用持久化值
    expect(localStorage.getItem("ensemble.client_id")).toBe(first);
  });

  it("reuses a pre-existing client id", () => {
    localStorage.setItem("ensemble.client_id", "abc123");
    expect(getClientId()).toBe("abc123");
  });
});
```

`frontend/src/api/__tests__/rest.test.ts`：`createCampaign` 用例更新为带 clientId 调用与断言，并追加列表用例：

```ts
  it("POSTs create campaign with json body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ campaign_id: "c1" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await api.createCampaign("misty_hollow", "初探", "张三", "client-1");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toBe("/api/campaigns");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      module_id: "misty_hollow", title: "初探", player_name: "张三",
      client_id: "client-1",
    });
  });

  it("GETs campaign list scoped by client_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    await api.campaigns("client-1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/campaigns?client_id=client-1");
  });
```

`frontend/src/api/__tests__/ws.test.ts`：`makeClient` 构造加 `"client-1"`，URL 断言改为：

```ts
    expect(ws.url).toContain("/ws/campaign/c1?player_id=p1&resume_from=0&client_id=client-1");
```

`frontend/src/views/__tests__/Lobby.test.tsx`：
- 顶部追加 client 模块 mock：

```ts
vi.mock("../../client", () => ({ getClientId: () => "test-client" }));
```

- 第一个用例追加断言（在 `await waitFor(...)` 之后）：

```ts
    expect(mocked.campaigns).toHaveBeenCalledWith("test-client");
    expect(mocked.createCampaign).toHaveBeenCalledWith(
      "misty_hollow", "迷雾山谷", "调查员", "test-client");
```

- 第二个用例追加断言（在 `await waitFor(...)` 之后）：

```ts
    expect(mocked.campaign).toHaveBeenCalledWith("c9", "test-client");
```

`frontend/src/views/__tests__/Room.test.tsx`：`WsClient` mock 签名加第三参：

```ts
  WsClient: vi.fn().mockImplementation((_c: string, _p: string, _cid: string, h: typeof handlers) => {
```

- [ ] **Step 2: 验证失败（RED）**

Run: `cd backend; uv run pytest tests/storage/test_migration.py tests/api/test_campaign_ownership.py -q`
Expected: FAIL —— `AttributeError: 'Campaign' object has no attribute 'owner_client_id'`；`POST /api/campaigns` 忽略 `client_id`（406/断言失败）；列表未过滤（alice 看到 bob 的档）；WS 未拒绝外部 client

Run: `cd frontend; npm run test -- client rest ws Lobby Room`
Expected: FAIL —— `../client` 模块不存在（import 失败）；`campaigns` 调用缺 client_id 参数；WsClient URL 无 `client_id`；Room mock 参数错位

- [ ] **Step 3: 实现后端存储与路由**

`backend/app/storage/models.py` 的 `Campaign`：

```python
class Campaign(SQLModel, table=True):
    id: str = Field(primary_key=True)
    module_id: str
    title: str
    active_branch_id: str
    owner_client_id: str = Field(default="", index=True)   # 归属浏览器标识；空=升级前历史档
    created_at: datetime = Field(default_factory=_now)
```

`backend/app/storage/db.py` 的 `migrate_schema`：

```python
def migrate_schema(engine: Engine) -> None:
    """轻量迁移清单：每列一行，幂等可重复执行。"""
    with engine.begin() as conn:
        _ensure_column(conn, "dicerecordrow", "secret",
                       "secret BOOLEAN NOT NULL DEFAULT 0")
        _ensure_column(conn, "campaign", "owner_client_id",
                       "owner_client_id VARCHAR NOT NULL DEFAULT ''")
```

`backend/app/storage/repo.py` 的 `create_campaign`：

```python
    def create_campaign(self, module_id: str, title: str,
                        owner_client_id: str = "") -> Campaign:
        campaign_id = uuid.uuid4().hex[:12]
        branch = Branch(id=f"{campaign_id}@main", campaign_id=campaign_id, name="main")
        campaign = Campaign(id=campaign_id, module_id=module_id, title=title,
                            active_branch_id=branch.id, owner_client_id=owner_client_id)
        with Session(self.engine) as s:
            s.add(branch)
            s.add(campaign)
            s.commit()
            s.refresh(campaign)
        return campaign
```

`backend/app/api/routes.py` 三处：
1. `CreateCampaignRequest`：

```python
class CreateCampaignRequest(BaseModel):
    module_id: str
    title: str
    player_name: str = "调查员"
    client_id: str = ""                # 归属浏览器标识（M4 单人版）
```

2. `create_campaign` 端点中创建调用改为：

```python
    campaign = deps.repo.create_campaign(module.meta.id, req.title,
                                         owner_client_id=req.client_id)
```

3. `list_campaigns` 与 `get_campaign`：

```python
@router.get("/campaigns")
def list_campaigns(request: Request, client_id: str = ""):
    """单人归属：只返回本 client 创建的档；无主历史档兼容可见。

    缺省 client_id 时仅返回无主档——owner 档不泄露给未标识客户端。"""
    repo = _deps(request).repo
    from app.storage.models import Campaign
    from sqlmodel import Session, select, or_
    with Session(repo.engine) as s:
        rows = s.exec(select(Campaign)
                      .where(or_(Campaign.owner_client_id == client_id,
                                 Campaign.owner_client_id == ""))
                      .order_by(Campaign.created_at.desc())).all()
    out = []
    for c in rows:
        out.append({"id": c.id, "title": c.title, "module_id": c.module_id,
                    "active_branch_id": c.active_branch_id,
                    "created_at": c.created_at.isoformat()})
    return out
```

```python
@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, request: Request, client_id: str = ""):
    import json
    deps = _deps(request)
    repo = deps.repo
    try:
        campaign = repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    if campaign.owner_client_id not in ("", client_id):
        raise HTTPException(status_code=404, detail="campaign not found")
    ...（其余保持不变）
```

`backend/app/api/ws.py` 的 `ws_campaign` 头部（在 `deps.manager` 检查之后、player 检查之前插入）：

```python
    try:
        campaign = deps.repo.get_campaign(campaign_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    if campaign.owner_client_id not in ("", client_id):
        await websocket.close(code=4404)
        return
    player = deps.repo.get_player(player_id)
    if player is None or player.campaign_id != campaign_id:
        await websocket.close(code=4404)
        return
```

签名改为：

```python
@router.websocket("/ws/campaign/{campaign_id}")
async def ws_campaign(websocket: WebSocket, campaign_id: str,
                      player_id: str = Query(...), resume_from: int = Query(0),
                      client_id: str = Query("")):
```

- [ ] **Step 4: 实现前端**

`frontend/src/client.ts`（新建）：

```ts
const KEY = "ensemble.client_id";

/** 浏览器客户端标识：首次访问生成并持久化，用于战役归属隔离（每人只见自己创建的档）。 */
export function getClientId(): string {
  try {
    const existing = localStorage.getItem(KEY);
    if (existing) return existing;
    const id = randomHex();
    localStorage.setItem(KEY, id);
    return id;
  } catch {
    return randomHex();      // 隐私模式等不可写场景：本次会话内临时有效
  }
}

function randomHex(): string {
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);   // 非 HTTPS 的纯 IP 部署也可用（randomUUID 要求安全上下文）
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}
```

`frontend/src/api/rest.ts`：

```ts
  campaigns: (clientId: string) =>
    jsonFetch<CampaignInfo[]>(`/api/campaigns?client_id=${encodeURIComponent(clientId)}`),
  createCampaign: (moduleId: string, title: string, playerName: string, clientId: string) =>
    postJson<CreateResult>("/api/campaigns", {
      module_id: moduleId, title, player_name: playerName, client_id: clientId,
    }),
  campaign: (id: string, clientId: string) =>
    jsonFetch<CampaignDetail>(
      `/api/campaigns/${id}?client_id=${encodeURIComponent(clientId)}`),
```

`frontend/src/api/ws.ts`：

```ts
  constructor(
    private campaignId: string,
    private playerId: string,
    private clientId: string,
    private handlers: WsHandlers,
  ) {}
```

```ts
    const url = `${proto}://${location.host}/ws/campaign/${this.campaignId}` +
      `?player_id=${this.playerId}&resume_from=${this.lastSeq}` +
      `&client_id=${encodeURIComponent(this.clientId)}`;
```

`frontend/src/views/Lobby.tsx`：
- import：`import { getClientId } from "../client";`
- `useEffect` 中：`api.campaigns(getClientId()).then(setCampaigns).catch(() => {});`
- `create()` 中：`const r = await api.createCampaign(moduleId, title, playerName, getClientId());`
- `continueCampaign()` 中：`const detail = await api.campaign(c.id, getClientId());`，并把过时注释

```ts
      const player = detail.players[0]; // M3 单人；M4 改为邀请码/选择玩家
```

改为：

```ts
      const player = detail.players[0];       // 单人档：唯一玩家即本档玩家
```

`frontend/src/views/Room.tsx`：
- import：`import { getClientId } from "../client";`
- 构造：

```ts
    const client = new WsClient(session.campaignId, session.playerId, getClientId(), {
      onEvent: (evt) => useGame.getState().apply(evt),
      onStatus: (s) => useGame.getState().setConnected(s === "open"),
    });
```

- [ ] **Step 5: 验证通过（GREEN）**

Run: `cd backend; uv run pytest tests/storage tests/api -q`
Expected: PASS —— 归属用例全绿；`test_campaigns_api.py` / `test_ws.py` / `test_ws_ending_e2e.py` / `test_session.py` 不受影响（测试档均为无主档，放行）

Run: `cd frontend; npm run test`
Expected: PASS —— client 新用例 + rest/ws/Lobby/Room 适配后全绿

Run: `cd frontend; npm run build`
Expected: 无类型错误（TS strict 下新签名编译通过）

- [ ] **Step 6: 全量回归 + Commit**

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 后端全量测试全绿

```bash
git add backend/app/storage/models.py backend/app/storage/db.py backend/app/storage/repo.py backend/app/api/routes.py backend/app/api/ws.py backend/tests/storage/test_migration.py backend/tests/api/test_campaign_ownership.py frontend/src/client.ts frontend/src/__tests__/client.test.ts frontend/src/api/rest.ts frontend/src/api/ws.ts frontend/src/api/__tests__/rest.test.ts frontend/src/api/__tests__/ws.test.ts frontend/src/views/Lobby.tsx frontend/src/views/Room.tsx frontend/src/views/__tests__/Lobby.test.tsx frontend/src/views/__tests__/Room.test.tsx
git commit -m "feat: per-client campaign ownership with browser client id isolation"
```

---

### Task M4-4: 容器化与腾讯云部署（单人口径）

**Files:**
- Modify: `backend/Dockerfile`（替换 M2 占位 → uv 生产镜像）
- Create: `backend/.dockerignore`
- Create: `frontend/Dockerfile`、`frontend/nginx.conf`、`frontend/.dockerignore`
- Modify: `docker-compose.yml`（两服务生产编排）
- Create: `.env.example`
- Modify: `.gitignore`（追加 `data/`、`dist/`）
- Create: `docs/deploy-tencent.md`
- Modify: `README.md`（追加 Docker 部署节与单人验收清单）

**Interfaces:**
- Consumes: `app.serve:app`（M3-17）、`GET /healthz`（M3-5）、WS `/ws/campaign/{id}?client_id=`（M4-3）、前端 `npm run build`（M3-12）、`backend/uv.lock`（M2-1 已提交）、`frontend/package-lock.json`（M3-12 已提交）
- Produces：
  - backend 镜像：`uv sync --frozen --no-dev`（venv 在 `/srv/.venv`）；镜像级环境 `ENSEMBLE_SQLITE_PATH=/data/ensemble.db`、`ENSEMBLE_MODULES_DIR=/modules`、`ENSEMBLE_PRICING_PATH=/config/pricing.yaml`
  - frontend 镜像：Node 构建 `dist` → nginx 托管；`/api/` 与 `/ws/`（Upgrade 头 + `proxy_read_timeout 3600s`）反代 `backend:8000`；SPA `try_files $uri /index.html`
  - compose：对外仅 `frontend` `80:80`；持久卷 `./data:/data`（SQLite 库）；只读挂载 `./modules:/modules:ro`、`./config:/config:ro`；两个 API key 由 compose 变量插值（读同目录 `.env`）
  - `.env.example`；`docs/deploy-tencent.md`（§5 为单人验收清单）；README Docker 节 + 单人浏览器验收清单

（说明：原旧计划 Task M4-6 的整体平移；旧 Task M4-7「联机双人 E2E」取消——单人 WS 全链路已由 `test_ws_ending_e2e.py` 覆盖，浏览器层验收改为下方手动清单。）

- [ ] **Step 1: 写 backend 镜像文件**

`backend/Dockerfile`（整文件替换）：

```dockerfile
FROM ghcr.io/astral-sh/uv:0.5 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 依赖层缓存：先只装依赖，再拷源码装项目（改代码不重装依赖）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev

ENV PATH="/srv/.venv/bin:$PATH" \
    ENSEMBLE_SQLITE_PATH=/data/ensemble.db \
    ENSEMBLE_MODULES_DIR=/modules \
    ENSEMBLE_PRICING_PATH=/config/pricing.yaml

EXPOSE 8000
CMD ["uvicorn", "app.serve:app", "--host", "0.0.0.0", "--port", "8000"]
```

`backend/.dockerignore`：

```
.venv
__pycache__
.pytest_cache
*.db
tests
```

- [ ] **Step 2: 写 frontend 镜像与 nginx**

`frontend/Dockerfile`：

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

`frontend/.dockerignore`：

```
node_modules
dist
```

`frontend/nginx.conf`：

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

- [ ] **Step 3: compose、env 模板与 .gitignore**

`docker-compose.yml`（整文件替换 M1 骨架）：

```yaml
services:
  backend:
    build: ./backend
    environment:
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-}
      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}
    volumes:
      - ./data:/data
      - ./modules:/modules:ro
      - ./config:/config:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  frontend:
    build: ./frontend
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped
```

`.env.example`：

```
# 复制为 .env 后填入真实密钥：cp .env.example .env
# compose 自动读取同目录 .env 做变量插值；.env 已被 .gitignore 忽略
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

`.gitignore` 追加两行（若尚未存在）：

```
data/
dist/
```

- [ ] **Step 4: 写部署文档（单人版）**

`docs/deploy-tencent.md`：

````markdown
# 腾讯云轻量应用服务器部署（Ensemble 单人版）

> 目标：把"本机 docker-compose 可玩"升级为"公网 IP 可玩"。全流程约 30 分钟。

## 1. 购买与初始化

- 腾讯云「轻量应用服务器」：Ubuntu 22.04，2 核 2G 起（单人玩足够）；
- 防火墙放行 `80/tcp`（HTTPS 再加 443），22 默认放行；
- 纯 IP 访问无需域名与备案；绑域名走 HTTPS 需备案。

## 2. 安装 Docker

SSH 登录后：

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker   # 免 sudo（重登生效）
docker compose version
```

## 3. 上传代码

```bash
git clone <你的仓库地址> ensemble && cd ensemble   # 或 scp 上传整个目录
```

## 4. 配置与启动

```bash
cp .env.example .env
vim .env          # 填 DASHSCOPE_API_KEY / DEEPSEEK_API_KEY
mkdir -p data
docker compose up -d --build
docker compose ps           # frontend running / backend healthy
```

## 5. 验收（M4 出口标准：公网单人可玩）

- 浏览器打开 `http://<公网IP>/` → 新建战役 → 进入房间；
- 提交行动 → **立刻结算**（无等待窗口）；结算完自动可输入下一回合；
- 刷新页面 → 历史完整回放，可继续行动；
- 换一台设备 / 另一个浏览器打开同地址 → 大厅「进行中」**看不到**前一浏览器的战役（归属隔离生效）；
- 玩到结局 → 结局叙事完整展示；
- GM 暗骰不出现在骰子日志中；
- 命令行冒烟：`curl http://<公网IP>/api/modules` 返回模组列表 JSON。

## 6. 日常运维

```bash
docker compose logs -f backend     # 看日志
docker compose up -d --build       # 更新代码后重建
docker compose down                # 停止
```

- 数据都在 `./data/ensemble.db`（SQLite），定期 `scp` 备份即可；
- 重启服务器后若未自启，见下方 systemd。

### 开机自启（可选）

`/etc/systemd/system/ensemble.service`：

```ini
[Unit]
Description=Ensemble docker compose
After=docker.service
Requires=docker.service

[Service]
WorkingDirectory=/home/ubuntu/ensemble
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now ensemble.service`

## 7. HTTPS（可选，绑定域名时）

- 腾讯云 SSL 证书（免费）挂载进 frontend 容器，nginx 加 443 server；
- 或前置 Caddy 反代；WebSocket 需 Upgrade 头透传（本项目 nginx.conf 已配置）。
````

- [ ] **Step 5: 更新 README**

在 README 的「启动（本地）」一节之后插入：

````markdown
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
````

- [ ] **Step 6: 验证（compose 静态校验 + 本机构建）**

Run: `docker compose config -q`（仓库根目录）

Expected: 无输出、退出码 0 —— compose 语法与变量插值通过（未创建 `.env` 也可校验）

Run: `docker compose up -d --build`（需本机 Docker Desktop；首次拉镜像需数分钟）

Expected: `docker compose ps` 显示 backend (healthy)、frontend (running)

Run: `curl http://localhost/api/modules`

Expected: JSON 列表含 `misty_hollow` —— nginx → backend 链路通

Run: `docker compose down`

Expected: 两容器停止（`./data/ensemble.db` 保留）

（若执行环境无 Docker：记录"未在本机构建验证"，部署时按 `docs/deploy-tencent.md` 第 5 节验收。）

- [ ] **Step 7: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore docker-compose.yml .env.example .gitignore docs/deploy-tencent.md README.md
git commit -m "feat(deploy): production docker images, nginx reverse proxy and compose stack (solo)"
```

---

## 计划自审（M4 单人版）

**需求覆盖表**（对照用户 2026-10-04 拍板范围 + 设计规格）：

| 需求 / 规格 | 覆盖任务 |
| --- | --- |
| 统一阻塞：提交即结算，无窗口 / 超时 / 防抖 | M4-1（`TurnBuffer` 瘦身、`handle_submit` 即收口、`pending_next` 顺延、idle 不空跑） |
| 战役归属隔离：每人只见 / 只玩自己创建的档 | M4-3（`client_id` 三入口过滤 + 前端 localStorage 标识 + 迁移） |
| 暗骰对玩家不可见（设计规格 §5.3 私密信息） | M4-2（`secret` 链路、实时 / 回放 / 重连三处过滤、L2 完整保留） |
| 腾讯云部署（单人可玩为出口） | M4-4（uv / nginx 生产镜像、compose、部署文档、单人验收清单） |
| 旧计划平移 | 原 M4-5 暗骰 → M4-2；原 M4-6 部署 → M4-4；原 M4-7 联机 E2E → 取消（单人 WS E2E `test_ws_ending_e2e.py` 已覆盖全链路） |

**已知边界（有意为之）**：
- `client_id` 是"防误入"级软隔离而非账号认证：清空 localStorage / 换浏览器即换身份；持有他人 `client_id` 字符串可直接访问其档——个人自用 / 轻量公网可接受，M5 若要硬化可升级为账号或签名 cookie。
- 无主历史档（`owner_client_id=""`）对任何浏览器可见：用于保护升级前的本机存档；腾讯云全新部署不存在无主档，故线上等价于完全隔离。
- 暗骰无 GM 客户端：`visibility="gm"` 事件保留在 EventBus 缓冲与 L2，M5 的 God 视角可直接复用。
- 结算期间到达的输入顺延到下一轮（后发覆盖）：不丢失、不要求重输；前端 InputBar 在 resolving 阶段禁用输入已天然防连发。
- 部署不含 HTTPS 终结自动化：纯 IP 走 HTTP（`getClientId` 用 `crypto.getRandomValues`，不依赖安全上下文）；绑域名时按 `docs/deploy-tencent.md` §7 挂证书。

**类型一致性抽查**：
- `client_id` 链路（6 处）：`client.ts getClientId()` → `rest.ts`（`?client_id=` 查询参数 / body `client_id`）→ `ws.ts`（`&client_id=`）→ `routes.py`（`client_id: str = ""`）→ `ws.py`（`client_id: str = Query("")`）→ `Campaign.owner_client_id`。**分层命名**：API 层一律 `client_id`，存储层一律 `owner_client_id`，映射仅在 `routes.py` 创建端点发生。
- `secret` 链路（5 处，M4-2）：`CheckRequest.secret` → `decision["checks"]` → `resolve_checks`（落库 + 事件 visibility）→ `DiceRecordRow.secret` → `_backfill` / `resync_payload` 过滤；前端无 secret 字段。
- `TurnBuffer` API（M4-1）：`open(turn_id, active_players) -> None`、`submit(player_id, entry) -> str`、`close() -> dict`；旧签名（`now` / epoch / `should_close`）全计划零引用。
- `drive_task`（M4-1，4 处）：`handle_submit` 派发、`_open_window` 顺延派发、`on_branch_switch` 取消、`close` 取消。
- `migrate_schema` 清单递进：M4-2 补 `dicerecordrow.secret`（含迁移测试）→ M4-3 追加 `campaign.owner_client_id`（含迁移测试）；两任务都先写"旧表缺列 → init_db 幂等补列"断言。
- 前端调用面：`getClientId` 仅 Lobby.tsx / Room.tsx 两处 import（M4-3）；`api.campaigns/campaign/createCampaign` 与 `new WsClient(...)` 的签名变更在同一任务的四处测试（rest / ws / Lobby / Room）内闭环适配。

---

## 执行交接（M4 单人版）

本计划 4 个任务按依赖序排列：

1. **M4-1 单人即时结算** —— 独立，无前置（只动 turn_buffer / session / config 与其测试）；
2. **M4-2 暗骰与迁移基建** —— 依赖 M4-1（新测试夹具基于无窗口语义）；
3. **M4-3 战役归属隔离** —— 依赖 M4-2（复用 `migrate_schema` 基建）；
4. **M4-4 容器化与部署** —— 依赖 M4-3（部署的是带归属隔离的单人版）。

每个任务自包含（RED → 实现 → GREEN → 回归 → commit），可独立测试与提交；任务间人工审查把关。

执行方式二选一：
1. **Subagent 逐任务执行（推荐）**：每个任务派发新的子代理实现，任务间人工审查；
2. **本会话内批量执行**：按 executing-plans 流水线推进，在检查点停顿复核。

交接前确认：
- M1 / M2 / M3 全部完成且测试全绿（`cd backend; uv run pytest -q`；`cd frontend; npm run test`）；
- 本机安装 Docker Desktop（M4-4 镜像构建验证需要；无 Docker 时按该任务 Step 6 备注处理）；
- 云端准备：腾讯云轻量应用服务器 + 两个 API key（M4-4 交付部署文档，浏览器层验收按 README「单人验收清单」在公网完成）。

---
