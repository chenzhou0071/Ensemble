# Ensemble 多人联机与部署（M4）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Ensemble 支持多人同桌：邀请码加入、全员回合窗口、掉线不阻塞、暗骰可见性，并用同一套 docker-compose 部署到腾讯云（或本机）。

**Architecture:** 在 M3 的 EventBus / TurnBuffer / SessionManager 之上小步扩展：邀请码与加入只加一列数据与一条 REST；多人窗口由 SessionManager 的在线玩家集合（presence）驱动开窗与掉线跳过；暗骰给 DiceRecord 打 secret 标记并在推送侧按 visibility 过滤；部署侧补全 Dockerfile / nginx / compose。

**Tech Stack:** FastAPI、SQLModel + SQLite（轻量迁移）、LangGraph、React + Vite + TS + zustand、Docker Compose + nginx、腾讯云轻量应用服务器。

**依赖前置:** M1、M2、M3 全部完成且测试全绿（本计划直接引用其接口、夹具与文件）。

## Global Constraints

（规格摘录——每个任务都隐式包含本节）

- Python 3.12+；后端依赖管理 `uv`；Node 20+；前端测试用 Vitest + Testing Library。
- 所有后端测试零网络、零 API key（FakeLLM 工厂注入）；异步测试依赖 `pytest-asyncio`（`asyncio_mode = "auto"`，M3-10 已配置）。
- 时间相关逻辑：`TurnBuffer` 由调用方注入 `now`；测试用 `single_player_debounce_seconds=0.1`、`turn_window_seconds=10.0` 等短常量，避免真实等待。
- 不引入新的 LLM 调用：多人功能全部在既有调用链上扩展，不增加成本面。
- 数据库变更一律走 `migrate_schema`（PRAGMA 检查 + ALTER ADD COLUMN，幂等），不破坏历史数据语义。
- 每个任务结束提交一次（本地 commit）；**不推送**（用户确认后才推送）。
- 中文 UI 文案与注释；前端 TS strict，类型注解齐全。

## 文件结构（M4 新增/修改总览）

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `backend/app/storage/models.py` | 改 | `Campaign.invite_code`、`DiceRecordRow.secret` |
| `backend/app/storage/db.py` | 改 | `migrate_schema`（幂等补列），`init_db` 调用 |
| `backend/app/storage/repo.py` | 改 | 邀请码生成/查询、`add_dice_record(secret=)` |
| `backend/app/api/routes.py` | 改 | `POST /api/campaigns/join`、detail 返回邀请码 |
| `backend/app/api/turn_buffer.py` | 改 | `mark_skipped` / `activate` / `cancel` |
| `backend/app/api/session.py` | 改 | presence 在线集、连接/断开钩子、开窗按在线集、暗骰过滤 |
| `backend/app/api/ws.py` | 改 | 连接注册与断开钩子 |
| `backend/app/graph/schemas.py` | 改 | `CheckRequest.secret` |
| `backend/app/graph/nodes/turn.py` | 改 | `resolve_checks` 透传 secret |
| `backend/app/graph/nodes/gm.py` | 改 | `DECIDE_SYSTEM` 暗骰说明 |
| `backend/tests/...` | 增 | 迁移/加入/多人窗口/暗骰/联机 E2E |
| `frontend/src/api/rest.ts` | 改 | `joinCampaign` |
| `frontend/src/views/Lobby.tsx` | 改 | 邀请码加入表单 |
| `frontend/src/views/Room.tsx` | 改 | 邀请码分享、玩家栏 |
| `frontend/src/stores/game.ts` | 改 | `players` / `submitted` 状态 |
| `frontend/src/types.ts` | 改 | `PlayerInfo`、`CampaignDetail.invite_code`、Turn/State payload 扩展 |
| `backend/Dockerfile` | 改 | 生产镜像（uv 多段） |
| `backend/.dockerignore`、`frontend/.dockerignore` | 增 | 构建上下文瘦身 |
| `frontend/Dockerfile`、`frontend/nginx.conf` | 增 | 前端构建 + 静态托管与反代 |
| `docker-compose.yml` | 改 | backend + frontend 两服务 |
| `.env.example`、`docs/deploy-tencent.md` | 增 | 部署密钥模板与腾讯云指南 |
| `README.md` | 改 | 联机手测清单 |

---

### Task M4-1: 战役邀请码与加入 API

**Files:**
- Modify: `backend/app/storage/models.py`（`Campaign.invite_code`）
- Modify: `backend/app/storage/db.py`（`migrate_schema`；`init_db` 末尾调用）
- Modify: `backend/app/storage/repo.py`（`create_campaign` 生成邀请码；`get_campaign_by_invite_code`）
- Modify: `backend/app/api/routes.py`（`POST /api/campaigns/join`；detail 返回 `invite_code`）
- Test: `backend/tests/storage/test_migration.py`、`backend/tests/api/test_join_api.py`

**Interfaces:**
- Consumes: `SqliteRepository`（M2）、`create_app`/`AppDeps`（M3-5/11）、`make_default_character`（M2）
- Produces：
  - `Campaign.invite_code: str = Field(default="", index=True)`（6 位大写十六进制如 `3F9A2C`；建战役时生成、全库唯一）
  - `migrate_schema(engine) -> None`：为历史库补列（当前：`campaign.invite_code`）；幂等，`init_db` 末尾调用
  - `SqliteRepository.get_campaign_by_invite_code(code: str) -> Campaign`（未找到 `KeyError`）
  - `POST /api/campaigns/join`（**必须注册在 `/campaigns/{campaign_id}` 之前**）：`{invite_code, player_name}` → `{campaign_id, branch_id, player_id, character_id, title}`；邀请码无效 → 404
  - `GET /api/campaigns/{id}` 返回值新增 `invite_code`

- [ ] **Step 1: 写失败测试**

`backend/tests/storage/test_migration.py`：
```python
"""轻量迁移：历史库（缺列）经 init_db 后可用新字段，且幂等。"""
import sqlite3

from sqlmodel import Session, select

from app.storage.db import init_db, make_engine
from app.storage.models import Campaign


def test_init_db_migrates_legacy_campaign_table(tmp_path):
    db = tmp_path / "legacy.db"
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
    init_db(engine)                                   # 幂等：重复调用不报错

    with Session(engine) as s:
        row = s.get(Campaign, "c1")
        assert row is not None
        assert row.invite_code == ""                  # 历史行补列为默认值
        assert s.exec(select(Campaign)).first() is not None


def test_init_db_fresh_database_has_new_columns(tmp_path):
    engine = make_engine(str(tmp_path / "fresh.db"))
    init_db(engine)
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(campaign)")}
    assert "invite_code" in cols
```

`backend/tests/api/test_join_api.py`：
```python
"""邀请码加入：新玩家获得角色、全员列出现、错误邀请码 404。"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def client(tmp_path):
    engine = make_engine(str(tmp_path / "join.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "join.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"))
    return TestClient(create_app(AppDeps(settings=settings, repo=repo))), repo


def test_create_campaign_returns_invite_code(client):
    c, _ = client
    created = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                             "title": "联机桌",
                                             "player_name": "张三"}).json()
    detail = c.get(f"/api/campaigns/{created['campaign_id']}").json()
    assert len(detail["invite_code"]) == 6
    assert detail["invite_code"] == detail["invite_code"].upper()


def test_join_by_invite_code_adds_player_and_character(client):
    c, repo = client
    created = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                             "title": "联机桌",
                                             "player_name": "张三"}).json()
    code = c.get(f"/api/campaigns/{created['campaign_id']}").json()["invite_code"]

    r = c.post("/api/campaigns/join",
               json={"invite_code": code.lower(), "player_name": "李四"})
    assert r.status_code == 200
    joined = r.json()
    assert joined["campaign_id"] == created["campaign_id"]
    assert joined["player_id"] != created["player_id"]
    assert joined["title"] == "联机桌"

    detail = c.get(f"/api/campaigns/{created['campaign_id']}").json()
    assert {p["display_name"] for p in detail["players"]} == {"张三", "李四"}
    assert joined["character_id"] in {ch["id"] for ch in detail["characters"]}


def test_join_with_unknown_code_404(client):
    c, _ = client
    r = c.post("/api/campaigns/join",
               json={"invite_code": "ZZZZZZ", "player_name": "路人"})
    assert r.status_code == 404
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/storage/test_migration.py tests/api/test_join_api.py -q`
Expected: FAIL —— `TypeError: 'invite_code' is an invalid keyword argument`（模型无字段）与 `404 != 200`（路由不存在）

- [ ] **Step 3: 实现（四处修改）**

`backend/app/storage/models.py` 的 `Campaign` 追加字段：
```python
class Campaign(SQLModel, table=True):
    id: str = Field(primary_key=True)
    module_id: str
    title: str
    active_branch_id: str
    invite_code: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=_now)
```

`backend/app/storage/db.py` 追加迁移并在 `init_db` 调用：
```python
def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """旧表缺列时补列（SQLModel.create_all 不会修改已存在的表）。"""
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    if rows and column not in {r[1] for r in rows}:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def migrate_schema(engine) -> None:
    """轻量迁移清单：每列一行，幂等可重复执行。"""
    with engine.begin() as conn:
        _ensure_column(conn, "campaign", "invite_code",
                       "invite_code VARCHAR NOT NULL DEFAULT ''")


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    migrate_schema(engine)
```

`backend/app/storage/repo.py`：
- `create_campaign` 替换为：
```python
    def create_campaign(self, module_id: str, title: str) -> Campaign:
        campaign_id = uuid.uuid4().hex[:12]
        branch = Branch(id=f"{campaign_id}@main", campaign_id=campaign_id, name="main")
        campaign = Campaign(id=campaign_id, module_id=module_id, title=title,
                            active_branch_id=branch.id,
                            invite_code=self._new_invite_code())
        with Session(self.engine) as s:
            s.add(branch)
            s.add(campaign)
            s.commit()
            s.refresh(campaign)
        return campaign
```
- 追加两个方法：
```python
    def _new_invite_code(self) -> str:
        while True:
            code = secrets.token_hex(3).upper()       # 6 位十六进制；单人服务器量级足够
            with Session(self.engine) as s:
                exists = s.exec(select(Campaign)
                                .where(Campaign.invite_code == code)).first()
            if exists is None:
                return code

    def get_campaign_by_invite_code(self, code: str) -> Campaign:
        with Session(self.engine) as s:
            row = s.exec(select(Campaign)
                         .where(Campaign.invite_code == code)).first()
        if row is None:
            raise KeyError(f"invite code not found: {code}")
        return row
```

`backend/app/api/routes.py`：
- 在 `create_campaign` 之后、`get_campaign` 之前追加（路由顺序敏感）：
```python
class JoinCampaignRequest(BaseModel):
    invite_code: str
    player_name: str = "调查员"


@router.post("/campaigns/join")
def join_campaign(req: JoinCampaignRequest, request: Request):
    from app.rules.character import make_default_character

    deps = _deps(request)
    try:
        campaign = deps.repo.get_campaign_by_invite_code(req.invite_code.strip().upper())
    except KeyError:
        raise HTTPException(status_code=404, detail="邀请码无效")
    player = deps.repo.add_player(campaign.id, req.player_name)
    char = make_default_character(player.id, req.player_name)
    deps.repo.append_character(campaign.id, campaign.active_branch_id, 0,
                               char.id, asdict(char))
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "player_id": player.id, "character_id": char.id,
            "title": campaign.title}
```
- `get_campaign` 的返回 dict 追加 `"invite_code": campaign.invite_code`（放在 `"module_title"` 之后）。

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/storage tests/api -q`
Expected: PASS（新用例 + M2/M3 既有 storage/api 用例全绿）

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/models.py backend/app/storage/db.py backend/app/storage/repo.py backend/app/api/routes.py backend/tests/storage/test_migration.py backend/tests/api/test_join_api.py
git commit -m "feat(api): campaign invite codes with join endpoint and lightweight schema migration"
```

---

### Task M4-2: 在线状态与多人窗口硬化

**Files:**
- Modify: `backend/app/api/turn_buffer.py`（`mark_skipped` / `activate` / `cancel`；`close` 兼容跳过位）
- Modify: `backend/app/api/session.py`（presence 在线集、`on_player_connect` / `on_player_disconnect`、`_open_window` 按在线集、`_state_payload` 加 players）
- Modify: `backend/app/api/ws.py`（连接注册 / 断开钩子）
- Test: `backend/tests/api/test_turn_buffer.py`（追加）、`backend/tests/api/test_multiplayer_window.py`

**Interfaces:**
- Consumes: `TurnBuffer`（M3-9）、`SessionManager`/`RoomSession`（M3-10）、`EventBus`（M3-8）、WS 端点（M3-11）
- Produces：
  - `TurnBuffer.mark_skipped(player_id) -> bool`：掉线未提交占位为跳过（`submissions[player_id] = None`）；已提交或不在本窗口返回 `False`
  - `TurnBuffer.activate(player_id) -> bool`：收集中的窗口重新纳入玩家（掉线重连回归）
  - `TurnBuffer.cancel() -> None`：作废窗口（`phase="idle"`、`epoch+=1`），不产出 payload
  - `close()`：`inputs` 排除跳过与未提交；`skipped` 含二者；`None` 提交可被后续 `submit` 覆盖（回归可行动）
  - `SessionManager.presence(campaign_id) -> set[str]`；`on_player_connect(campaign_id, player_id)`；`on_player_disconnect(campaign_id, player_id)`（**async**）
  - `turn` collecting 事件 payload 扩展：`players: [{id, display_name}]`（开窗时的在场名单）
  - `state` payload 新增 `players: [{id, display_name}]`
  - 语义：单人（唯一在线玩家）掉线 → 窗口作废且 `session.started = False`（重连时 `ensure_started` 重新开窗）；多人掉线未提交 → 标记跳过，若其余全交则立即结算（不等超时）

- [ ] **Step 1: 写失败测试（TurnBuffer 扩展）**

`backend/tests/api/test_turn_buffer.py` 追加：
```python
def test_mark_skipped_records_and_excludes_input():
    buf = TurnBuffer()
    buf.open(1, ["p1", "p2"], now=0.0)
    buf.submit("p1", entry("p1", "a"), now=1.0)
    assert buf.mark_skipped("p2") is True
    assert buf.all_submitted()
    payload = buf.close()
    assert [i["player_id"] for i in payload["inputs"]] == ["p1"]
    assert payload["skipped"] == ["p2"]


def test_skipped_player_can_resubmit_before_close():
    buf = TurnBuffer()
    buf.open(1, ["p1", "p2"], now=0.0)
    buf.mark_skipped("p2")
    assert buf.submit("p2", entry("p2", "我回来了"), now=1.0) == "accepted"
    payload = buf.close()
    assert [i["player_id"] for i in payload["inputs"]] == ["p2"]
    assert payload["skipped"] == ["p1"]


def test_mark_skipped_noop_for_submitted_or_unknown():
    buf = TurnBuffer()
    buf.open(1, ["p1"], now=0.0)
    buf.submit("p1", entry("p1", "x"), now=1.0)
    assert buf.mark_skipped("p1") is False
    assert buf.close()["skipped"] == []


def test_activate_rejoins_collecting_window():
    buf = TurnBuffer()
    buf.open(1, ["p1"], now=0.0)
    assert buf.activate("p2") is True
    assert buf.submit("p2", entry("p2", "加入"), now=1.0) == "accepted"
    assert buf.activate("p1") is False                # 已在场
    buf.close()
    assert buf.activate("p3") is False                # 非收集态拒绝


def test_cancel_discards_window_without_payload():
    buf = TurnBuffer()
    buf.open(1, ["p1"], now=0.0)
    epoch = buf.epoch
    buf.cancel()
    assert buf.phase == "idle" and buf.turn_id is None
    assert buf.epoch == epoch + 1
    assert buf.should_close(now=999.0, window_started=0.0) is False
```

- [ ] **Step 2: 写失败测试（SessionManager 多人窗口）**

`backend/tests/api/test_multiplayer_window.py`：
```python
"""多人窗口：齐交才收、掉线跳过、单人掉线取消并重开。"""
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
TURN_DECIDE = ('{"intent_summary": "行动", "checks": [], "proactive_npc_triggers": [],'
               ' "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    queues = {"qwen-plus": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


@pytest.fixture
def two_players(tmp_path):
    engine = make_engine(str(tmp_path / "mp.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "mp.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=10.0)
    campaign = repo.create_campaign("misty_hollow", "双人")
    pa = repo.add_player(campaign.id, "张三")
    pb = repo.add_player(campaign.id, "李四")
    for p in (pa, pb):
        char = make_default_character(p.id, p.display_name)
        repo.append_character(campaign.id, campaign.active_branch_id, 0,
                              char.id, asdict(char))
    return repo, settings, campaign, pa, pb


async def collect_until(session, predicate, timeout=8.0):
    sub = session.bus.subscribe("__test__")
    try:
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
    finally:
        session.bus.unsubscribe(sub)


async def test_window_waits_for_all_players(two_players):
    repo, settings, campaign, pa, pb = two_players
    factory = script_factory([OPENING_DECIDE, "开场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    assert set(session.buffer.active_players) == {pa.id, pb.id}   # 无在线信息：兜底全体

    assert await manager.handle_submit(campaign.id, pa.id, "我先看公告栏") == "accepted"
    await asyncio.sleep(0.3)                  # 超过单人防抖：多人不齐仍不收
    assert session.buffer.phase == "collecting"
    await manager.close()


async def test_disconnect_skips_and_finishes_window(two_players):
    repo, settings, campaign, pa, pb = two_players
    factory = script_factory([OPENING_DECIDE, "开场。", TURN_DECIDE, "回合叙事。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)

    assert await manager.handle_submit(campaign.id, pa.id, "我先看公告栏") == "accepted"
    await manager.on_player_disconnect(campaign.id, pb.id)     # pb 掉线：跳过
    events = await collect_until(session, lambda evts: any(
        e.type == "turn" and e.payload.get("phase") == "collecting"
        and e.payload.get("turn_id") == 2 for e in evts))
    assert any(e.type == "token" for e in events)              # 立即结算且叙事已产出
    await manager.close()


async def test_last_player_disconnect_cancels_and_reopens(two_players):
    repo, settings, campaign, pa, pb = two_players
    factory = script_factory([OPENING_DECIDE, "开场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    await manager.on_player_connect(campaign.id, pa.id)        # 先登记在线（无会话亦安全）
    session = await manager.ensure_started(campaign.id)
    assert session.buffer.active_players == [pa.id]            # 开窗仅含在线玩家
    assert session.buffer.phase == "collecting"

    await manager.on_player_disconnect(campaign.id, pa.id)     # 唯一玩家掉线
    assert session.buffer.phase == "idle"
    assert session.started is False                            # 允许重连重开

    again = await manager.ensure_started(campaign.id)          # 重连：重新开窗
    assert again is session and again.buffer.phase == "collecting"
    await manager.close()
```

- [ ] **Step 3: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_turn_buffer.py tests/api/test_multiplayer_window.py -q`
Expected: FAIL —— `AttributeError: 'TurnBuffer' object has no attribute 'mark_skipped'` / `'SessionManager' object has no attribute 'on_player_connect'`

- [ ] **Step 4: 实现 turn_buffer.py 扩展**

`backend/app/api/turn_buffer.py` 在 `submit` 之后追加三个方法，并替换 `close`：
```python
    def mark_skipped(self, player_id: str) -> bool:
        """掉线未提交：占位为跳过（后续 submit 可覆盖，允许回归行动）。"""
        if player_id not in self.active_players or player_id in self.submissions:
            return False
        self.submissions[player_id] = None
        return True

    def activate(self, player_id: str) -> bool:
        """重连回归：把玩家重新纳入收集中的窗口。"""
        if self.phase != "collecting" or player_id in self.active_players:
            return False
        self.active_players.append(player_id)
        return True

    def cancel(self) -> None:
        """作废当前窗口（不产出 payload；用于唯一玩家掉线，重连后重开）。"""
        self.phase = "idle"
        self.turn_id = None
        self.submissions = {}
        self.last_submit_ts = None
        self.epoch += 1
```

`close` 替换为（兼容跳过位）：
```python
    def close(self) -> dict:
        """收口并产出 interrupt resume payload（TurnInputs.model_dump() 结构）。"""
        inputs = [self.submissions[p] for p in self.active_players
                  if self.submissions.get(p) is not None]
        skipped = [p for p in self.active_players
                   if self.submissions.get(p) is None]
        payload = {"turn_id": self.turn_id, "inputs": inputs, "skipped": skipped}
        self.phase = "idle"
        self.turn_id = None
        self.submissions = {}
        self.last_submit_ts = None
        self.epoch += 1
        return payload
```

- [ ] **Step 5: 实现 session.py 扩展**

`backend/app/api/session.py`：

`SessionManager.__init__` 追加在线集：
```python
    def __init__(self, deps):
        self._deps = deps
        self._sessions: dict[str, RoomSession] = {}
        self._presence: dict[str, set[str]] = {}     # campaign_id -> 已连接 player_ids
        self._lock = asyncio.Lock()
```

`__init__` 之后新增查询与钩子（放在 `get` 之后）：
```python
    def presence(self, campaign_id: str) -> set[str]:
        return set(self._presence.get(campaign_id, set()))

    async def on_player_connect(self, campaign_id: str, player_id: str) -> None:
        """WS 建立后登记在线；若窗口在收集且该玩家缺席，重新纳入。"""
        self._presence.setdefault(campaign_id, set()).add(player_id)
        session = self._sessions.get(campaign_id)
        if session is not None and session.buffer.phase == "collecting":
            session.buffer.activate(player_id)

    async def on_player_disconnect(self, campaign_id: str, player_id: str) -> None:
        """WS 断开：单人作废窗口待重开；多人未提交者标跳过，若其余全交立即结算。"""
        self._presence.get(campaign_id, set()).discard(player_id)
        session = self._sessions.get(campaign_id)
        if session is None or session.ended:
            return
        buf = session.buffer
        if buf.phase != "collecting" or player_id not in buf.active_players:
            return
        if player_id in buf.submissions:
            return                                   # 已提交或已标跳过：无需处理
        if len(buf.active_players) > 1:
            buf.mark_skipped(player_id)
            if buf.all_submitted():
                payload = buf.close()
                await self._drive(session, Command(
                    resume=payload, update={"branch_id": session.branch_id}))
        else:
            if session.window_task is not None and not session.window_task.done():
                session.window_task.cancel()
            buf.cancel()
            session.started = False                  # 重连时 ensure_started 重新开窗
```

`_open_window` 替换为（开窗名单改为在线集，事件携带玩家列表）：
```python
    def _open_window(self, session: RoomSession) -> None:
        rows = session.repo.list_players(session.campaign_id)
        online = self._presence.get(session.campaign_id)
        roster = [p for p in rows if not online or p.id in online]
        players = [p.id for p in roster] or [p.id for p in rows]   # 无人在线：兜底全体
        snap = session.graph.get_state(session.config)
        turn_id = int((snap.values or {}).get("turn_id", 0))
        session.window_started = time.time()
        epoch = session.buffer.open(turn_id, players, now=session.window_started)
        session.bus.push("turn", {
            "phase": "collecting", "turn_id": turn_id,
            "players": [{"id": p.id, "display_name": p.display_name}
                        for p in rows if p.id in players]})
        if session.window_task is not None and not session.window_task.done():
            session.window_task.cancel()
        session.window_task = asyncio.create_task(self._window_timer(session, epoch))
```

`_state_payload` 的返回 dict 追加 `players`（放 `"characters"` 之后）：
```python
                "characters": session.repo.list_characters_at(campaign_id, branch_id,
                                                              10**9),
                "players": [{"id": p.id, "display_name": p.display_name}
                            for p in session.repo.list_players(campaign_id)],
```

- [ ] **Step 6: 实现 ws.py 钩子**

`backend/app/api/ws.py` 的 `ws_campaign` 内两处修改：
```python
    await websocket.accept()
    try:
        session = await deps.manager.ensure_started(campaign_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    await deps.manager.on_player_connect(campaign_id, player_id)   # 新增：登记在线
    sub = session.bus.subscribe(player_id)
    try:
        ...
    finally:
        session.bus.unsubscribe(sub)
        await deps.manager.on_player_disconnect(campaign_id, player_id)   # 新增：掉线处理
```

- [ ] **Step 7: 验证通过（含 M3 回归）**

Run: `cd backend; uv run pytest tests/api -q; uv run pytest -q`
Expected: PASS —— 新用例全绿；M3 既有 api 测试全绿（`ws.py` 钩子在直连 manager 的测试中不触发，`_open_window` 兜底行为与 M3 一致）

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/turn_buffer.py backend/app/api/session.py backend/app/api/ws.py backend/tests/api/test_turn_buffer.py backend/tests/api/test_multiplayer_window.py
git commit -m "feat(api): multiplayer windows with presence tracking and disconnect skip"
```

---

### Task M4-3: Lobby 加入流程与邀请码分享（前端）

**Files:**
- Modify: `frontend/src/types.ts`（`CampaignDetail.invite_code`；`JoinResult`）
- Modify: `frontend/src/api/rest.ts`（`joinCampaign`）
- Modify: `frontend/src/views/Lobby.tsx`（邀请码加入表单）
- Modify: `frontend/src/views/Room.tsx`（邀请码展示与点击复制）
- Modify: `frontend/src/styles.css`（`.invite-code`）
- Test: `frontend/src/views/__tests__/Lobby.test.tsx`（追加）、`frontend/src/views/__tests__/Room.test.tsx`（追加）

**Interfaces:**
- Consumes: `api.campaign`（M3-12）、`POST /api/campaigns/join`（M4-1）、`Session`（M3-14）
- Produces：
  - `JoinResult = CreateResult & { title: string }`
  - `api.joinCampaign(inviteCode, playerName) -> Promise<JoinResult>`
  - Lobby「加入战役」区块：邀请码 + 玩家名 → 成功后 `onEnter({campaignId, playerId, title})`
  - Room header：「邀请码 XXXXXX」按钮（点击写入剪贴板）；数据来自 `api.campaign(id).invite_code`
  - 存档「继续」仍取 `players[0]`（房主视角恢复入口；加入者依赖 localStorage 中的自身 session，刷新即回房间）

- [ ] **Step 1: 写失败测试**

`frontend/src/views/__tests__/Lobby.test.tsx` 的 mock 块替换为（新增 `joinCampaign`），并在 `describe("Lobby")` 内追加用例：
```tsx
vi.mock("../../api/rest", () => ({
  api: {
    modules: vi.fn(),
    campaigns: vi.fn(),
    createCampaign: vi.fn(),
    campaign: vi.fn(),
    joinCampaign: vi.fn(),
  },
}));

// …… 追加用例：
  it("joins a campaign via invite code", async () => {
    mocked.joinCampaign.mockResolvedValue({
      campaign_id: "c2", branch_id: "c2@main", player_id: "p2",
      character_id: "pc_p2", title: "老王的桌",
    });
    const onEnter = vi.fn();
    render(<Lobby onEnter={onEnter} />);
    await screen.findByText("迷雾幽谷");
    await userEvent.type(screen.getByLabelText("邀请码"), "A1B2C3");
    await userEvent.click(screen.getByText("加入"));
    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith({
        campaignId: "c2", playerId: "p2", title: "老王的桌",
      }),
    );
    expect(mocked.joinCampaign).toHaveBeenCalledWith("A1B2C3", "调查员");
  });
```

`frontend/src/views/__tests__/Room.test.tsx` 的 mock 块替换为（新增 `campaign`），并追加用例：
```tsx
vi.mock("../../api/rest", () => ({
  api: {
    module: vi.fn().mockResolvedValue({
      id: "misty_hollow", title: "迷雾幽谷",
      npcs: [{ id: "elder", name: "村长" }], endings: [],
    }),
    campaign: vi.fn().mockResolvedValue({ invite_code: "ABC123" }),
  },
}));

// …… 追加用例：
  it("shows the campaign invite code for sharing", async () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    expect(await screen.findByText("邀请码 ABC123")).toBeInTheDocument();
  });
```

- [ ] **Step 2: 验证失败**

Run: `cd frontend; npm run test`
Expected: FAIL —— `mocked.joinCampaign is not a function` / 找不到「邀请码 ABC123」

- [ ] **Step 3: 实现**

`frontend/src/types.ts`：
- `CampaignDetail` 追加 `invite_code: string;`
- 在 `CreateResult` 之后追加：
```ts
export type JoinResult = CreateResult & { title: string };
```

`frontend/src/api/rest.ts`：
- import 行加入 `JoinResult`
- `api` 追加：
```ts
  joinCampaign: (inviteCode: string, playerName: string) =>
    postJson<JoinResult>("/api/campaigns/join", {
      invite_code: inviteCode, player_name: playerName,
    }),
```

`frontend/src/views/Lobby.tsx`：
- state 追加：
```tsx
  const [inviteCode, setInviteCode] = useState("");
  const [joinName, setJoinName] = useState("调查员");
```
- `continueCampaign` 之后追加：
```tsx
  async function join() {
    const code = inviteCode.trim();
    if (!code || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.joinCampaign(code, joinName);
      onEnter({ campaignId: r.campaign_id, playerId: r.player_id, title: r.title });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
```
- 「新建战役」`</section>` 与「存档」`<section>` 之间插入：
```tsx
      <section>
        <h2>加入战役</h2>
        <label>
          邀请码
          <input value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} />
        </label>
        <label>
          玩家名
          <input value={joinName} onChange={(e) => setJoinName(e.target.value)} />
        </label>
        <button onClick={join} disabled={busy || !inviteCode.trim()}>加入</button>
      </section>
```

`frontend/src/views/Room.tsx`：
- state 追加 `const [inviteCode, setInviteCode] = useState<string | null>(null);`
- useEffect 中 `api.module(...)` 之后追加：
```tsx
    api.campaign(session.campaignId)
      .then((d) => setInviteCode(d.invite_code))
      .catch(() => {});
```
- header 中（`<span className="turn-badge">` 之前）插入：
```tsx
        {inviteCode && (
          <button className="invite-code" title="点击复制邀请码"
                  onClick={() => void navigator.clipboard?.writeText(inviteCode)}>
            邀请码 {inviteCode}
          </button>
        )}
```

`frontend/src/styles.css` 追加：
```css
.invite-code { font-size: 12px; padding: 2px 10px; border-radius: 10px;
  background: #2a3342; letter-spacing: 1px; }
```

- [ ] **Step 4: 验证通过**

Run: `cd frontend; npm run test; npm run build`
Expected: PASS（M3 用例 + 新增 2 个）；build 成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): invite-code join flow in lobby and share button in room"
```

---

### Task M4-4: 多人玩家栏与提交状态（前端）

**Files:**
- Modify: `frontend/src/types.ts`（`PlayerInfo`；`TurnPayload.players`；`StatePayload.players`）
- Modify: `frontend/src/stores/game.ts`（`players` / `submitted` 与 reducer 规则）
- Modify: `frontend/src/views/Room.tsx`（玩家栏渲染）
- Modify: `frontend/src/styles.css`（`.roster`）
- Test: `frontend/src/stores/__tests__/game.test.ts`（追加）、`frontend/src/views/__tests__/Room.test.tsx`（追加）

**Interfaces:**
- Consumes: `turn` collecting 事件的 `players`（M4-2）、`actor` 事件（M3-10）、`state.players`（M4-2）
- Produces：
  - `PlayerInfo = { id: string; display_name: string }`
  - `GameState.players: PlayerInfo[]`（来源：turn / state 事件）
  - `GameState.submitted: string[]`（本轮已提交的 player_id；`turn.collecting` 清空、`actor` 累积、去重）
  - Room 玩家栏：名字 + 已提交「✓」；多人未齐时显示「等待其他玩家…」

- [ ] **Step 1: 写失败测试**

`frontend/src/stores/__tests__/game.test.ts` 追加：
```ts
  it("tracks players roster and per-turn submissions", () => {
    let s = reduceEvent(initialState, evt("turn", {
      phase: "collecting", turn_id: 2,
      players: [{ id: "p1", display_name: "张三" },
                { id: "p2", display_name: "李四" }],
    }));
    expect(s.players.map((p) => p.id)).toEqual(["p1", "p2"]);
    s = reduceEvent(s, evt("actor", { player_id: "p1", text: "我上" }));
    s = reduceEvent(s, evt("actor", { player_id: "p1", text: "重复提交" }));
    expect(s.submitted).toEqual(["p1"]);
    s = reduceEvent(s, evt("turn", { phase: "collecting", turn_id: 3,
                                     players: [{ id: "p1", display_name: "张三" }] }));
    expect(s.submitted).toEqual([]);
    expect(s.players).toHaveLength(1);
  });
```

`frontend/src/views/__tests__/Room.test.tsx` 追加：
```tsx
  it("renders roster with submitted checkmarks and wait hint", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => {
      handlers.onStatus!("open");
      handlers.onEvent!({ seq: 1, type: "turn", visibility: "all",
                          payload: { phase: "collecting", turn_id: 1,
                                     players: [{ id: "p1", display_name: "张三" },
                                               { id: "p2", display_name: "李四" }] } });
      handlers.onEvent!({ seq: 2, type: "actor", visibility: "all",
                          payload: { player_id: "p1", text: "我上" } });
    });
    expect(screen.getByText("张三 ✓")).toBeInTheDocument();
    expect(screen.getByText("李四")).toBeInTheDocument();
    expect(screen.getByText("等待其他玩家…")).toBeInTheDocument();
  });
```

- [ ] **Step 2: 验证失败**

Run: `cd frontend; npm run test`
Expected: FAIL —— `s.players` undefined / 找不到「张三 ✓」

- [ ] **Step 3: 实现**

`frontend/src/types.ts`：
- `Segment` 之后追加 `export type PlayerInfo = { id: string; display_name: string };`
- `TurnPayload` 追加 `players?: PlayerInfo[];`
- `StatePayload` 追加 `players?: PlayerInfo[];`

`frontend/src/stores/game.ts`：
- `GameState` 追加字段：
```ts
  players: PlayerInfo[];
  submitted: string[];
```
- `initialState` 追加：`players: [], submitted: [],`
- import 行加入 `PlayerInfo`
- `reduceEvent` 的 `turn` 分支替换为：
```ts
    case "turn": {
      const { phase, turn_id, ending_reached, players } = evt.payload;
      const base: GameState = {
        ...state,
        phase,
        turnId: turn_id ?? state.turnId,
      };
      if (players) base.players = players;
      if (phase === "collecting") base.submitted = [];   // 新窗口：清空提交状态
      if (phase === "resolving") {
        base.live = [];
        base.errorMessage = null;
      }
      if (ending_reached) base.endingReached = ending_reached;
      return base;
    }
```
- `state` 分支中（`next` 构造后）追加：
```ts
      if (p.players) next.players = p.players;
```
- `actor` 分支替换为：
```ts
    case "actor":
      return {
        ...state,
        actors: [...state.actors, evt.payload].slice(-20),
        submitted: state.submitted.includes(evt.payload.player_id)
          ? state.submitted
          : [...state.submitted, evt.payload.player_id],
      };
```

`frontend/src/views/Room.tsx`：`{state.notice && ...}` 行之后插入：
```tsx
      {(state.players.length > 0 || state.phase === "collecting") && (
        <div className="roster">
          {state.players.map((p) => (
            <span key={p.id}
                  className={`roster-item${state.submitted.includes(p.id) ? " done" : ""}`}>
              {p.display_name}{state.submitted.includes(p.id) ? " ✓" : ""}
            </span>
          ))}
          {state.phase === "collecting" && state.players.length > 1
            && state.submitted.length < state.players.length && (
            <span className="roster-wait">等待其他玩家…</span>
          )}
        </div>
      )}
```

`frontend/src/styles.css` 追加：
```css
.roster { display: flex; gap: 10px; align-items: center; padding: 6px 16px;
  border-bottom: 1px solid #262c36; font-size: 13px; }
.roster-item { padding: 1px 10px; border-radius: 10px; background: #232a35; }
.roster-item.done { background: #25402b; }
.roster-wait { color: #9aa7b8; }
```

- [ ] **Step 4: 验证通过**

Run: `cd frontend; npm run test; npm run build`
Expected: PASS（M3 用例 + 新增 2 个）；build 成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): multiplayer roster with per-turn submission tracking"
```

---

### Task M4-5: 暗骰与事件可见性

**Files:**
- Modify: `backend/app/storage/models.py`（`DiceRecordRow.secret`）
- Modify: `backend/app/storage/db.py`（`migrate_schema` 追加一行）
- Modify: `backend/app/storage/repo.py`（`add_dice_record` 尾部参数 `secret`）
- Modify: `backend/app/graph/schemas.py`（`CheckRequest.secret`）
- Modify: `backend/app/graph/nodes/turn.py`（`resolve_checks` 透传 secret、事件按可见性落库）
- Modify: `backend/app/graph/nodes/gm.py`（`DECIDE_SYSTEM` 暗骰说明；`_check_lines` 标注暗骰）
- Modify: `backend/app/api/session.py`（`_push_snapshot` 暗骰按可见性推送；`resync_payload` 过滤）
- Test: `backend/tests/storage/test_migration.py`（追加）、`backend/tests/graph/test_resolve_checks.py`（追加）、`backend/tests/api/test_secret_dice.py`

**Interfaces:**
- Consumes: `CheckRequest`/`GmDecision`/`parse_decision_json`（M2-11）、`resolve_checks`（M2-13）、`add_dice_record`（M2-9）、`migrate_schema`/`_ensure_column`（M4-1）、`_push_snapshot`/`resync_payload`（M3-10）
- Produces：
  - `CheckRequest.secret: bool = False`：GM 可要求"玩家角色察觉不到的暗骰"；经 `GmDecision.model_dump()` 进入 `decision["checks"]`（缺省 false，向后兼容）
  - `DiceRecordRow.secret: bool = False`；`add_dice_record(..., seed: int, secret: bool = False)`
  - `resolve_checks`：`check_results` 元素新增 `"secret"`；暗骰的 `check` 事件 `visibility="gm"`（`WsEvent.visible_to` 只放行 `all` 与 `player:<自己>`，玩家侧实时与重放均不可见）
  - `_push_snapshot`：dice 推送 `visibility="gm" if row.secret else "all"`（无 GM 客户端时等效"不推送"；L2 记录完整保留，供 God 视角/分支回放）
  - `resync_payload`：`dice` 列表剔除暗骰
  - 不改 `_dice_payload`：玩家本就收不到暗骰事件；后续 M5 的 GM 面板如需展示再扩展字段

- [ ] **Step 1: 写失败测试（三处）**

`backend/tests/storage/test_migration.py`：import 行改为

```python
from app.storage.models import Campaign, DiceRecordRow
```

文件末尾追加：

```python
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
    init_db(engine)                                    # 幂等

    with Session(engine) as s:
        row = s.get(DiceRecordRow, 1)
        assert row is not None and row.secret is False  # 历史行补列为默认 false
```

`backend/tests/graph/test_resolve_checks.py` 追加：

```python
def test_secret_check_marks_record_and_event_visibility(node, repo, campaign):
    upd = node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular", "secret": True}]}))
    assert upd["check_results"][0]["secret"] is True
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 1 and rows[0].secret is True
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])
    assert events[0].visibility == "gm"


def test_regular_check_defaults_to_visible(node, repo, campaign):
    node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular"}]}))
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert rows[0].secret is False
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])
    assert events[0].visibility == "all"
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
    queues = {"qwen-plus": list(items)}

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
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=10.0)
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

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/storage/test_migration.py tests/graph/test_resolve_checks.py tests/api/test_secret_dice.py -q`
Expected: FAIL —— `TypeError: add_dice_record() got an unexpected keyword argument 'secret'`、`AttributeError: 'DiceRecordRow' object has no attribute 'secret'`、以及暗骰仍被推送给玩家的断言失败

- [ ] **Step 3: 实现存储层**

`backend/app/storage/models.py` 的 `DiceRecordRow` 在 `seed` 之后插入一行：

```python
    seed: int
    secret: bool = False          # 暗骰：L2 保留，但不对玩家可见
    created_at: datetime = Field(default_factory=_now)
```

`backend/app/storage/db.py` 的 `migrate_schema` 追加一行：

```python
def migrate_schema(engine) -> None:
    """轻量迁移清单：每列一行，幂等可重复执行。"""
    with engine.begin() as conn:
        _ensure_column(conn, "campaign", "invite_code",
                       "invite_code VARCHAR NOT NULL DEFAULT ''")
        _ensure_column(conn, "dicerecordrow", "secret",
                       "secret BOOLEAN NOT NULL DEFAULT 0")
```

`backend/app/storage/repo.py` 的 `add_dice_record` 替换为：

```python
    def add_dice_record(self, campaign_id: str, branch_id: str, turn_id: int, actor: str,
                        skill: str, skill_value: int, difficulty: str, roll: int,
                        level: str, seed: int, secret: bool = False) -> None:
        with Session(self.engine) as s:
            s.add(DiceRecordRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                                actor=actor, skill=skill, skill_value=skill_value,
                                difficulty=difficulty, roll=roll, level=level, seed=seed,
                                secret=secret))
            s.commit()
```

- [ ] **Step 4: 实现图与提示词**

`backend/app/graph/schemas.py` 的 `CheckRequest` 追加字段：

```python
class CheckRequest(BaseModel):
    actor: str
    skill: str
    difficulty: CheckDifficulty = CheckDifficulty.REGULAR
    secret: bool = False          # true=暗骰：玩家角色无从察觉，叙事不得直接暴露
```

`backend/app/graph/nodes/turn.py` 的 `resolve_checks` 替换为：

```python
def build_resolve_checks_node(repo):
    def resolve_checks(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        checks = (state.get("decision") or {}).get("checks", [])
        results = []
        for chk in checks:
            actor, skill = chk["actor"], chk["skill"]
            secret = bool(chk.get("secret"))
            skill_value = _skill_value(state, actor, skill)
            seed = new_seed()
            r = roll_check(actor, skill, skill_value,
                           CheckDifficulty(chk.get("difficulty", "regular")), seed)
            repo.add_dice_record(campaign_id, branch_id, turn_id, r.actor, r.skill,
                                 r.skill_value, str(r.difficulty), r.roll, str(r.level),
                                 r.seed, secret=secret)
            verdict = "成功" if r.success else "失败"
            repo.add_event(campaign_id, branch_id, turn_id, type="check",
                           payload={"text": f"{actor} 的「{skill}」检定：{r.roll}/{r.skill_value} "
                                            f"→ {r.level}（{verdict}）",
                                    "roll": r.roll, "level": str(r.level),
                                    "success": r.success, "secret": secret},
                           visibility="gm" if secret else "all")
            results.append({"actor": r.actor, "skill": r.skill, "roll": r.roll,
                            "skill_value": r.skill_value, "level": str(r.level),
                            "success": r.success, "seed": r.seed, "secret": secret})
        return {"check_results": results}

    return resolve_checks
```

`backend/app/graph/nodes/gm.py` 两处替换。

`DECIDE_SYSTEM` 替换为（含 M3-4 的 `clues_revealed/ending_reached` 两行，位于 `memory_queries` 之前，勿丢）：

```python
DECIDE_SYSTEM = (
    "你是跑团主持人（COC 风格）。基于玩家行动与当前场景做结构化裁决，只输出一个 JSON 对象，字段：\n"
    'intent_summary(str)、checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme),'
    '"secret"(bool，可选，默认 false)})、'
    'proactive_npc_triggers(数组，元素 {"npc_id","trigger"})、'
    'scene_transition(null 或 {"to_scene","reason"})、'
    'clues_revealed(数组，元素为线索 id，仅当本回合玩家明确获得线索时填写)、'
    'ending_reached(null 或模块给定结局 id，仅当叙事故意收束到结局时填写)、'
    'memory_queries(字符串数组)。\n'
    "规则：只为玩家的主动行动要求检定，每回合最多 2 个检定；NPC 只能用场景内列出的；"
    "开场回合可以引入场面但不要要求检定；secret=true 表示玩家角色无从察觉的暗骰（如暗中进行的观察或聆听），"
    "其检定与结果不得在叙事中直接暴露。"
)
```

`_check_lines` 替换为：

```python
def _check_lines(state: GameState) -> str:
    lines = []
    for c in state.get("check_results", []):
        verdict = "成功" if c.get("success") else "失败"
        note = ("（暗骰：不得在叙事中直接暴露该检定与结果，只可化为隐约的线索或不安感）"
                if c.get("secret") else "")
        lines.append(f"- {c['actor']} 的「{c['skill']}」：{c['roll']}/{c['skill_value']} "
                     f"→ {c['level']}（{verdict}）{note}")
    return "\n".join(lines) or "（本回合无检定）"
```

- [ ] **Step 5: 实现会话推送过滤**

`backend/app/api/session.py` 两处替换：

`_push_snapshot` 的 dice 推送：

```python
        for row in session.repo.list_dice_records(session.campaign_id,
                                                  session.branch_id,
                                                  turn_id=finished_turn):
            session.bus.push("dice", _dice_payload(row),
                             visibility="gm" if row.secret else "all")
```

`resync_payload` 的 records 读取：

```python
        rows = [r for r in session.repo.list_dice_records(session.campaign_id,
                                                          session.branch_id)
                if not r.secret]
```

- [ ] **Step 6: 验证通过（含 M2/M3 回归）**

Run: `cd backend; uv run pytest tests/storage tests/graph tests/api -q`
Expected: PASS —— 新用例全绿；`resolve_checks`/`gm_narrate` 既有用例不受影响（无 secret 时行为与提示词不变）

- [ ] **Step 7: Commit**

```bash
git add backend/app/storage/models.py backend/app/storage/db.py backend/app/storage/repo.py backend/app/graph/schemas.py backend/app/graph/nodes/turn.py backend/app/graph/nodes/gm.py backend/app/api/session.py backend/tests/storage/test_migration.py backend/tests/graph/test_resolve_checks.py backend/tests/api/test_secret_dice.py
git commit -m "feat(api): secret dice with GM-only visibility, persisted in L2"
```

---

### Task M4-6: 容器化与腾讯云部署

**Files:**
- Modify: `backend/Dockerfile`（替换 M2 占位 → uv 生产镜像）
- Create: `backend/.dockerignore`
- Create: `frontend/Dockerfile`、`frontend/nginx.conf`、`frontend/.dockerignore`
- Modify: `docker-compose.yml`（两服务生产编排）
- Create: `.env.example`
- Modify: `.gitignore`（追加 `data/`、`dist/`）
- Create: `docs/deploy-tencent.md`
- Modify: `README.md`（追加 Docker 部署节）

**Interfaces:**
- Consumes: `app.serve:app`（M3-17）、`GET /healthz`（M3-5）、WS `/ws/campaign/{id}`（M3-11）、前端 `npm run build`（M3-12）、`backend/uv.lock`（M2-1 已提交）、`frontend/package-lock.json`（M3-12 已提交）
- Produces：
  - backend 镜像：`uv sync --frozen --no-dev`（venv 在 `/srv/.venv`）；镜像级环境 `ENSEMBLE_SQLITE_PATH=/data/ensemble.db`、`ENSEMBLE_MODULES_DIR=/modules`、`ENSEMBLE_PRICING_PATH=/config/pricing.yaml`
  - frontend 镜像：Node 构建 `dist` → nginx 托管；`/api/` 与 `/ws/`（Upgrade 头 + `proxy_read_timeout 3600s`）反代 `backend:8000`；SPA `try_files $uri /index.html`
  - compose：对外仅 `frontend` `80:80`；持久卷 `./data:/data`（SQLite 库）；只读挂载 `./modules:/modules:ro`、`./config:/config:ro`；两个 API key 由 compose 变量插值（读同目录 `.env`）
  - `.env.example`、`docs/deploy-tencent.md`（轻量服务器全流程）

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

`.gitignore` 追加两行：

```
data/
dist/
```

- [ ] **Step 4: 写部署文档**

`docs/deploy-tencent.md`：

````markdown
# 腾讯云轻量应用服务器部署（Ensemble）

> 目标：把"本机 docker-compose 可玩"升级为"公网 IP 可玩"。全流程约 30 分钟。

## 1. 购买与初始化

- 腾讯云「轻量应用服务器」：Ubuntu 22.04，2 核 2G 起（两人玩足够）；
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

## 5. 验收（M4 出口标准）

- 浏览器打开 `http://<公网IP>/` → 新建战役 → 出现回合窗口；
- 第二台设备（手机/电脑）打开同地址 → 输入房主的 6 位邀请码加入；
- 两人各提交一次行动 → 双方同时看到结算叙事；断线重连后能继续；
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

```markdown
## Docker 一键启动 / 服务器部署

```bash
cp .env.example .env      # 填入 DASHSCOPE_API_KEY / DEEPSEEK_API_KEY
docker compose up -d --build
# 浏览器打开 http://localhost/
```

数据存放在 `./data/ensemble.db`；腾讯云部署全流程见 `docs/deploy-tencent.md`。
```

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
git commit -m "feat(deploy): production docker images, nginx reverse proxy and compose stack"
```

---

### Task M4-7: 联机双人 E2E（M4 出口验收）

**Files:**
- Create: `backend/tests/api/test_multiplayer_e2e.py`
- Modify: `README.md`（追加「双人联机手测」清单）

**Interfaces:**
- Consumes: `create_app`/`AppDeps`（M3-11）、邀请码加入（M4-1）、presence 与掉线跳过（M4-2）、`turn.players` payload（M4-2）、`TurnBuffer.should_close` 多人语义（M3-9）
- Produces：
  - E2E 验收测试：双 WS（TestClient 嵌套）走通「邀请码加入 → 全员开窗不齐不收 → 掉线跳过立即结算 → 重连回放继续 → 联机拉结局」，作为 M4 出口标准"两个浏览器联机玩一回合"的自动化替身
  - README「双人联机手测」清单（浏览器层验收）

- [ ] **Step 1: 写 E2E 测试**

`backend/tests/api/test_multiplayer_e2e.py`：

```python
"""联机双人 E2E：邀请码加入 → 全员窗口 → 掉线跳过 → 重连继续（M4 出口标准）。"""
import json
import time
from dataclasses import asdict
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]


def script_factory(items):
    """按模型名消耗脚本；每次 chat/chat_stream 新建 FakeLLM。"""
    queues = {"qwen-plus": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


def make_script(char_id: str) -> list[str]:
    """八条 qwen-plus 脚本：开场 + 三轮（回合 2 为掉线跳过轮；回合 3 触发结局）。"""

    def decide(**extra):
        base = {"intent_summary": "行动", "checks": [], "proactive_npc_triggers": [],
                "scene_transition": None, "memory_queries": []}
        base.update(extra)
        return json.dumps(base)

    return [
        decide(intent_summary="开场"), "暮色压着雾霭镇，无面的神像俯视着广场。",
        decide(checks=[{"actor": char_id, "skill": "侦查", "difficulty": "regular"}]),
        "公告栏上的寻人启事被风吹得沙沙作响。",
        decide(), "井底传来空洞的回声，仿佛有什么在应答。",
        decide(intent_summary="终结旧约", ending_reached="ending_break"),
        "石台在轰鸣中崩塌，缠绕镇子的低语骤然停止。",
    ]


def build_env(tmp_path):
    engine = make_engine(str(tmp_path / "mp_e2e.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "mp_e2e.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=10.0)
    campaign = repo.create_campaign("misty_hollow", "联机端到端")
    host = repo.add_player(campaign.id, "张三")
    char = make_default_character(host.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    deps = AppDeps(settings=settings, repo=repo,
                   model_factory=script_factory(make_script(char.id)))
    return create_app(deps), repo, campaign, host


def pump_until(ws, collected, predicate, limit=400):
    """持续接收事件直到 predicate(collected) 为真；全程断言 seq 严格单调。"""
    last_seq = collected[-1]["seq"] if collected else 0
    for _ in range(limit):
        evt = json.loads(ws.receive_text())
        assert evt["seq"] > last_seq, f"seq must strictly increase: {evt['seq']}"
        last_seq = evt["seq"]
        collected.append(evt)
        if predicate(collected):
            return
    raise AssertionError(f"timeout; got {[e['type'] for e in collected]}")


def _collecting(turn_id):
    return lambda evts: any(e["type"] == "turn"
                            and e["payload"].get("phase") == "collecting"
                            and e["payload"].get("turn_id") == turn_id for e in evts)


def _players_of(evts, turn_id):
    for e in evts:
        if (e["type"] == "turn" and e["payload"].get("phase") == "collecting"
                and e["payload"].get("turn_id") == turn_id):
            return [p["id"] for p in e["payload"]["players"]]
    raise AssertionError(f"no collecting event for turn {turn_id}")


def wait_until(predicate, timeout=5.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def test_two_browsers_round_trip_with_skip_and_reconnect(tmp_path):
    app, repo, campaign, host = build_env(tmp_path)
    manager = app.state.deps.manager
    a_events: list[dict] = []

    with TestClient(app) as client:
        invite = client.get(f"/api/campaigns/{campaign.id}").json()["invite_code"]
        joined = client.post("/api/campaigns/join",
                             json={"invite_code": invite, "player_name": "李四"}).json()
        guest = joined["player_id"]

        url_a = f"/ws/campaign/{campaign.id}?player_id={host.id}"
        url_b = f"/ws/campaign/{campaign.id}?player_id={guest}"
        with client.websocket_connect(url_a) as ws_a:
            pump_until(ws_a, a_events, _collecting(1))          # 开场窗口：等两个人
            assert set(_players_of(a_events, 1)) == {host.id, guest}

            ws_a.send_text(json.dumps({"type": "input", "text": "我先看公告栏"}))
            time.sleep(0.3)                                     # 多人不齐：不结算
            assert manager.get(campaign.id).buffer.phase == "collecting"

            with client.websocket_connect(url_b) as ws_b:
                ws_b.send_text(json.dumps({"type": "input", "text": "我检查井边"}))
                pump_until(ws_a, a_events, _collecting(2))      # 齐交才收
                assert set(_players_of(a_events, 2)) == {host.id, guest}
                assert any(e["type"] == "dice" for e in a_events)   # 两人共享同一检定

            wait_until(lambda: guest not in manager.presence(campaign.id))

            ws_a.send_text(json.dumps({"type": "input", "text": "我向井底喊话"}))
            pump_until(ws_a, a_events, _collecting(3))          # B 掉线：跳过并立即结算
            assert _players_of(a_events, 3) == [host.id]        # 新窗口只剩在线者

            with client.websocket_connect(url_b + "&resume_from=0") as ws_b2:
                b_events: list[dict] = []
                pump_until(ws_b2, b_events, _collecting(3))     # 重连：回放补齐历史
                assert any(e["type"] == "token" for e in b_events)
                wait_until(lambda: guest
                           in manager.get(campaign.id).buffer.active_players)

                ws_a.send_text(json.dumps({"type": "input", "text": "我推倒石台"}))
                ws_b2.send_text(json.dumps({"type": "input", "text": "我掩护你"}))
                pump_until(ws_a, a_events, lambda evts: any(    # 联机拉到结局
                    e["type"] == "turn" and e["payload"].get("phase") == "ended"
                    for e in evts))
                ended = [e for e in a_events if e["type"] == "turn"
                         and e["payload"].get("phase") == "ended"]
                assert ended[-1]["payload"]["ending_reached"] == "ending_break"

        detail = client.get(f"/api/campaigns/{campaign.id}").json()
        assert {p["display_name"] for p in detail["players"]} == {"张三", "李四"}
```

- [ ] **Step 2: 运行 E2E 与全量回归**

Run: `cd backend; uv run pytest tests/api/test_multiplayer_e2e.py -q`
Expected: PASS —— M4-1~M4-6 已分别验证；此处失败必是装配缝隙，当场修复后重跑（不允许绕过）

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 后端全量测试全绿

Run: `cd frontend; npm run test`
Expected: PASS —— 前端全量（含 M4-3/M4-4 新增用例）

- [ ] **Step 3: README 追加双人联机手测**

在 README「浏览器验收清单（手测）」之后追加：

```markdown
## 双人联机手测

- [ ] 设备① 新建战役，房间头部显示 6 位邀请码（点击可复制）
- [ ] 设备② 打开同地址 → 大厅「加入战役」输入邀请码与名字 → 进入同一房间，玩家栏出现两人
- [ ] 提交行动后玩家栏显示「✓」，等待其他玩家提交后才结算（「等待其他玩家…」）
- [ ] 关掉设备② 的标签页 / 断网：设备① 提交后立即结算，不卡死
- [ ] 设备② 重开页面进入房间 → 历史完整回放，可继续行动
- [ ] GM 判定的暗骰不会出现在玩家骰子日志中
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/api/test_multiplayer_e2e.py README.md
git commit -m "test(e2e): two-browser round trip with invite join, disconnect skip and reconnect"
```

---

## 计划自审（M4）

**规格覆盖表**（对照 `docs/superpowers/specs/2026-09-24-ensemble-design.md`）：

| 规格章节 | 覆盖任务 |
| --- | --- |
| §5.3 私密信息（暗骰与 visibility） | M4-5（`secret` 骰子、check 事件 `visibility="gm"`、推送与重连过滤） |
| §6.4 前端信息架构（邀请码分享、玩家在线） | M4-3（邀请码展示/加入）、M4-4（玩家栏与提交状态） |
| §13-M4 全员回合窗口与超时 | M4-2（presence 驱动开窗、掉线跳过即结算、唯一玩家掉线重开） |
| §13-M4 邀请码 | M4-1（生成/加入 API + 轻量迁移）、M4-3（前端加入流程） |
| §13-M4 腾讯云部署 | M4-6（uv/nginx 生产镜像、compose、`.env.example`、部署文档） |
| §13-M4 出口：两个浏览器联机玩一回合 | M4-7（双 WS E2E：邀请码加入→齐交才收→掉线跳过→重连继续→结局）+ README 手测清单 |

**已知边界（有意为之）**：
- 邀请码为 6 位 hex（约 1600 万组合），单机自用规模足够；无速率限制与过期时间，若公网长期开放建议 M5 补加入限流。
- presence 以 WS 连接为中心：同一玩家多标签页按"存在连接即在线"处理，不区分设备。
- 暗骰的 GM 视角暂无独立客户端：`visibility="gm"` 事件保留在 EventBus 缓冲与 L2，M5 的 GM 面板可直接复用。
- 部署不含 HTTPS 终结自动化：按需在腾讯云侧挂证书（`docs/deploy-tencent.md` §7）。

**类型一致性抽查**：
- `turn.players` 形状 `[{id, display_name}]` 三处一致：M4-2 `_open_window` 产出、M4-4 前端 `PlayerInfo`/`TurnPayload`、M4-7 断言。
- `invite_code` 四处一致：M4-1 存储字段与 join API、M4-3 前端 `CampaignDetail` 与 Lobby 表单。
- `secret` 五处一致：M4-5 的 `CheckRequest.secret` → `decision["checks"]` → `resolve_checks` 落库/事件 → `DiceRecordRow.secret` → session 推送过滤；前端无 secret 字段（对玩家不可见）。
- `JoinResult = CreateResult & { title }`：M4-1 返回体、M4-3 前端类型、Lobby 映射 `campaign_id→campaignId` 对齐。

---

## 执行交接（M4）

本计划 7 个任务按依赖序排列：M4-1（数据与加入）→ M4-2（窗口硬化）→ M4-3/M4-4（前端）→ M4-5（暗骰）→ M4-6（部署）→ M4-7（联机 E2E 验收），每个任务自包含、可独立测试与提交。

执行方式二选一：
1. **Subagent 逐任务执行（推荐）**：每个任务派发新的子代理实现，任务间人工审查把关；
2. **本会话内批量执行**：按 executing-plans 流水线推进，在检查点停顿复核。

交接前确认：
- M1/M2/M3 全部完成且测试全绿（`cd backend; uv run pytest -q`；`cd frontend; npm run test`）；
- 本机安装 Docker Desktop（M4-6 的镜像构建验证需要；无 Docker 时按该任务 Step 6 备注处理）；
- 云端准备：腾讯云轻量应用服务器 + 两个 API key（M4-6 交付部署文档，验收在 M4-7 之后的真实联机手测完成）。

---
