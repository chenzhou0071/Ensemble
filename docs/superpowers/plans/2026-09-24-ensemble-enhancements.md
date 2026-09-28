# Ensemble M5 增强实施计划（Graphiti / 可观测性 / 奖惩骰 / 战斗子图）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按设计规格 §13 的"M5 增强（可选）"清单交付四项能力，每项自包含、可独立验收：① Graphiti 时序图谱记忆适配器（L3 二阶段，可插拔 + 优雅回退）；② 可观测性（LangSmith 原生追踪 + 本地 JSONL 降级 + `/metrics` 四指标）；③ 奖惩骰（COC 7e 风格，规则→GM→存储→前端全链路）；④ 轻量战斗结算子图（攻击对抗 → 伤害 → HP/败亡，接入主图）。

**Architecture:** 所有新增能力遵循"协议注入 + 优雅回退"：Graphiti 实现既有 `MemoryService` 协议、不改任何上层调用；可观测性以 `Tracer`/`Counters` 旁挂（LLMClient 调用点 + 回合驱动点），默认零开销、零写盘；奖惩骰扩展 `rules/check.py` 纯函数并沿既有 `checks` 管道透传（CheckRequest → resolve_checks → DiceRecordRow → dice 事件 → 前端）；战斗为独立 `rules/combat.py` 纯函数 + `combat_resolve` 节点（`validate` 后按 `target` 字段分流），HP 随 state 装载/写回 L2 快照，事件与可见性机制全部复用 M2-M4 既有设施。

**Tech Stack:** 沿用 M2-M4：Python 3.12 / uv / LangGraph / FastAPI / SQLModel / pytest（零网络）+ React / Vite / TS / vitest。新增**可选**依赖（缺失时全部降级路径可用）：`graphiti-core`（extra: `graph`）、`langsmith`（extra: `observability`）。

## Global Constraints

- 全部测试零网络零外部服务；`graphiti-core` / `langsmith` 一律通过 `[project.optional-dependencies]` 安装，代码中**延迟导入**，未安装时走回退路径且既有测试全绿。
- 新增后端模块一律依赖注入（tracer / graph_client），测试可替换；产生副作用的写盘与计数在测试中显式开关（`Settings.traces_dir=""` → tracer 关闭）或 `reset_counters()` 隔离。
- 数值全部由纯函数（`rules/*`）计算，**LLM 永远不提供数值**；本计划所有提示词只允许 LLM 输出"意图与参数"，不允许输出骰值/伤害值/HP。
- 奖惩骰上限 ±2（COC 7e 惯例）；净额 `net = bonus - penalty`；`net == 0` 时与既有 `roll_d100` 行为完全一致（既有测试的 monkeypatch 语义不变）。
- 战斗边界（YAGNI，规格 §14）：只做"攻击检定 → 防御掷骰 → 伤害 → HP/败亡"的单次结算；不做先攻排序、战斗轮循环、NPC 反击、武器/护甲表、战棋地图。攻击目标仅限**当前场景**内的 NPC，攻击者仅限玩家角色。
- `/metrics` 为 JSON 端点（不引入 Prometheus）；进程内计数器重启清零并在响应中声明；traces JSONL 字段固定为 `run_id / parent_run_id / name / run_type / inputs / outputs / start_time / end_time / error`。
- 兼容性：既有 `WsEvent` / `TurnBuffer` / `secret` 机制不改语义；前端新增字段一律可选（`bonus?: number`），不破坏 M3/M4 已定测试数据。
- 前置依赖：M2（Task 1-24）、M3（T1-T17）、M4（M4-1~M4-7）全部完成且 `uv run pytest` 全绿；本计划按任务号顺序执行（多个任务触碰同一文件：`session.py` / `llm/client.py` / `turn.py` / `gm.py`，线性执行避免交叉合并）。

---

## 文件结构（新增/修改一览）

```
docs/superpowers/plans/2026-09-24-ensemble-enhancements.md   # 本计划
backend/
├── pyproject.toml                 # M5-1（extra: graph）、M5-2（extra: observability）
├── app/
│   ├── config.py                  # M5-1（memory_backend/neo4j_*）、M5-2（traces_dir）
│   ├── cli.py                     # M5-1（build_memory）、M5-2（tracer 注入）
│   ├── obs/
│   │   ├── __init__.py            # M5-2
│   │   ├── tracer.py              # M5-2（JSONL run trace，字段对齐 run 格式）
│   │   └── counters.py            # M5-3（四指标进程内计数器）
│   ├── llm/client.py              # M5-2（tracer 包裹 chat/chat_stream）、M5-3（LLM 成败计数）
│   ├── memory/graphiti.py         # M5-1（GraphitiMemory + 异步桥 + build_memory）
│   ├── rules/
│   │   ├── dice.py                # M5-4（roll_d100_with_bonus）
│   │   ├── check.py               # M5-4（roll_check 支持 bonus/penalty）
│   │   └── combat.py              # M5-6（resolve_attack / roll_damage）
│   ├── content/schema.py          # M5-6（NpcDef.combat）
│   ├── storage/
│   │   ├── models.py              # M5-4（DiceRecordRow.bonus/penalty）
│   │   ├── db.py                  # M5-4（migrate_schema 追加两列）
│   │   ├── repo.py                # M5-4（add_dice_record）、M5-3（usage_totals）、M5-5（usage_rows）
│   ├── graph/
│   │   ├── state.py               # M5-7（npc_hp / combat_log）
│   │   ├── schemas.py             # M5-4（CheckRequest.bonus/penalty）、M5-7（CheckRequest.target）
│   │   ├── main.py                # M5-7（combat_resolve 节点与 validate 分流）
│   │   └── nodes/
│   │       ├── turn.py            # M5-4（提取 _resolve_plain_check）、M5-7（combat 节点/intake/post_turn）、M5-3（paused 计数）
│   │       ├── gm.py              # M5-4（DECIDE_SYSTEM/_check_lines）、M5-7（target 校验/战斗行）、M5-3（降级计数）
│   │       ├── memory.py          # M5-3（降级计数）
│   │       └── npc.py             # M5-3（降级计数）
│   ├── api/
│   │   ├── app.py                 # M5-3（GET /metrics）
│   │   ├── routes.py              # M5-5（GET /api/campaigns/{id}/usage）
│   │   └── session.py             # M5-1（build_memory）、M5-2（turn trace）、M5-3（record_turn）、M5-4（_dice_payload）
├── modules/misty_hollow.yaml      # M5-6（whisperer.combat）
└── tests/
    ├── memory/test_graphiti.py    # M5-1（新建）
    ├── obs/test_tracer.py         # M5-2（新建）
    ├── obs/test_counters.py       # M5-3（新建）
    ├── api/test_metrics.py        # M5-3（新建）
    ├── graph/test_fallbacks_count.py  # M5-3（新建）
    ├── api/test_usage_api.py      # M5-5（新建）
    ├── rules/test_combat.py       # M5-6（新建）
    ├── graph/test_combat.py       # M5-7（新建）
    └── （追加）rules/test_dice.py、rules/test_check.py、storage/test_migration.py、
         graph/test_resolve_checks.py、graph/test_endings.py（validate 新签名兼容）、
         tests/content/test_schema.py
frontend/
├── src/types.ts                   # M5-4（DicePayload）、M5-5（UsageSummary）
├── src/api/rest.ts                # M5-5（api.usage）
├── src/views/Room.tsx             # M5-5（挂载 CostPanel）
├── src/components/
│   ├── DiceOverlay.tsx            # M5-4（奖励/惩罚骰标注）
│   ├── DiceLogPanel.tsx           # M5-4（记录标注）
│   ├── CostPanel.tsx              # M5-5（新建）
│   └── __tests__/                 # M5-4（DiceOverlay）、M5-5（CostPanel）、Room.test.tsx（mock 更新）
README.md / .env.example           # M5-2（记忆后端 / traces / LangSmith 三开关说明）
```

---

### Task M5-1: Graphiti 时序图谱记忆适配器（可插拔 L3）

**Files:**
- Create: `backend/app/memory/graphiti.py`
- Create: `backend/tests/memory/test_graphiti.py`
- Modify: `backend/app/config.py`（Settings + 4 字段；load_settings 读 env）
- Modify: `backend/pyproject.toml`（`[project.optional-dependencies] graph`）
- Modify: `backend/app/cli.py`（`assemble` 改用 `build_memory`）
- Modify: `backend/app/api/session.py`（`_assemble` 改用 `build_memory`）

**Interfaces:**
- Consumes: `MemoryService` / `MemoryEvent` / `MemoryHit`（M2-13）、`JournalMemory`（M2-13）、`Settings` / `load_settings`（M2-10，M3-5 扩展）、`SqliteRepository.latest_summary`（M2-9）
- Produces：
  - `GraphClient(Protocol)`（同步接口，真实实现内部桥接 graphiti-core 异步 API）：
    `add_episode(name: str, body: str, group_id: str, reference_time: str) -> None`；
    `search_facts(query: str, group_id: str, limit: int) -> list[str]`；
    `close() -> None`
  - `GraphitiMemory(repo, graph_client: GraphClient | None = None, summarizer=None)`：实现 `MemoryService` 协议；组合 `JournalMemory`——**事件始终落 L2 事件表（权威）**，图谱仅增强：写入失败只记日志、检索失败回退关键词
  - `make_graphiti_client(settings) -> GraphClient`：延迟导入 `graphiti_core`（未安装 / 未配密码时抛异常）；`_GraphitiAdapter` 用后台线程事件循环桥接异步 API
  - `build_memory(settings, repo, summarizer=None) -> MemoryService`：`memory_backend == "graphiti"` 时尝试 graphiti（任何异常 → warning + 回退 `JournalMemory`），否则直接 `JournalMemory`；`summarizer`（Task 18b 的 `LLMSummarizer`）透传给底层 JournalMemory（默认 None 时保持模板兜底，兼容既有测试）
  - `Settings` 新字段：`memory_backend: str = "journal"`、`neo4j_uri: str = "bolt://localhost:7687"`、`neo4j_user: str = "neo4j"`、`neo4j_password: str | None = None`；env：`ENSEMBLE_MEMORY_BACKEND` / `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`

- [ ] **Step 1: 写失败测试**

`backend/tests/memory/test_graphiti.py`：
```python
"""GraphitiMemory：图谱增强 + 优雅回退；全部用假 GraphClient，零网络。"""
import pytest

from app.config import Settings
from app.memory.base import MemoryEvent
from app.memory.graphiti import GraphitiMemory, build_memory
from app.memory.journal import JournalMemory


class FakeGraphClient:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.episodes: list[dict] = []
        self.queries: list[tuple] = []
        self.closed = False

    def add_episode(self, name, body, group_id, reference_time):
        if self.fail:
            raise RuntimeError("graph down")
        self.episodes.append({"name": name, "body": body, "group_id": group_id})

    def search_facts(self, query, group_id, limit):
        if self.fail:
            raise RuntimeError("graph down")
        self.queries.append((query, group_id, limit))
        return ["磨坊学徒三个月前失踪", "神像的五官被磨平"]

    def close(self):
        self.closed = True


def test_write_event_mirrors_to_graph(repo, campaign):
    graph = FakeGraphClient()
    mem = GraphitiMemory(repo, graph_client=graph)
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=2))
    events = [e for e in repo.list_events(campaign.id, campaign.active_branch_id)
              if e.type == "memory:clue"]
    assert len(events) == 1                                  # L2 权威落地
    assert len(graph.episodes) == 1                          # 图谱镜像
    ep = graph.episodes[0]
    assert ep["body"] == "磨坊夜里传出哭声"
    assert ep["group_id"] == f"{campaign.id}:{campaign.active_branch_id}"
    assert ep["name"] == "clue:t2"


def test_write_event_survives_graph_failure(repo, campaign):
    mem = GraphitiMemory(repo, graph_client=FakeGraphClient(fail=True))
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="clue", text="仍然要落库", turn_id=1))
    assert any(e.type == "memory:clue"
               for e in repo.list_events(campaign.id, campaign.active_branch_id))


def test_search_prefers_graph_facts(repo, campaign):
    graph = FakeGraphClient()
    mem = GraphitiMemory(repo, graph_client=graph)
    hits = mem.search(campaign.id, campaign.active_branch_id, "磨坊", limit=2)
    assert [h.text for h in hits] == ["磨坊学徒三个月前失踪", "神像的五官被磨平"]
    assert graph.queries == [("磨坊", f"{campaign.id}:{campaign.active_branch_id}", 2)]


def test_search_falls_back_to_journal(repo, campaign):
    journal = JournalMemory(repo)
    journal.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=1))
    mem = GraphitiMemory(repo, graph_client=FakeGraphClient(fail=True))
    hits = mem.search(campaign.id, campaign.active_branch_id, "磨坊")
    assert hits and "哭声" in hits[0].text                   # 图不可用 → 关键词回退


def test_get_context_delegates_to_journal(repo, campaign):
    repo.append_summary(campaign.id, campaign.active_branch_id, 3, "已有摘要")
    mem = GraphitiMemory(repo, graph_client=FakeGraphClient())
    assert "已有摘要" in mem.get_context(campaign.id, campaign.active_branch_id)


def test_update_summaries_mirrors_new_summary(repo, campaign):
    graph = FakeGraphClient()
    mem = GraphitiMemory(repo, graph_client=graph)
    for i in range(12):
        mem.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="note", text=f"事件{i}", turn_id=i // 3))
    graph.episodes.clear()
    mem.update_summaries(campaign.id, campaign.active_branch_id, turn_id=3)
    summary = repo.latest_summary(campaign.id, campaign.active_branch_id)
    assert summary is not None
    assert len(graph.episodes) == 1
    assert graph.episodes[0]["name"] == "summary:t3"
    assert graph.episodes[0]["body"] == summary.content


def test_build_memory_defaults_to_journal(repo):
    mem = build_memory(Settings(), repo)
    assert isinstance(mem, JournalMemory)


def test_build_memory_falls_back_when_graphiti_missing(repo, monkeypatch):
    def boom(settings):
        raise ImportError("graphiti-core not installed")

    monkeypatch.setattr("app.memory.graphiti.make_graphiti_client", boom)
    mem = build_memory(Settings(memory_backend="graphiti"), repo)
    assert isinstance(mem, JournalMemory)                    # 优雅回退


def test_build_memory_uses_graphiti_backend(repo, monkeypatch):
    fake = FakeGraphClient()
    monkeypatch.setattr("app.memory.graphiti.make_graphiti_client", lambda settings: fake)
    mem = build_memory(Settings(memory_backend="graphiti"), repo)
    assert isinstance(mem, GraphitiMemory)
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/memory/test_graphiti.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.memory.graphiti'`

- [ ] **Step 3: 实现 graphiti.py**

`backend/app/memory/graphiti.py`：
```python
"""L3 二阶段：Graphiti 时序图谱适配器（可选依赖）。

设计要点：
- 事件始终落 L2 事件表（权威来源），图谱只做增强——写失败只记日志、不回滚回合；
- 检索优先图谱事实，图谱不可用/报错时回退 JournalMemory 关键词检索；
- graphiti-core 是可选的异步库：延迟导入（extra: graph），
  `_GraphitiAdapter` 用后台线程独占事件循环把异步 API 桥接为同步 GraphClient。
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Protocol

from app.memory.base import MemoryEvent, MemoryHit
from app.memory.journal import JournalMemory

logger = logging.getLogger("ensemble.memory")


class GraphClient(Protocol):
    def add_episode(self, name: str, body: str, group_id: str,
                    reference_time: str) -> None: ...
    def search_facts(self, query: str, group_id: str, limit: int) -> list[str]: ...
    def close(self) -> None: ...


class GraphitiMemory:
    """MemoryService 实现：JournalMemory 为底座，时序图谱为增强。"""

    def __init__(self, repo, graph_client: GraphClient | None = None,
                 summarizer: Callable | None = None):
        self._repo = repo
        self._graph = graph_client
        self._journal = JournalMemory(repo, summarizer)

    @staticmethod
    def _group_id(campaign_id: str, branch_id: str) -> str:
        return f"{campaign_id}:{branch_id}"

    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None:
        self._journal.write_event(campaign_id, branch_id, event)
        if self._graph is None:
            return
        try:
            self._graph.add_episode(
                name=f"{event.type}:t{event.turn_id}", body=event.text,
                group_id=self._group_id(campaign_id, branch_id),
                reference_time=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logger.warning("graphiti add_episode failed: %s", exc)

    def search(self, campaign_id: str, branch_id: str, query: str,
               limit: int = 5) -> list[MemoryHit]:
        if self._graph is not None:
            try:
                facts = self._graph.search_facts(
                    query, self._group_id(campaign_id, branch_id), limit)
                return [MemoryHit(text=f, turn_id=0) for f in facts]   # 图谱事实无回合归属，回填 0
            except Exception as exc:
                logger.warning("graphiti search failed, fallback to journal: %s", exc)
        return self._journal.search(campaign_id, branch_id, query, limit)

    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str:
        return self._journal.get_context(campaign_id, branch_id, budget_chars)

    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None:
        before = self._repo.latest_summary(campaign_id, branch_id)
        self._journal.update_summaries(campaign_id, branch_id, turn_id)
        if self._graph is None:
            return
        after = self._repo.latest_summary(campaign_id, branch_id)
        if after is None or (before is not None and after.content == before.content
                             and after.turn_id == before.turn_id):
            return                                   # 未产生新摘要
        try:
            self._graph.add_episode(
                name=f"summary:t{turn_id}", body=after.content,
                group_id=self._group_id(campaign_id, branch_id),
                reference_time=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logger.warning("graphiti summary mirror failed: %s", exc)


class _GraphitiAdapter:
    """graphiti-core 异步 API → 同步 GraphClient（后台 daemon 线程独占事件循环）。"""

    def __init__(self, graphiti, timeout_seconds: int = 60):
        self._graphiti = graphiti
        self._timeout = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()

    def _serve_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(self._timeout)

    def add_episode(self, name: str, body: str, group_id: str, reference_time: str) -> None:
        from graphiti_core.nodes import EpisodeType
        self._call(self._graphiti.add_episode(
            name=name, episode_body=body, source=EpisodeType.text,
            source_description="ensemble turn event",
            reference_time=datetime.fromisoformat(reference_time),
            group_id=group_id))

    def search_facts(self, query: str, group_id: str, limit: int) -> list[str]:
        edges = self._call(self._graphiti.search(query=query, group_ids=[group_id],
                                                 num_results=limit))
        return [getattr(e, "fact", str(e)) for e in edges]

    def close(self) -> None:
        try:
            self._call(self._graphiti.close())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)


def make_graphiti_client(settings) -> GraphClient:
    """真实图谱客户端；graphiti-core 未安装 / 密码缺失时抛异常（由 build_memory 回退）。"""
    from graphiti_core import Graphiti          # 可选依赖：延迟导入
    if not settings.neo4j_password:
        raise RuntimeError("NEO4J_PASSWORD 未配置")
    graphiti = Graphiti(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    return _GraphitiAdapter(graphiti)


def build_memory(settings, repo, summarizer=None):
    """按配置装配 L3：journal（默认）| graphiti（初始化失败优雅回退并告警）。

    summarizer 由装配层传入（Task 18b 摘要接线：LLMSummarizer），透传给底层 JournalMemory。
    """
    if settings.memory_backend == "graphiti":
        try:
            graph = make_graphiti_client(settings)
            logger.info("L3 memory backend: graphiti")
            return GraphitiMemory(repo, graph_client=graph, summarizer=summarizer)
        except Exception as exc:
            logger.warning("Graphiti 不可用，回退 JournalMemory：%s", exc)
    return JournalMemory(repo, summarizer=summarizer)
```

- [ ] **Step 4: 修改装配与配置（四处）**

`backend/pyproject.toml` 在 `[dependency-groups]` 段之前追加（然后 `cd backend; uv sync`，基础同步不装 extra）：
```toml
[project.optional-dependencies]
graph = ["graphiti-core>=0.5"]
```

`backend/app/config.py` 的 `Settings` 追加字段（放在 `campaign_cost_cap_usd` 之后）：
```python
    memory_backend: str = "journal"           # journal | graphiti
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
```

`load_settings()` 追加 kwargs：
```python
        memory_backend=os.environ.get("ENSEMBLE_MEMORY_BACKEND", "journal"),
        neo4j_uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.environ.get("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("NEO4J_PASSWORD"),
```

`backend/app/cli.py`（三处）：
- import：`from app.memory.journal import JournalMemory` → `from app.memory.graphiti import build_memory`
- `AppContext` 的注解：`memory: JournalMemory | None` → `memory: object | None`（MemoryService 协议实现，Journal 或 Graphiti）
- `assemble()` 内：`memory = JournalMemory(repo, summarizer=LLMSummarizer(client))`（Task 18b 接线后形态）→ `memory = build_memory(settings, repo, summarizer=LLMSummarizer(client))`；摘要队列包装（`BackgroundQueue(name="summary")` + `BackgroundSummaries` + `queue.start()` 与 `main` 的 `flush(2.0)`）保留不变

`backend/app/api/session.py`（两处）：
- import：`from app.memory.journal import JournalMemory` → `from app.memory.graphiti import build_memory`
- `SessionManager._assemble()` 内 `journal = JournalMemory(deps.repo, summarizer=LLMSummarizer(client))`（Task 18b 接线后形态）→ `journal = build_memory(deps.settings, deps.repo, summarizer=LLMSummarizer(client))`；`build_game_graph(..., BackgroundSummaries(journal, queue), ...)` 包装与 queue 生命周期（`queue.start()`、`close()` / 切分支时 `flush/stop`）保留不变

- [ ] **Step 5: 验证通过（含全量回归）**

Run: `cd backend; uv run pytest tests/memory -q`
Expected: PASS（新增 9 passed + M2 既有 memory 用例全绿）

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 全量回归（`uv sync` 未安装 extra，`make_graphiti_client` 仅在 `memory_backend="graphiti"` 时被触碰，默认 journal 路径零影响）

- [ ] **Step 6: 真库手测（可选，需要 Docker）**

```powershell
docker run -d --name ensemble-neo4j -p 7687:7687 -p 7474:7474 `
  -e NEO4J_AUTH=neo4j/ensembledev neo4j:5
$env:NEO4J_PASSWORD="ensembledev"; $env:ENSEMBLE_MEMORY_BACKEND="graphiti"
cd backend; uv sync --extra graph
uv run python -m app.cli new ../modules/misty_hollow.yaml "图谱冒烟"
uv run python -m app.cli play <campaign_id> ../modules/misty_hollow.yaml
```

验收点：① 跑 2 回合无报错；② 浏览器打开 `http://localhost:7474`（neo4j/ensembledev）能看到 Episode 节点；③ 日志无"Graphiti 不可用，回退 JournalMemory"。
（若 `graphiti-core` 版本 API 有出入，以官方 README 的 `add_episode/search` 签名为准调整 `_GraphitiAdapter` 的两处调用；适配器协议与回退逻辑已被单测锁定，不受影响。）

- [ ] **Step 7: Commit**

```bash
git add backend/app/memory/graphiti.py backend/app/config.py backend/app/cli.py backend/app/api/session.py backend/pyproject.toml backend/uv.lock backend/tests/memory/test_graphiti.py
git commit -m "feat(memory): pluggable graphiti temporal graph adapter with graceful fallback"
```

---

### Task M5-2: 可观测性 —— 本地 JSONL 追踪 + LangSmith 开关

**Files:**
- Create: `backend/app/obs/__init__.py`（空文件）
- Create: `backend/app/obs/tracer.py`
- Create: `backend/tests/obs/test_tracer.py`
- Modify: `backend/app/config.py`（Settings + `traces_dir`；`load_settings` 读 env）
- Modify: `backend/app/llm/client.py`（`__init__` 加 `tracer`；`chat`/`chat_stream` 包裹）
- Modify: `backend/app/api/session.py`（`RoomSession.tracer` 字段；`_assemble` 注入；`_drive` 包 turn run）
- Modify: `backend/app/cli.py`（`assemble` 注入 tracer）
- Modify: `backend/pyproject.toml`（extra `observability`）
- Modify: `README.md`、`.env.example`（记忆后端 / traces / LangSmith 三开关）

**Interfaces:**
- Consumes: `LLMClient`（M2-11 / M3-2）、`RoomSession` / `SessionManager._assemble` / `_drive`（M3-11）、`assemble`（M2-24）、`Settings` / `load_settings`（M2-10、M3-5、M5-1 扩展后）
- Produces：
  - `Tracer(traces_dir: str)`：`start_run(name, run_type, inputs=None, parent_run_id=None) -> str`（只登记内存、不写盘）；`finish_run(run_id, outputs=None, error=None) -> None`（追加一行 JSON 到 `<traces_dir>/traces.jsonl`；未知 run_id 为 no-op）；属性 `current_turn_run_id: str | None`（LLM run 的 parent 挂接点）
  - JSONL 行字段（字段名固定，对齐 LangSmith run 格式）：`run_id / parent_run_id / name / run_type / inputs / outputs / start_time / end_time / error`
  - `make_tracer(settings) -> Tracer | None`（`traces_dir` 为空 → `None`，全链路零开销）
  - `Settings.traces_dir: str = ""`；env：`ENSEMBLE_TRACES_DIR`
  - `LLMClient(settings, pricing, usage_sink=None, model_factory=None, tracer=None)`：`chat`/`chat_stream` 每次调用记一条 `llm:{role}` run（parent 挂 `tracer.current_turn_run_id`）；异常记 `error` 后原样抛出；流式被中途放弃时既不记账也不落盘（与既有语义一致）
  - `RoomSession.tracer: Tracer | None = None`；`_drive` 每回合记一条 `turn:{turn_id}` run（outputs：`turn_id / latency_ms / npc_count / degraded / error`）
  - LangSmith：`uv sync --extra observability` + `LANGSMITH_TRACING=true` / `LANGSMITH_API_KEY`（openai SDK 内置集成，零代码改动，手测见 Step 9）

- [ ] **Step 1: 写失败测试**

`backend/tests/obs/test_tracer.py`：

```python
"""Tracer：JSONL 一行一 run；finish 才落盘（中途放弃不写断头 run）。"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.session import SessionManager
from app.config import Pricing, PricingEntry, Settings
from app.llm.client import ChatMessage, LLMClient, LlmContext
from app.llm.fakes import FakeLLM
from app.obs.tracer import Tracer, make_tracer


def make_pricing() -> Pricing:
    return Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.001, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0005, output_per_1k=0.001),
    })


def load_rows(tmp_path) -> list[dict]:
    path = tmp_path / "traces.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_finish_writes_single_line(tmp_path):
    tracer = Tracer(str(tmp_path))
    run_id = tracer.start_run("turn:0", "chain", inputs={"turn_id": 0})
    assert load_rows(tmp_path) == []                      # start 不落盘
    tracer.finish_run(run_id, outputs={"latency_ms": 12})
    rows = load_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == run_id and row["name"] == "turn:0"
    assert row["run_type"] == "chain" and row["parent_run_id"] is None
    assert row["inputs"] == {"turn_id": 0}
    assert row["outputs"] == {"latency_ms": 12}
    assert row["error"] is None
    assert row["start_time"] and row["end_time"]


def test_abandoned_run_not_written(tmp_path):
    tracer = Tracer(str(tmp_path))
    tracer.start_run("llm:gm", "llm", inputs={})
    tracer.finish_run("no-such-run")          # 未知 run_id 为 no-op
    assert load_rows(tmp_path) == []


def test_parent_and_error_recorded(tmp_path):
    tracer = Tracer(str(tmp_path))
    turn = tracer.start_run("turn:1", "chain", inputs={})
    child = tracer.start_run("llm:npc", "llm", inputs={}, parent_run_id=turn)
    tracer.finish_run(child, error="boom")
    tracer.finish_run(turn, outputs={})
    rows = {r["run_id"]: r for r in load_rows(tmp_path)}
    assert rows[child]["parent_run_id"] == turn
    assert rows[child]["error"] == "boom"


def test_make_tracer_respects_settings(tmp_path):
    assert make_tracer(Settings()) is None
    tracer = make_tracer(Settings(traces_dir=str(tmp_path)))
    assert isinstance(tracer, Tracer)


def test_llm_client_traces_chat_with_turn_parent(tmp_path):
    tracer = Tracer(str(tmp_path))
    turn = tracer.start_run("turn:3", "chain", inputs={})
    tracer.current_turn_run_id = turn
    client = LLMClient(Settings(), make_pricing(),
                       model_factory=lambda *_: FakeLLM(["你好"]), tracer=tracer)
    ctx = LlmContext(campaign_id="c1", branch_id="b1", turn_id=3)
    text = client.chat("gm", [ChatMessage(role="user", content="开始")], ctx)
    assert text == "你好"
    rows = [r for r in load_rows(tmp_path) if r["run_type"] == "llm"]
    assert len(rows) == 1
    assert rows[0]["parent_run_id"] == turn
    assert rows[0]["inputs"]["model"] == "qwen-plus"
    assert rows[0]["outputs"]["text"] == "你好"


def test_llm_client_traces_failure_and_raises(tmp_path):
    tracer = Tracer(str(tmp_path))
    client = LLMClient(Settings(), make_pricing(),
                       model_factory=lambda *_: FakeLLM([]), tracer=tracer)
    ctx = LlmContext(campaign_id="c1", branch_id="b1", turn_id=1)
    with pytest.raises(IndexError):
        client.chat("gm", [ChatMessage(role="user", content="x")], ctx)
    rows = load_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["error"] and "exhausted" in rows[0]["error"]


class _FakeBus:
    def __init__(self):
        self.events: list[tuple] = []

    def push(self, event_type, payload, visibility="all"):
        self.events.append((event_type, payload))


class _FakeGraph:
    def __init__(self, values):
        self._values = values

    def get_state(self, config):
        return SimpleNamespace(values=self._values)

    async def astream(self, inp, config, stream_mode=None):
        yield {"text": "……"}


class _FakeSession:
    def __init__(self, tracer):
        self.driving = False
        self.campaign_id = "c1"
        self.branch_id = "b1"
        self.tracer = tracer
        self.bus = _FakeBus()
        self.graph = _FakeGraph({"turn_id": 2,
                                 "npc_reactions": {"guard": {"npc_id": "guard"}}})
        self.config = {"configurable": {"thread_id": "b1"}}


def test_drive_writes_turn_run(tmp_path):
    tracer = Tracer(str(tmp_path))
    manager = SessionManager.__new__(SessionManager)        # 免构造：只测 _drive
    manager._push_snapshot = lambda session: None
    session = _FakeSession(tracer=tracer)
    asyncio.run(manager._drive(session, {}))
    rows = load_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "turn:2" and row["run_type"] == "chain"
    assert row["inputs"]["campaign_id"] == "c1"
    assert row["outputs"]["npc_count"] == 1
    assert row["outputs"]["latency_ms"] >= 0 and row["outputs"]["error"] is None
    assert tracer.current_turn_run_id is None


def test_drive_without_tracer_is_silent(tmp_path):
    manager = SessionManager.__new__(SessionManager)
    manager._push_snapshot = lambda session: None
    session = _FakeSession(tracer=None)
    asyncio.run(manager._drive(session, {}))
    assert load_rows(tmp_path) == []
    assert any(e[0] == "turn" for e in session.bus.events)   # 事件照常推送
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/obs -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.obs'`

- [ ] **Step 3: 实现 tracer.py**

`backend/app/obs/__init__.py`：空文件。

`backend/app/obs/tracer.py`：
```python
"""可观测性：本地 JSONL 追踪（一行一个完整 run，字段对齐 LangSmith run 格式）。

设计约定：
- start_run 只登记内存，finish_run 才追加写盘 → 中途放弃的流不会留下断头 run；
- 每行 JSON 独立完整；单进程内追加写（open "a"）简单安全；
- 与 LangSmith 字段对齐，供本地无网调试与"每回合延迟 / LLM 成功率"分析。
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Tracer:
    def __init__(self, traces_dir: str):
        self._dir = Path(traces_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "traces.jsonl"
        self._pending: dict[str, dict] = {}
        self.current_turn_run_id: str | None = None

    def start_run(self, name: str, run_type: str, inputs: dict | None = None,
                  parent_run_id: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        self._pending[run_id] = {
            "run_id": run_id, "parent_run_id": parent_run_id,
            "name": name, "run_type": run_type,
            "inputs": inputs or {}, "start_time": _now(),
        }
        return run_id

    def finish_run(self, run_id: str, outputs: dict | None = None,
                   error: str | None = None) -> None:
        meta = self._pending.pop(run_id, None)
        if meta is None:
            return
        meta["outputs"] = outputs or {}
        meta["end_time"] = _now()
        meta["error"] = error
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")


def make_tracer(settings) -> Tracer | None:
    """traces_dir 为空（默认）→ 关闭追踪，零开销。"""
    return Tracer(settings.traces_dir) if settings.traces_dir else None
```

- [ ] **Step 4: 修改 config.py 与 pyproject.toml**

`backend/app/config.py` 的 `Settings`，在 M5-1 追加的 `neo4j_password` 之后追加字段：
```python
    traces_dir: str = ""                      # 空 = 关闭本地 JSONL 追踪
```
`load_settings()` 在 M5-1 追加的 kwargs 之后追加：
```python
        traces_dir=os.environ.get("ENSEMBLE_TRACES_DIR", ""),
```

`backend/pyproject.toml` 在 M5-1 追加的 `graph = ["graphiti-core>=0.5"]` 行之后追加一行：
```toml
observability = ["langsmith>=0.1.100"]
```
然后 `cd backend; uv sync`（基础同步不装 extra）。

- [ ] **Step 5: 修改 llm/client.py（tracer 包裹）**

头部 import 追加（`from app.config import Pricing, Settings` 之后）：
```python
from app.obs.tracer import Tracer
```

`LLMClient.__init__` 整体替换为（新增 `tracer` 参数与两个私有 helper）：
```python
    def __init__(self, settings: Settings, pricing: Pricing,
                 usage_sink: UsageSink | None = None, model_factory: ModelFactory | None = None,
                 tracer: Tracer | None = None):
        self._settings = settings
        self._pricing = pricing
        self._usage_sink = usage_sink
        self._factory: ModelFactory = model_factory or _default_factory
        self._tracer = tracer

    def _start_llm_run(self, role: Role, messages: list[ChatMessage], model: str,
                       cheap: bool) -> str | None:
        if self._tracer is None:
            return None
        return self._tracer.start_run(
            name=f"llm:{role}", run_type="llm",
            inputs={"role": role, "model": model, "cheap": cheap,
                    "messages": [{"role": m.role, "content": m.content}
                                 for m in messages]},
            parent_run_id=self._tracer.current_turn_run_id)

    def _finish_llm_run(self, run_id: str | None, outputs: dict | None = None,
                        error: str | None = None) -> None:
        if self._tracer is not None and run_id is not None:
            self._tracer.finish_run(run_id, outputs=outputs, error=error)
```

`chat` 方法整体替换为：
```python
    def chat(self, role: Role, messages: list[ChatMessage], ctx: LlmContext,
             cheap: bool = False) -> str:
        model, base_url, api_key = self._resolve(role, cheap)
        model_obj = self._factory(model, base_url, api_key)
        run_id = self._start_llm_run(role, messages, model, cheap)
        start = time.perf_counter()
        try:
            resp = model_obj.chat(messages)
        except Exception as exc:
            self._finish_llm_run(run_id, error=str(exc))
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        cost = compute_cost(self._pricing, model, resp.tokens_in, resp.tokens_out)
        if self._usage_sink is not None:
            self._usage_sink.record_usage(ctx.campaign_id, ctx.branch_id, ctx.turn_id,
                                          role, model, resp.tokens_in, resp.tokens_out,
                                          cost, latency_ms)
        self._finish_llm_run(run_id, outputs={"text": resp.text,
                                              "tokens_in": resp.tokens_in,
                                              "tokens_out": resp.tokens_out,
                                              "latency_ms": latency_ms,
                                              "cost_usd": cost})
        return resp.text
```

`chat_stream` 方法整体替换为：
```python
    def chat_stream(self, role: Role, messages: list[ChatMessage], ctx: LlmContext,
                    cheap: bool = False) -> Iterator[str]:
        """流式输出；流正常结束后记一次账（消费方中途放弃则不记账、不落 trace）。"""
        model, base_url, api_key = self._resolve(role, cheap)
        model_obj = self._factory(model, base_url, api_key)
        usage = StreamUsage()
        chars = 0
        parts: list[str] = []
        run_id = self._start_llm_run(role, messages, model, cheap)
        start = time.perf_counter()
        try:
            for delta in model_obj.chat_stream(messages, usage):
                chars += len(delta)
                parts.append(delta)
                yield delta
        except Exception as exc:
            self._finish_llm_run(run_id, error=str(exc))
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        if usage.tokens_in == 0 and usage.tokens_out == 0:
            usage.tokens_in = max(1, sum(len(m.content) for m in messages) // 2)
            usage.tokens_out = max(1, chars // 2)
        cost = compute_cost(self._pricing, model, usage.tokens_in, usage.tokens_out)
        if self._usage_sink is not None:
            self._usage_sink.record_usage(ctx.campaign_id, ctx.branch_id, ctx.turn_id,
                                          role, model, usage.tokens_in, usage.tokens_out,
                                          cost, latency_ms)
        self._finish_llm_run(run_id, outputs={"text": "".join(parts),
                                              "tokens_in": usage.tokens_in,
                                              "tokens_out": usage.tokens_out,
                                              "latency_ms": latency_ms,
                                              "cost_usd": cost})
```

- [ ] **Step 6: 修改 api/session.py（装配 + 回合追踪）**

import 追加（`from app.memory.graphiti import build_memory` 之后）：
```python
from app.obs.tracer import Tracer, make_tracer
```

`RoomSession` 在 `window_started: float = 0.0` 之后追加字段：
```python
    tracer: Tracer | None = None
```

`SessionManager._assemble` 中 client 构造替换为（新增 `tracer` 行）：
```python
        tracer = make_tracer(deps.settings)
        client = LLMClient(deps.settings, load_pricing(deps.settings.pricing_path),
                           usage_sink=deps.repo, model_factory=deps.model_factory,
                           tracer=tracer)
```

`RoomSession(...)` 构造行追加参数：
```python
            branch_id=campaign.active_branch_id, tracer=tracer)
```

`_drive` 方法整体替换为：
```python
    async def _drive(self, session: RoomSession, inp) -> None:
        session.driving = True
        snap0 = session.graph.get_state(session.config)
        turn_id0 = int((snap0.values or {}).get("turn_id", 0))
        session.bus.push("turn", {"phase": "resolving", "turn_id": turn_id0})
        tracer = session.tracer
        run_id: str | None = None
        started = time.perf_counter()
        if tracer is not None:
            run_id = tracer.start_run(name=f"turn:{turn_id0}", run_type="chain",
                                      inputs={"campaign_id": session.campaign_id,
                                              "branch_id": session.branch_id,
                                              "turn_id": turn_id0})
            tracer.current_turn_run_id = run_id
        drive_error: str | None = None
        try:
            async for chunk in session.graph.astream(inp, session.config,
                                                     stream_mode="custom"):
                if isinstance(chunk, dict) and ("text" in chunk or "reset" in chunk):
                    session.bus.push("token", dict(chunk))
        except Exception as exc:      # 图执行意外崩溃：提示但保留会话（可重连续玩）
            drive_error = str(exc)
            session.bus.push("error", {"message": f"图执行失败：{exc}"})
        finally:
            session.driving = False
        if tracer is not None and run_id is not None:
            values = (session.graph.get_state(session.config).values) or {}
            tracer.finish_run(run_id, outputs={
                "turn_id": int(values.get("turn_id", turn_id0)),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "npc_count": len(values.get("npc_reactions") or {}),
                "degraded": dict(values.get("degraded") or {}),
                "error": drive_error})
            tracer.current_turn_run_id = None
        self._push_snapshot(session)
```

- [ ] **Step 7: 修改 cli.py（注入 tracer）**

import 追加（`from app.memory.graphiti import build_memory` 之后）：
```python
from app.obs.tracer import make_tracer
```
`assemble()` 内 client 构造一行替换：
```python
    client = LLMClient(settings, pricing, usage_sink=repo, tracer=make_tracer(settings))
```

- [ ] **Step 8: 验证通过（含全量回归）**

Run: `cd backend; uv run pytest tests/obs -q`
Expected: PASS（8 passed）

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 全量回归；默认 `traces_dir=""`（tracer=None），既有测试零影响

- [ ] **Step 9: 更新 .env.example 与 README（三开关 + 手测）**

`.env.example` 追加（在 M4-6 已有的两行密钥之后）：
```bash
# --- M5 可选开关（默认全部关闭，不影响既有行为） ---
# 记忆后端：journal（默认）| graphiti（需要 uv sync --extra graph + Neo4j）
ENSEMBLE_MEMORY_BACKEND=journal
# NEO4J_URI=bolt://localhost:7687
# NEO4J_USER=neo4j
# NEO4J_PASSWORD=

# 本地 JSONL 追踪目录（留空 = 关闭；设置后每回合与每次 LLM 调用各写一行）
ENSEMBLE_TRACES_DIR=

# LangSmith 云追踪（uv sync --extra observability 后开启）
LANGSMITH_TRACING=false
# LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=ensemble
```

README 追加「M5 增强」章节（本地 JSONL 手测 + LangSmith 零代码手测 + 记忆后端切换）：

````markdown
## M5 增强（可选能力）

### 本地追踪（JSONL，默认关闭）

```bash
cd backend
$env:ENSEMBLE_TRACES_DIR="../.traces"     # PowerShell；bash 用 export
uv run python -m app.cli play <campaign_id> <module_path>
```

`../.traces/traces.jsonl` 每行一个完整 run（`turn:*` 回合 / `llm:{role}` 模型调用），
字段与 LangSmith run 对齐：`run_id / parent_run_id / name / run_type / inputs / outputs / start_time / end_time / error`。
中途失败/放弃的调用不会留下断头 run。

### LangSmith 云追踪（零代码）

```bash
cd backend
uv sync --extra observability
$env:LANGSMITH_TRACING="true"; $env:LANGSMITH_API_KEY="lsv2_..."; $env:LANGSMITH_PROJECT="ensemble"
uv run python -m app.cli play <campaign_id> <module_path>
```

openai SDK 检测到 langsmith 与开关后自动上报，无需代码改动；跑两回合后在 Smith 项目里可见调用链与耗时。
（若所用版本未自动挂钩，按 LangSmith 官方 openai 集成文档处理；本地 JSONL 路径始终可用。）

### 记忆后端切换

`ENSEMBLE_MEMORY_BACKEND=graphiti` 时需要 `uv sync --extra graph` 与 Neo4j（连接参数见 `.env.example`）；
初始化失败会回退 journal 并在日志中告警。
````

- [ ] **Step 10: Commit**

```bash
git add backend/app/obs backend/app/config.py backend/app/llm/client.py backend/app/api/session.py backend/app/cli.py backend/pyproject.toml backend/uv.lock backend/tests/obs README.md .env.example
git commit -m "feat(obs): local JSONL tracing with LangSmith-compatible run records"
```

---

### Task M5-3: 可观测性 —— /metrics 四指标 + 成本汇总

**Files:**
- Create: `backend/app/obs/counters.py`
- Create: `backend/tests/obs/test_counters.py`
- Create: `backend/tests/graph/test_fallbacks_count.py`
- Create: `backend/tests/api/test_metrics.py`
- Modify: `backend/app/llm/client.py`（`chat` / `chat_stream` 记 LLM 成败）
- Modify: `backend/app/graph/nodes/memory.py`（`memory_query` 降级计数）
- Modify: `backend/app/graph/nodes/npc.py`（`npc_silent` 降级计数）
- Modify: `backend/app/graph/nodes/gm.py`（`decision_invalid` / `narrate_failed` 降级计数）
- Modify: `backend/app/graph/nodes/turn.py`（`budget_paused` 降级计数）
- Modify: `backend/app/api/session.py`（`_drive` 记 `record_turn`）
- Modify: `backend/app/storage/repo.py`（`usage_totals`）
- Modify: `backend/app/api/app.py`（`GET /metrics`）

**Interfaces:**
- Consumes: `LLMClient`（M2，M5-2 包装后）、`SessionManager._drive`（M3-11，M5-2 包装后）、节点工厂 `build_memory_query_node(memory)` / `build_npc_worker(subgraph)` / `build_validate_node(client)` / `build_narrate_node(client, module)` / `build_intake_node(repo, module, guard)`（M2）、`SqliteRepository.record_usage` 与 `UsageRow`（M2）、`AppDeps` / `create_app`（M3-5，M3-11 扩展）
- Produces：
  - `Counters`：`record_llm(ok: bool = True)`；`record_fallback(kind: str)`；`record_turn(latency_ms: int, npc_count: int)`；`snapshot() -> dict`，结构固定：
    ```python
    {"llm": {"calls": int, "failures": int},
     "fallbacks": {kind: int},          # kind ∈ memory_query / npc_silent / decision_invalid / narrate_failed / budget_paused
     "turns": {"count": int, "p50_ms": int, "p95_ms": int},   # 最近 200 回合窗口
     "npc_activation": {str(n): int}}   # 每回合 NPC 反应数分布
    ```
  - `get_counters() -> Counters`（进程内单例）；`reset_counters() -> None`（测试隔离）
  - `SqliteRepository.usage_totals() -> dict`：`{"calls": int, "tokens_in": int, "tokens_out": int, "cost_usd": float}`
  - `GET /metrics` → `snapshot()` + `{"scope": "process", "usage": usage_totals()}`（重启清零；不引入 Prometheus）

- [ ] **Step 1: 写失败测试**

`backend/tests/obs/test_counters.py`：
```python
"""Counters：进程内四指标（LLM 成败 / 降级 / 回合延迟 / NPC 激活分布）。"""
import asyncio
from types import SimpleNamespace

import pytest

from app.api.session import SessionManager
from app.config import Pricing, PricingEntry, Settings
from app.llm.client import ChatMessage, LLMClient, LlmContext
from app.llm.fakes import FakeLLM
from app.obs.counters import Counters, get_counters, reset_counters


def make_pricing() -> Pricing:
    return Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.001, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0005, output_per_1k=0.001),
    })


def test_snapshot_math_and_shape():
    c = Counters()
    c.record_llm(ok=True)
    c.record_llm(ok=True)
    c.record_llm(ok=False)
    c.record_fallback("memory_query")
    c.record_fallback("memory_query")
    c.record_fallback("npc_silent")
    for i, ms in enumerate([10, 20, 30, 40]):
        c.record_turn(ms, npc_count=i % 2)
    snap = c.snapshot()
    assert snap["llm"] == {"calls": 3, "failures": 1}
    assert snap["fallbacks"] == {"memory_query": 2, "npc_silent": 1}
    assert snap["turns"] == {"count": 4, "p50_ms": 30, "p95_ms": 40}
    assert snap["npc_activation"] == {"0": 2, "1": 2}


def test_empty_snapshot():
    assert Counters().snapshot() == {
        "llm": {"calls": 0, "failures": 0}, "fallbacks": {},
        "turns": {"count": 0, "p50_ms": 0, "p95_ms": 0}, "npc_activation": {}}


def test_latency_window_capped_at_200():
    c = Counters()
    for _ in range(250):
        c.record_turn(7, npc_count=0)
    assert c.snapshot()["turns"]["count"] == 200


def test_reset_counters_isolates():
    get_counters().record_llm(ok=False)
    assert get_counters().snapshot()["llm"]["failures"] == 1
    reset_counters()
    assert get_counters().snapshot()["llm"]["failures"] == 0


def test_llm_client_counts_success_and_failure():
    reset_counters()
    ctx = LlmContext(campaign_id="c1", branch_id="b1", turn_id=1)
    ok = LLMClient(Settings(), make_pricing(),
                   model_factory=lambda *_: FakeLLM(["你好"]))
    assert ok.chat("gm", [ChatMessage(role="user", content="开始")], ctx) == "你好"
    bad = LLMClient(Settings(), make_pricing(),
                    model_factory=lambda *_: FakeLLM([]))
    with pytest.raises(IndexError):
        bad.chat("gm", [ChatMessage(role="user", content="x")], ctx)
    assert get_counters().snapshot()["llm"] == {"calls": 2, "failures": 1}


class _FakeBus:
    def __init__(self):
        self.events: list[tuple] = []

    def push(self, event_type, payload, visibility="all"):
        self.events.append((event_type, payload))


class _FakeGraph:
    def __init__(self, values):
        self._values = values

    def get_state(self, config):
        return SimpleNamespace(values=self._values)

    async def astream(self, inp, config, stream_mode=None):
        yield {"text": "……"}


class _FakeSession:
    def __init__(self):
        self.driving = False
        self.campaign_id = "c1"
        self.branch_id = "b1"
        self.tracer = None
        self.bus = _FakeBus()
        self.graph = _FakeGraph({"turn_id": 2,
                                 "npc_reactions": {"guard": {"npc_id": "guard"}}})
        self.config = {"configurable": {"thread_id": "b1"}}


def test_drive_records_turn_latency_and_npc_count():
    reset_counters()
    manager = SessionManager.__new__(SessionManager)      # 免构造：只测 _drive
    manager._push_snapshot = lambda session: None
    asyncio.run(manager._drive(_FakeSession(), {}))
    snap = get_counters().snapshot()
    assert snap["turns"]["count"] == 1
    assert snap["turns"]["p50_ms"] >= 0
    assert snap["npc_activation"] == {"1": 1}
```

`backend/tests/graph/test_fallbacks_count.py`：
```python
"""降级路径 → 计数器挂钩：五类 fallback kind 各计一次（节点返回值保持既有语义）。"""
from app.config import Pricing, PricingEntry, Settings
from app.graph.nodes.gm import build_narrate_node, build_validate_node
from app.graph.nodes.memory import build_memory_query_node
from app.graph.nodes.npc import build_npc_worker
from app.graph.nodes.turn import build_intake_node
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.obs.counters import get_counters, reset_counters


def make_client(script: list[str]):
    built: dict[str, FakeLLM] = {}

    def factory(model, base_url, api_key):
        if model not in built:                     # 同一 model 复用同一脚本队列
            built[model] = FakeLLM(list(script))
        return built[model]

    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.001, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0005, output_per_1k=0.001),
    })
    return LLMClient(Settings(), pricing, model_factory=factory)


def fallbacks() -> dict:
    return get_counters().snapshot()["fallbacks"]


def test_memory_failure_counts(campaign):
    reset_counters()

    class BrokenMemory:
        def get_context(self, *a, **kw):
            raise RuntimeError("memory down")

        def search(self, *a, **kw):
            raise RuntimeError("memory down")

        def update_summaries(self, *a, **kw):
            pass

    build_memory_query_node(BrokenMemory())({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
        "turn_id": 1, "decision": {"memory_queries": ["磨坊"]},
        "budget_level": "ok"})
    assert fallbacks() == {"memory_query": 1}


def test_npc_failure_counts_silent():
    reset_counters()

    class BrokenSubgraph:
        def invoke(self, task):
            raise RuntimeError("npc down")

    out = build_npc_worker(BrokenSubgraph())({"npc_id": "guard"})
    assert out["npc_reactions"]["guard"]["speech"] == ""   # 沉默占位照常返回
    assert fallbacks() == {"npc_silent": 1}


def test_decision_invalid_counts():
    reset_counters()
    client = make_client(["还不是 JSON"])
    upd = build_validate_node(client)({
        "decision_raw": "不是 JSON", "budget_level": "ok",
        "campaign_id": "c", "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] == "decision_invalid"
    assert fallbacks() == {"decision_invalid": 1}


def test_narrate_failed_counts(campaign, mini_module):
    reset_counters()
    client = make_client(["", "   "])
    upd = build_narrate_node(client, mini_module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
        "turn_id": 1, "scene_id": "gate", "is_opening": False,
        "player_inputs": [{"player_id": "p1", "character_id": "pc_1",
                           "text": "我想进城"}],
        "check_results": [], "npc_reactions": {},
        "memory_context": "", "budget_level": "ok"})
    assert upd["error"] == "narrate_failed"
    assert fallbacks() == {"narrate_failed": 1}


def test_budget_paused_counts(repo, campaign, mini_module):
    reset_counters()
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen-plus",
                      1, 1, 5.0, 100)
    guard = BudgetGuard(Settings(campaign_cost_cap_usd=1.0))
    upd = build_intake_node(repo, mini_module, guard)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
        "turn_id": 0, "player_inputs": []})
    assert upd["budget_level"] == "paused" and upd["error"] == "budget_paused"
    assert fallbacks() == {"budget_paused": 1}
```

`backend/tests/api/test_metrics.py`：
```python
"""GET /metrics：进程内快照（scope=process）+ DB usage 汇总。"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.obs.counters import get_counters, reset_counters
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def client(tmp_path):
    engine = make_engine(str(tmp_path / "api.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "api.db"),
                        modules_dir=str(ROOT / "modules"))
    return TestClient(create_app(AppDeps(settings=settings, repo=repo))), repo


def test_metrics_snapshot_and_usage(client):
    reset_counters()
    c, repo = client
    repo.record_usage("c1", "c1@main", 1, "gm", "qwen-plus", 100, 50, 0.0004, 120)
    get_counters().record_llm(ok=True)
    get_counters().record_turn(1500, npc_count=2)
    body = c.get("/metrics").json()
    assert body["scope"] == "process"
    assert body["llm"] == {"calls": 1, "failures": 0}
    assert body["turns"]["count"] == 1 and body["turns"]["p50_ms"] == 1500
    assert body["npc_activation"] == {"2": 1}
    assert body["usage"] == {"calls": 1, "tokens_in": 100,
                             "tokens_out": 50, "cost_usd": 0.0004}
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/obs/test_counters.py tests/graph/test_fallbacks_count.py tests/api/test_metrics.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.obs.counters'`

- [ ] **Step 3: 实现 counters.py**

`backend/app/obs/counters.py`：
```python
"""进程内指标计数器（/metrics 数据源）。

设计约定：
- 纯进程内存：重启清零，响应以 scope="process" 声明；
- 回合延迟只保留最近 200 个样本（deque maxlen），p50/p95 为排序后最近秩取值；
- fallback kind 固定五类：memory_query / npc_silent / decision_invalid /
  narrate_failed / budget_paused，与各处降级路径一一对应。
"""
from collections import Counter, deque

_TURN_WINDOW = 200


class Counters:
    def __init__(self) -> None:
        self.llm_calls = 0
        self.llm_failures = 0
        self.fallbacks: Counter[str] = Counter()
        self.turn_latencies: deque[int] = deque(maxlen=_TURN_WINDOW)
        self.npc_activation: Counter[str] = Counter()

    def record_llm(self, ok: bool = True) -> None:
        self.llm_calls += 1
        if not ok:
            self.llm_failures += 1

    def record_fallback(self, kind: str) -> None:
        self.fallbacks[kind] += 1

    def record_turn(self, latency_ms: int, npc_count: int) -> None:
        self.turn_latencies.append(int(latency_ms))
        self.npc_activation[str(npc_count)] += 1

    def snapshot(self) -> dict:
        lat = sorted(self.turn_latencies)

        def _pct(p: float) -> int:
            if not lat:
                return 0
            return lat[min(len(lat) - 1, int(len(lat) * p))]

        return {
            "llm": {"calls": self.llm_calls, "failures": self.llm_failures},
            "fallbacks": dict(self.fallbacks),
            "turns": {"count": len(lat), "p50_ms": _pct(0.50), "p95_ms": _pct(0.95)},
            "npc_activation": dict(self.npc_activation),
        }


_counters = Counters()


def get_counters() -> Counters:
    return _counters


def reset_counters() -> None:
    """测试隔离用：替换为新实例（引用方始终经 get_counters() 取最新单例）。"""
    global _counters
    _counters = Counters()
```

- [ ] **Step 4: 修改 llm/client.py（LLM 成败计数）**

import 追加（M5-2 追加的 `from app.obs.tracer import Tracer` 之后）：
```python
from app.obs.counters import get_counters
```

`chat` 失败分支改为（在原 `try/except` 中新增首行）：
```python
        try:
            resp = model_obj.chat(messages)
        except Exception as exc:
            get_counters().record_llm(ok=False)
            self._finish_llm_run(run_id, error=str(exc))
            raise
```
`chat` 成功收尾改为（在 `_finish_llm_run` 之后、`return` 之前新增一行）：
```python
        self._finish_llm_run(run_id, outputs={"text": resp.text,
                                              "tokens_in": resp.tokens_in,
                                              "tokens_out": resp.tokens_out,
                                              "latency_ms": latency_ms,
                                              "cost_usd": cost})
        get_counters().record_llm(ok=True)
        return resp.text
```
`chat_stream` 失败分支改为（`for delta in model_obj.chat_stream(messages, usage)` 循环后的 except）：
```python
            for delta in model_obj.chat_stream(messages, usage):
                chars += len(delta)
                parts.append(delta)
                yield delta
        except Exception as exc:
            get_counters().record_llm(ok=False)
            self._finish_llm_run(run_id, error=str(exc))
            raise
```
`chat_stream` 成功收尾改为（生成器正常耗尽时执行）：
```python
        self._finish_llm_run(run_id, outputs={"text": "".join(parts),
                                              "tokens_in": usage.tokens_in,
                                              "tokens_out": usage.tokens_out,
                                              "latency_ms": latency_ms,
                                              "cost_usd": cost})
        get_counters().record_llm(ok=True)
```
（消费方中途放弃流时不走到收尾：既不记账也不落 trace，与 M5-2 语义一致。）

- [ ] **Step 5: 五处降级挂钩（5 个节点文件）**

`backend/app/graph/nodes/memory.py`：import 区追加 `from app.obs.counters import get_counters`；然后
```python
        except Exception:
            return {"memory_context": "", "degraded": {"memory_query": True}}
```
替换为
```python
        except Exception:
            get_counters().record_fallback("memory_query")
            return {"memory_context": "", "degraded": {"memory_query": True}}
```

`backend/app/graph/nodes/npc.py`：import 区追加 `from app.obs.counters import get_counters`；然后
```python
        except Exception:
            reaction = {}  # 单个 NPC 失败 → 沉默占位（规格 §8），其余 NPC 不受影响
```
替换为
```python
        except Exception:
            get_counters().record_fallback("npc_silent")
            reaction = {}  # 单个 NPC 失败 → 沉默占位（规格 §8），其余 NPC 不受影响
```

`backend/app/graph/nodes/gm.py`：import 区追加 `from app.obs.counters import get_counters`；两处——

validate（`build_validate_node` 重试耗尽后的失败返回，位于 `for _ in range(2)` 循环之外——M3-4 已把 validate 重写为循环结构，不存在内层 `except: return`）：
```python
        return {"error": "decision_invalid", "decision": None,
                "degraded": {"decision_invalid": True}}
```
替换为
```python
        get_counters().record_fallback("decision_invalid")
        return {"error": "decision_invalid", "decision": None,
                "degraded": {"decision_invalid": True}}
```
narrate（`build_narrate_node` 两次尝试均失败后的最终返回）：
```python
        return {"error": "narrate_failed", "degraded": {"narrate_failed": True},
                "narration": "", "narration_segments": []}
```
替换为
```python
        get_counters().record_fallback("narrate_failed")
        return {"error": "narrate_failed", "degraded": {"narrate_failed": True},
                "narration": "", "narration_segments": []}
```

`backend/app/graph/nodes/turn.py`：import 区追加 `from app.obs.counters import get_counters`；然后
```python
        if level == "paused":
            upd["error"] = "budget_paused"
```
替换为
```python
        if level == "paused":
            get_counters().record_fallback("budget_paused")
            upd["error"] = "budget_paused"
```

- [ ] **Step 6: 修改 api/session.py（_drive 记回合延迟）**

import 追加（M5-2 追加的 `from app.obs.tracer import Tracer, make_tracer` 之后）：
```python
from app.obs.counters import get_counters
```
`_drive` 尾段（M5-2 版本）
```python
        if tracer is not None and run_id is not None:
            values = (session.graph.get_state(session.config).values) or {}
            tracer.finish_run(run_id, outputs={
                "turn_id": int(values.get("turn_id", turn_id0)),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "npc_count": len(values.get("npc_reactions") or {}),
                "degraded": dict(values.get("degraded") or {}),
                "error": drive_error})
            tracer.current_turn_run_id = None
        self._push_snapshot(session)
```
替换为
```python
        values = (session.graph.get_state(session.config).values) or {}
        latency_ms = int((time.perf_counter() - started) * 1000)
        npc_count = len(values.get("npc_reactions") or {})
        get_counters().record_turn(latency_ms, npc_count)     # 无 tracer 也计数
        if tracer is not None and run_id is not None:
            tracer.finish_run(run_id, outputs={
                "turn_id": int(values.get("turn_id", turn_id0)),
                "latency_ms": latency_ms,
                "npc_count": npc_count,
                "degraded": dict(values.get("degraded") or {}),
                "error": drive_error})
            tracer.current_turn_run_id = None
        self._push_snapshot(session)
```

- [ ] **Step 7: 修改 storage/repo.py 与 api/app.py**

`backend/app/storage/repo.py`：在 `campaign_cost_total` 方法之后追加：
```python
    def usage_totals(self) -> dict:
        q = select(UsageRow)
        with Session(self.engine) as s:
            rows = s.exec(q).all()
        return {"calls": len(rows),
                "tokens_in": sum(r.tokens_in for r in rows),
                "tokens_out": sum(r.tokens_out for r in rows),
                "cost_usd": round(sum(r.cost_usd for r in rows), 6)}
```

`backend/app/api/app.py`：import 区追加（`from app.storage.repo import SqliteRepository` 之后）：
```python
from app.obs.counters import get_counters
```
在 `/healthz` 路由之后追加：
```python
    @app.get("/metrics")
    def metrics():
        snapshot = get_counters().snapshot()
        snapshot["scope"] = "process"          # 进程内计数器：重启清零，非持久化
        snapshot["usage"] = deps.repo.usage_totals()
        return snapshot
```

- [ ] **Step 8: 验证通过（含全量回归）**

Run: `cd backend; uv run pytest tests/obs/test_counters.py tests/graph/test_fallbacks_count.py tests/api/test_metrics.py -q`
Expected: PASS（12 passed：6 + 5 + 1）

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 全量回归；计数为旁挂行为，不改变任何既有函数返回值与事件流

- [ ] **Step 9: Commit**

```bash
git add backend/app/obs/counters.py backend/app/llm/client.py backend/app/graph/nodes/memory.py backend/app/graph/nodes/npc.py backend/app/graph/nodes/gm.py backend/app/graph/nodes/turn.py backend/app/api/session.py backend/app/storage/repo.py backend/app/api/app.py backend/tests/obs/test_counters.py backend/tests/graph/test_fallbacks_count.py backend/tests/api/test_metrics.py
git commit -m "feat(obs): /metrics with turn latency, llm success rate and fallback counters"
```

---

### Task M5-4: 奖惩骰全链路（规则 → GM → 存储 → 前端）

**Files:**
- Modify: `backend/app/rules/dice.py`、`backend/app/rules/check.py`、`backend/app/storage/models.py`、`backend/app/storage/db.py`、`backend/app/storage/repo.py`、`backend/app/graph/schemas.py`、`backend/app/graph/nodes/turn.py`、`backend/app/graph/nodes/gm.py`、`backend/app/api/session.py`、`frontend/src/types.ts`、`frontend/src/components/DiceOverlay.tsx`、`frontend/src/components/DiceLogPanel.tsx`、`frontend/src/styles.css`
- Test: 追加 `backend/tests/rules/test_dice.py`、`backend/tests/rules/test_check.py`、`backend/tests/graph/test_resolve_checks.py`、`backend/tests/storage/test_migration.py`（M4-1 已建，追加 2 例）、`frontend/src/components/__tests__/DiceOverlay.test.tsx`

**Interfaces:**
- Consumes: `new_seed()` / `roll_d100(seed)`（M2 Task 2）、`CheckDifficulty` / `SuccessLevel` / `CheckResult` / `roll_check`（M2 Task 3）、`DiceRecordRow` / `make_engine`（M2 Task 4）、`SqliteRepository.add_dice_record / list_dice_records`（M2 Task 9）、`_skill_value` / `build_resolve_checks_node`（M2 Task 14）、`DECIDE_SYSTEM` / `_check_lines`（M2 Task 16）、`_dice_payload`（M3-11）、`DicePayload` / `DiceOverlay` / `DiceLogPanel`（M3-16）、`init_db` / `migrate_schema` / `_ensure_column`（M4-1）、暗骰 `secret` 链路（M4-4：`CheckRequest.secret`、`add_dice_record(secret=)`、`_check_lines` 暗骰标注、事件 `visibility="gm"`、`_push_snapshot`/`resync_payload` 过滤）
- Produces:
  - `roll_d100_with_bonus(seed: int, bonus: int = 0, penalty: int = 0) -> int`：`net = clamp(bonus - penalty, -2, +2)`；net > 0 连掷 net+1 个 d100 取最小、net < 0 取最大；net == 0 完全等价 `roll_d100(seed)`
  - `roll_check(actor, skill, skill_value, difficulty, seed, bonus: int = 0, penalty: int = 0) -> CheckResult`；`CheckResult` 尾部新增字段 `bonus / penalty`（存**夹紧后**生效值，各 0..2）
  - `bonus_note(bonus: int, penalty: int) -> str`：`"（奖励骰 ×1，惩罚骰 ×2） "` / `""`（事件文本、提示词行共用同一格式）
  - `_resolve_plain_check(repo, state, chk) -> dict`（自 `resolve_checks` 提取，**M5-7 战斗攻击复用**）；`check_results` 条目与 `check` 事件 payload 新增 `bonus / penalty` 键
  - `CheckRequest.bonus / CheckRequest.penalty: int = 0`（越界值在 rules 层夹紧，schema 不拒绝——LLM 小错不失败整回合）
  - `migrate_schema` 追加两行 `_ensure_column`（复用 M4-1 机制，`init_db` 无需改动）：旧库 `dicerecordrow` 表补 `bonus / penalty INTEGER NOT NULL DEFAULT 0`
  - 与 M4-4 的合并口径：`add_dice_record(..., seed, secret=False, bonus=0, penalty=0)`；`_resolve_plain_check` 同时透传 `secret` 与 `bonus/penalty` 且暗骰事件 `visibility="gm"` 保持；`_check_lines` / `DECIDE_SYSTEM` 保留暗骰内容并叠加奖惩说明
  - `_dice_payload` 追加 `"bonus" / "penalty"`；前端 `DicePayload.bonus? / penalty?: number`（可选，M3 测试数据不破）
- 语义约束：LLM 只输出"要不要给奖惩、几颗"（意图参数，0-2）；骰值与成败全部由纯函数计算；无奖惩时事件文本/提示词/前端渲染与既有输出**逐字符一致**。

- [ ] **Step 1: 写失败测试（规则层）**

更新 `backend/tests/rules/test_dice.py` 首行 import 为：
```python
from app.rules.dice import new_seed, roll_d100, roll_d100_with_bonus
```
文件尾追加：
```python
def test_zero_net_matches_plain_roll():
    for s in (1, 2, 3, 99):
        assert roll_d100_with_bonus(s) == roll_d100(s)
        assert roll_d100_with_bonus(s, 2, 2) == roll_d100(s)      # net 抵销

def test_bonus_not_worse_penalty_not_better():
    for s in range(50):
        assert roll_d100_with_bonus(s, 1) <= roll_d100(s)          # 奖励取最小 ≥ 不劣于原掷
        assert roll_d100_with_bonus(s, 0, 1) >= roll_d100(s)       # 惩罚取最大 ≥ 不优于原掷

def test_net_clamped_to_two():
    for s in range(20):
        assert roll_d100_with_bonus(s, 9, 0) == roll_d100_with_bonus(s, 2, 0)
        assert roll_d100_with_bonus(s, 0, 9) == roll_d100_with_bonus(s, 0, 2)

def test_bonus_result_in_range():
    assert all(1 <= roll_d100_with_bonus(s, 2, 0) <= 100 for s in range(200))
```

更新 `backend/tests/rules/test_check.py` 首行 import 为：
```python
from app.rules.check import CheckDifficulty, SuccessLevel, bonus_note, roll_check
```
文件尾追加：
```python
def test_zero_net_keeps_plain_roll(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 42)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7)
    assert r.roll == 42 and r.bonus == 0 and r.penalty == 0

def test_net_zero_cancels_bonus_and_penalty(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 17)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7,
                   bonus=2, penalty=2)
    assert r.roll == 17 and r.bonus == 0 and r.penalty == 0

def test_bonus_delegates_and_clamps_to_two(monkeypatch):
    seen = []
    def fake(seed, bonus=0, penalty=0):
        seen.append((seed, bonus, penalty))
        return 30
    monkeypatch.setattr("app.rules.check.roll_d100_with_bonus", fake)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7, bonus=3)
    assert r.roll == 30 and r.bonus == 2 and r.penalty == 0        # 结果字段存夹紧值
    assert seen == [(7, 3, 0)]                                     # 原样透传给掷骰（内部再夹紧）

def test_penalty_net_negative(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100_with_bonus",
                        lambda seed, bonus=0, penalty=0: 88)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7,
                   bonus=1, penalty=2)
    assert r.roll == 88 and r.bonus == 0 and r.penalty == 1        # net = -1

def test_bonus_note_text():
    assert bonus_note(0, 0) == ""
    assert bonus_note(1, 0) == "（奖励骰 ×1） "
    assert bonus_note(0, 2) == "（惩罚骰 ×2） "
    assert bonus_note(1, 1) == "（奖励骰 ×1，惩罚骰 ×1） "
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/rules -q`
Expected: FAIL —— `ImportError: cannot import name 'roll_d100_with_bonus' / 'bonus_note'`（收集期报错）

- [ ] **Step 3: 实现 dice.py（文件尾追加）**

```python
def roll_d100_with_bonus(seed: int, bonus: int = 0, penalty: int = 0) -> int:
    """奖惩骰（COC 7e 惯例）：net = bonus - penalty，夹紧 ±2；net == 0 完全等价 roll_d100。

    net > 0：连掷 net+1 个 d100 取最小（有利）；net < 0：取最大（不利）。
    同一条 random.Random(seed) 流，结果完全可复现。
    """
    net = max(-2, min(2, int(bonus) - int(penalty)))
    if net == 0:
        return roll_d100(seed)
    rng = random.Random(seed)
    rolls = [rng.randint(1, 100) for _ in range(abs(net) + 1)]
    return min(rolls) if net > 0 else max(rolls)
```

- [ ] **Step 4: 实现 check.py（三处修改）**

1. import 行（M2 计划内为 `from app.rules.dice import roll_d100`）替换为：
```python
from app.rules.dice import roll_d100, roll_d100_with_bonus
```

2. `CheckResult`（frozen dataclass）尾部追加两字段：
```python
    level: SuccessLevel
    success: bool
    bonus: int = 0
    penalty: int = 0
```

3. `roll_check` 整体替换为：
```python
def roll_check(actor: str, skill: str, skill_value: int,
               difficulty: CheckDifficulty, seed: int,
               bonus: int = 0, penalty: int = 0) -> CheckResult:
    net = max(-2, min(2, int(bonus) - int(penalty)))
    if net == 0:
        roll = roll_d100(seed)              # 与既有行为完全一致（保留 monkeypatch 语义）
    else:
        roll = roll_d100_with_bonus(seed, bonus, penalty)
    level = _level_for(roll, skill_value)
    if level is SuccessLevel.CRITICAL:
        success = True
    elif level is SuccessLevel.FUMBLE:
        success = False
    else:
        success = _RANK[level] >= _REQUIRED[difficulty]
    return CheckResult(actor, skill, skill_value, difficulty, roll, seed, level, success,
                       bonus=max(net, 0), penalty=max(-net, 0))
```

4. 文件尾追加：
```python
def bonus_note(bonus: int, penalty: int) -> str:
    """展示用标注：'（奖励骰 ×1） ' / ''；事件文本、提示词行、前端文案同构。"""
    parts = []
    if bonus:
        parts.append(f"奖励骰 ×{bonus}")
    if penalty:
        parts.append(f"惩罚骰 ×{penalty}")
    return f"（{'，'.join(parts)}） " if parts else ""
```

- [ ] **Step 5: 验证规则层通过**

Run: `cd backend; uv run pytest tests/rules -q`
Expected: PASS —— test_dice.py 8 passed（4 既有 + 4 新增）、test_check.py 10 passed（5 既有 + 5 新增）；既有 monkeypatch 断言零改动仍全绿

- [ ] **Step 6: 写失败测试（存储迁移 + 检定节点）**

`backend/tests/storage/test_migration.py`（M4-1 已建、M4-4 已追加 1 例）：import 区追加
```python
from app.storage.repo import SqliteRepository
```
文件末尾追加（沿用 M4 的 sqlite3 直连建旧表风格；旧表不含 M4 的 `secret` 列，只断言 bonus/penalty 补齐）：
```python
def test_init_db_backfills_bonus_penalty_on_legacy_table(tmp_path):
    db = tmp_path / "legacy_bonus.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE dicerecordrow ("
        "id INTEGER NOT NULL PRIMARY KEY, campaign_id VARCHAR NOT NULL,"
        "branch_id VARCHAR NOT NULL, turn_id INTEGER NOT NULL, actor VARCHAR NOT NULL,"
        "skill VARCHAR NOT NULL, skill_value INTEGER NOT NULL,"
        "difficulty VARCHAR NOT NULL, roll INTEGER NOT NULL, level VARCHAR NOT NULL,"
        "seed INTEGER NOT NULL, created_at DATETIME NOT NULL)")
    conn.execute("INSERT INTO dicerecordrow VALUES "
                 "(1, 'c1', 'c1@main', 1, 'pc_1', '侦查', 50, 'regular', 30, 'regular',"
                 " 1, '2026-01-01 00:00:00')")
    conn.commit()
    conn.close()

    engine = make_engine(str(db))
    init_db(engine)

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(dicerecordrow)")}
    assert {"bonus", "penalty"} <= cols
    repo = SqliteRepository(engine)
    old = repo.list_dice_records("c1", "c1@main")
    assert old[0].bonus == 0 and old[0].penalty == 0          # 旧数据补默认 0
    repo.add_dice_record("c1", "c1@main", 2, "pc_1", "潜行", 40, "regular", 20,
                         "hard", 9, bonus=1, penalty=0)
    assert repo.list_dice_records("c1", "c1@main")[1].bonus == 1


def test_init_db_is_idempotent_on_fresh_engine(tmp_path):
    engine = make_engine(str(tmp_path / "fresh_bonus.db"))
    init_db(engine)
    init_db(engine)                                           # 二次调用幂等
    repo = SqliteRepository(engine)
    repo.add_dice_record("c1", "c1@main", 1, "pc_1", "侦查", 50, "regular", 30,
                         "regular", 1, bonus=0, penalty=2)
    assert repo.list_dice_records("c1", "c1@main")[0].penalty == 2
```

追加 `backend/tests/graph/test_resolve_checks.py`（import 区加 `import json`；文件尾追加）：
```python
def test_bonus_penalty_recorded_and_annotated(node, repo, campaign):
    upd = node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular",
         "bonus": 1, "penalty": 0}]}))
    row = upd["check_results"][0]
    assert row["bonus"] == 1 and row["penalty"] == 0
    rec = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)[-1]
    assert rec.bonus == 1 and rec.penalty == 0
    ev = repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])[-1]
    assert "奖励骰 ×1" in json.loads(ev.payload_json)["text"]


def test_bonus_clamped_to_two(node, repo, campaign):
    upd = node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular",
         "bonus": 9, "penalty": 0}]}))
    assert upd["check_results"][0]["bonus"] == 2
```

- [ ] **Step 7: 验证失败**

Run: `cd backend; uv run pytest tests/storage/test_migration.py tests/graph/test_resolve_checks.py -q`
Expected: FAIL —— `TypeError: add_dice_record() got an unexpected keyword argument 'bonus'`；resolve_checks 两条新用例 `KeyError: 'bonus'`

- [ ] **Step 8: 实现存储层（models / db / repo）**

1. `backend/app/storage/models.py`：`DiceRecordRow` 的 `secret` 行之后、`created_at` 之前追加两行（M4-4 已插入 `secret` 行，勿丢）：
```python
    seed: int
    secret: bool = False          # 暗骰：L2 保留，但不对玩家可见
    bonus: int = 0
    penalty: int = 0
    created_at: datetime = Field(default_factory=_now)
```

2. `backend/app/storage/db.py`：`migrate_schema` 清单尾部追加两行（复用 M4-1 的 `_ensure_column`；`init_db` 已是 `create_all + migrate_schema`，无需改动）：
```python
def migrate_schema(engine) -> None:
    """轻量迁移清单：每列一行，幂等可重复执行。"""
    with engine.begin() as conn:
        _ensure_column(conn, "campaign", "invite_code",
                       "invite_code VARCHAR NOT NULL DEFAULT ''")
        _ensure_column(conn, "dicerecordrow", "secret",
                       "secret BOOLEAN NOT NULL DEFAULT 0")
        _ensure_column(conn, "dicerecordrow", "bonus",
                       "bonus INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "dicerecordrow", "penalty",
                       "penalty INTEGER NOT NULL DEFAULT 0")
```

3. `backend/app/storage/repo.py`：`add_dice_record` 整体替换（保留 M4-4 的 `secret` 参数，签名尾部再加 `bonus / penalty`；insert 补两字段）：
```python
    def add_dice_record(self, campaign_id: str, branch_id: str, turn_id: int, actor: str,
                        skill: str, skill_value: int, difficulty: str, roll: int,
                        level: str, seed: int, secret: bool = False,
                        bonus: int = 0, penalty: int = 0) -> None:
        with Session(self.engine) as s:
            s.add(DiceRecordRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                                actor=actor, skill=skill, skill_value=skill_value,
                                difficulty=difficulty, roll=roll, level=level, seed=seed,
                                secret=secret, bonus=bonus, penalty=penalty))
            s.commit()
```

- [ ] **Step 9: 实现图节点层（schemas / turn / gm）**

1. `backend/app/graph/schemas.py`：`CheckRequest` 整体替换（保留 M4-4 的 `secret` 字段）：
```python
class CheckRequest(BaseModel):
    actor: str
    skill: str
    difficulty: CheckDifficulty = CheckDifficulty.REGULAR
    secret: bool = False          # true=暗骰：玩家角色无从察觉，叙事不得直接暴露
    bonus: int = 0      # 奖励骰数（意图参数；越界由 rules 层夹紧 ±2，不在此拒绝）
    penalty: int = 0    # 惩罚骰数
```

2. `backend/app/graph/nodes/turn.py` 两处修改：
   - import 行（M2 计划内为 `from app.rules.check import CheckDifficulty, roll_check`）替换为：
```python
from app.rules.check import CheckDifficulty, bonus_note, roll_check
```
   - `build_resolve_checks_node` 整体替换为（基于 M4-4 的 secret 版提取 `_resolve_plain_check`，供 M5-7 战斗复用；secret 透传、事件可见性、payload `secret` 键原样保留）：
```python
def _resolve_plain_check(repo, state: GameState, chk: dict) -> dict:
    """单条普通检定（M5-4 自 resolve_checks 提取）：掷骰 → DiceRecord → check 事件 → 结果行。"""
    campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
    actor, skill = chk["actor"], chk["skill"]
    secret = bool(chk.get("secret"))
    skill_value = _skill_value(state, actor, skill)
    seed = new_seed()
    r = roll_check(actor, skill, skill_value,
                   CheckDifficulty(chk.get("difficulty", "regular")), seed,
                   bonus=int(chk.get("bonus", 0)), penalty=int(chk.get("penalty", 0)))
    repo.add_dice_record(campaign_id, branch_id, turn_id, r.actor, r.skill, r.skill_value,
                         str(r.difficulty), r.roll, str(r.level), r.seed,
                         secret=secret, bonus=r.bonus, penalty=r.penalty)
    verdict = "成功" if r.success else "失败"
    note = bonus_note(r.bonus, r.penalty)
    repo.add_event(campaign_id, branch_id, turn_id, type="check",
                   payload={"text": f"{actor} 的「{skill}」检定：{r.roll}/{r.skill_value} "
                                    f"{note}→ {r.level}（{verdict}）",
                            "roll": r.roll, "level": str(r.level), "success": r.success,
                            "secret": secret, "bonus": r.bonus, "penalty": r.penalty},
                   visibility="gm" if secret else "all")
    return {"actor": r.actor, "skill": r.skill, "roll": r.roll,
            "skill_value": r.skill_value, "level": str(r.level),
            "success": r.success, "seed": r.seed, "secret": secret,
            "bonus": r.bonus, "penalty": r.penalty}


def build_resolve_checks_node(repo):
    def resolve_checks(state: GameState) -> dict:
        checks = (state.get("decision") or {}).get("checks", [])
        return {"check_results": [_resolve_plain_check(repo, state, chk) for chk in checks]}

    return resolve_checks
```

3. `backend/app/graph/nodes/gm.py` 三处修改：
   - import 区（`from app.llm.client import ...` 行之后）追加：
```python
from app.rules.check import bonus_note
```
   - `DECIDE_SYSTEM` 整体替换（在 M4-4 的 secret 版基础上叠加 bonus/penalty；M3-4 的 `clues_revealed/ending_reached` 两行保留在 `memory_queries` 之前，勿丢）：
```python
DECIDE_SYSTEM = (
    "你是跑团主持人（COC 风格）。基于玩家行动与当前场景做结构化裁决，只输出一个 JSON 对象，字段：\n"
    'intent_summary(str)、checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme),'
    '"secret"(bool，可选，默认 false),"bonus"(0-2，可选),"penalty"(0-2，可选)})、'
    'proactive_npc_triggers(数组，元素 {"npc_id","trigger"})、'
    'scene_transition(null 或 {"to_scene","reason"})、'
    'clues_revealed(数组，元素为线索 id，仅当本回合玩家明确获得线索时填写)、'
    'ending_reached(null 或模块给定结局 id，仅当叙事故意收束到结局时填写)、'
    'memory_queries(字符串数组)。\n'
    "规则：只为玩家的主动行动要求检定，每回合最多 2 个检定；NPC 只能用场景内列出的；"
    "奖励/惩罚骰仅在情境明显有利/不利时给出（如充分准备、恶劣环境），每项最多 2，默认省略；"
    "开场回合可以引入场面但不要要求检定；"
    "secret=true 表示玩家角色无从察觉的暗骰（如暗中进行的观察或聆听），其检定与结果不得在叙事中直接暴露。"
)
```
   - `_check_lines` 整体替换（无奖惩且非暗骰时输出与既有逐字符一致；暗骰标注来自 M4-4，勿丢）：
```python
def _check_lines(state: GameState) -> str:
    lines = []
    for c in state.get("check_results", []):
        verdict = "成功" if c.get("success") else "失败"
        dice_note = bonus_note(int(c.get("bonus", 0)), int(c.get("penalty", 0)))
        secret_note = ("（暗骰：不得在叙事中直接暴露该检定与结果，只可化为隐约的线索或不安感）"
                       if c.get("secret") else "")
        lines.append(f"- {c['actor']} 的「{c['skill']}」：{c['roll']}/{c['skill_value']} "
                     f"{dice_note}→ {c['level']}（{verdict}）{secret_note}")
    return "\n".join(lines) or "（本回合无检定）"
```

- [ ] **Step 10: 验证存储与节点层通过**

Run: `cd backend; uv run pytest tests/storage tests/graph -q`
Expected: PASS —— 迁移 5 例（3 既有 + 2 新增）、resolve_checks 7 例（5 既有 + 2 新增）；check_results 与事件 payload 新增键向后兼容，其余 graph/storage 全绿

- [ ] **Step 11: 实现 API 与前端（session / types / DiceOverlay / DiceLogPanel / styles）**

1. `backend/app/api/session.py`：`_dice_payload` 整体替换（新增两键；`_SUCCESS_LEVELS` 等其余不动）：
```python
def _dice_payload(row) -> dict:
    return {"actor": row.actor, "skill": row.skill, "skill_value": row.skill_value,
            "difficulty": row.difficulty, "roll": row.roll, "level": row.level,
            "seed": row.seed, "success": row.level in _SUCCESS_LEVELS,
            "bonus": row.bonus, "penalty": row.penalty}
```

2. `frontend/src/types.ts`：`DicePayload` 整体替换：
```ts
export type DicePayload = {
  actor: string; skill: string; skill_value: number; difficulty: string;
  roll: number; level: string; seed: number; success: boolean;
  bonus?: number; penalty?: number;
};
```

3. `frontend/src/components/DiceOverlay.tsx`：`dice-level` 一行后插入奖惩标注（其余 JSX 不动）：
```tsx
        <div className="dice-level">{LEVEL_LABEL[dice.level] ?? dice.level}</div>
        {(dice.bonus || dice.penalty) ? (
          <div className="dice-note">
            {dice.bonus ? `奖励骰 ×${dice.bonus}` : ""}
            {dice.bonus && dice.penalty ? "，" : ""}
            {dice.penalty ? `惩罚骰 ×${dice.penalty}` : ""}
          </div>
        ) : null}
```

4. `frontend/src/components/DiceLogPanel.tsx`：`<li>` 渲染替换为：
```tsx
              <li key={i} className={d.success ? "ok" : "bad"}>
                {d.skill} d100={d.roll} · {d.level}
                {d.bonus ? ` · 奖励骰×${d.bonus}` : ""}
                {d.penalty ? ` · 惩罚骰×${d.penalty}` : ""}
              </li>
```

5. `frontend/src/styles.css`：在 `.dice-level { margin-top: 6px; }` 规则之后追加：
```css
.dice-note { margin-top: 4px; font-size: 13px; color: #9aa7b8; }
```

6. 追加 `frontend/src/components/__tests__/DiceOverlay.test.tsx`（既有 `describe` 块内、最后一个 `it` 之后）：
```tsx
  it("annotates bonus and penalty dice", () => {
    vi.useFakeTimers();
    render(<DiceOverlay dice={{ ...DICE, bonus: 1, penalty: 2 }} onDone={() => {}} />);
    vi.advanceTimersByTime(2000);
    expect(screen.getByText(/奖励骰 ×1/)).toBeInTheDocument();
    expect(screen.getByText(/惩罚骰 ×2/)).toBeInTheDocument();
  });
```

- [ ] **Step 12: 验证前端与 API 层**

Run: `cd frontend; npm run test`
Expected: PASS —— DiceOverlay 3 例（2 既有 + 1 新增）+ 其余前端测试全绿

Run: `cd backend; uv run pytest tests/api -q`
Expected: PASS —— `_dice_payload` 新增键不破坏既有 REST/WS 断言（类型一致性抽查：`DiceRecordRow` ↔ `_dice_payload` ↔ 前端 `DicePayload` 三处字段名与可选性一致）

- [ ] **Step 13: 全量回归**

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 全量绿；奖惩骰为既有 checks 管道的纯扩展，无奖惩路径行为逐字符不变

- [ ] **Step 14: Commit**

```bash
git add backend/app/rules/dice.py backend/app/rules/check.py backend/app/storage/models.py backend/app/storage/db.py backend/app/storage/repo.py backend/app/graph/schemas.py backend/app/graph/nodes/turn.py backend/app/graph/nodes/gm.py backend/app/api/session.py backend/tests/rules/test_dice.py backend/tests/rules/test_check.py backend/tests/storage/test_migration.py backend/tests/graph/test_resolve_checks.py frontend/src/types.ts frontend/src/components/DiceOverlay.tsx frontend/src/components/DiceLogPanel.tsx frontend/src/styles.css frontend/src/components/__tests__/DiceOverlay.test.tsx
git commit -m "feat(rules): COC-style bonus/penalty dice across rules, GM, storage and web UI"
```

---

### Task M5-5: 成本面板（usage API + CostPanel）

**Files:**
- Modify: `backend/app/storage/repo.py`、`backend/app/api/routes.py`、`frontend/src/types.ts`、`frontend/src/api/rest.ts`、`frontend/src/views/Room.tsx`、`frontend/src/styles.css`
- Create: `backend/tests/api/test_usage_api.py`、`frontend/src/components/CostPanel.tsx`、`frontend/src/components/__tests__/CostPanel.test.tsx`
- Test: 追加 `frontend/src/views/__tests__/Room.test.tsx`（rest mock 增 `usage`）

**Interfaces:**
- Consumes: `UsageRow` / `record_usage` / `get_campaign`（M2 Task 9）、`usage_totals`（M5-3）、`_deps` / `router` / `HTTPException`（M3-6）、`api` 客户端与 `client` fixture（M3-12）、`Room` 侧栏（M3-15/16）
- Produces:
  - `SqliteRepository.usage_rows(campaign_id: str, limit: int = 50) -> list[UsageRow]`（按 id 倒序，最近在前）
  - `GET /api/campaigns/{id}/usage` → `{"totals": {calls,tokens_in,tokens_out,cost_usd}, "cap_usd": float, "recent": [{turn_id,role,model,tokens_in,tokens_out,cost_usd,created_at}]}`；未知战役 404
  - 前端 `UsageSummary` 类型；`api.usage(id)`；`CostPanel({ campaignId })`（拉取失败静默隐藏，不阻塞房间）

- [ ] **Step 1: 写失败测试（后端）**

新建 `backend/tests/api/test_usage_api.py`（复用既有 `client` fixture，返回 `(TestClient, repo)`）：
```python
def test_usage_endpoint_aggregates_and_lists_recent(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "记账"}).json()["campaign_id"]
    branch = repo.get_campaign(cid).active_branch_id
    repo.record_usage(cid, branch, 1, "gm", "qwen-plus", 100, 50, 0.0004, 120)
    repo.record_usage(cid, branch, 2, "npc", "qwen-turbo", 80, 40, 0.0001, 90)
    d = c.get(f"/api/campaigns/{cid}/usage").json()
    assert d["totals"]["calls"] == 2
    assert d["totals"]["tokens_in"] == 180 and d["totals"]["tokens_out"] == 90
    assert abs(d["totals"]["cost_usd"] - 0.0005) < 1e-9
    assert d["cap_usd"] > 0
    assert [r["role"] for r in d["recent"]] == ["npc", "gm"]        # 最近在前
    assert d["recent"][0]["turn_id"] == 2 and d["recent"][0]["model"] == "qwen-turbo"


def test_usage_endpoint_404_for_unknown_campaign(client):
    c, _ = client
    assert c.get("/api/campaigns/none/usage").status_code == 404
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_usage_api.py -q`
Expected: FAIL —— 路由不存在（响应 `{"detail":"Not Found"}` → `KeyError: 'totals'`）

- [ ] **Step 3: 实现（repo + route）**

1. `backend/app/storage/repo.py`：在 `usage_totals` 之后追加：
```python
    def usage_rows(self, campaign_id: str, limit: int = 50) -> list[UsageRow]:
        q = (select(UsageRow).where(UsageRow.campaign_id == campaign_id)
             .order_by(UsageRow.id.desc()).limit(limit))
        with Session(self.engine) as s:
            return list(s.exec(q).all())
```

2. `backend/app/api/routes.py`：追加端点（紧跟 `/campaigns/{campaign_id}/module` 之后）：
```python
@router.get("/campaigns/{campaign_id}/usage")
def campaign_usage(campaign_id: str, request: Request):
    deps = _deps(request)
    try:
        deps.repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    rows = deps.repo.usage_rows(campaign_id)
    return {"totals": deps.repo.usage_totals(campaign_id),
            "cap_usd": deps.settings.campaign_cost_cap_usd,
            "recent": [{"turn_id": r.turn_id, "role": r.role, "model": r.model,
                        "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                        "cost_usd": r.cost_usd,
                        "created_at": r.created_at.isoformat()} for r in rows]}
```

- [ ] **Step 4: 验证后端通过（含回归）**

Run: `cd backend; uv run pytest tests/api -q`
Expected: PASS —— 新 2 例 + 既有 API 用例全绿

- [ ] **Step 5: 写失败测试（前端）**

新建 `frontend/src/components/__tests__/CostPanel.test.tsx`：
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CostPanel from "../CostPanel";

vi.mock("../../api/rest", () => ({
  api: {
    usage: vi.fn().mockResolvedValue({
      totals: { calls: 2, tokens_in: 180, tokens_out: 90, cost_usd: 0.0005 },
      cap_usd: 1.0,
      recent: [{ turn_id: 1, role: "gm", model: "qwen-plus",
                 tokens_in: 100, tokens_out: 50, cost_usd: 0.0004,
                 created_at: "2026-01-01T00:00:00" }],
    }),
  },
}));

describe("CostPanel", () => {
  it("renders totals against the cap and recent rows", async () => {
    render(<CostPanel campaignId="c1" />);
    expect(await screen.findByText(/\$0\.0005 \/ \$1\.00/)).toBeInTheDocument();
    expect(await screen.findByText(/gm · qwen-plus/)).toBeInTheDocument();
  });
});
```

`frontend/src/views/__tests__/Room.test.tsx`：`vi.mock("../../api/rest", ...)` 工厂内 `api` 对象补齐 `usage`（否则 Room 挂载 CostPanel 后既有用例 `api.usage is not a function`）：
```tsx
vi.mock("../../api/rest", () => ({
  api: {
    module: vi.fn().mockResolvedValue({
      id: "misty_hollow", title: "迷雾幽谷",
      npcs: [{ id: "elder", name: "村长" }], endings: [],
    }),
    usage: vi.fn().mockResolvedValue({
      totals: { calls: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0 },
      cap_usd: 1.0, recent: [],
    }),
  },
}));
```

- [ ] **Step 6: 验证失败**

Run: `cd frontend; npm run test`
Expected: FAIL —— `Failed to resolve import "../CostPanel"`

- [ ] **Step 7: 实现前端**

1. `frontend/src/types.ts` 追加：
```ts
export type UsageSummary = {
  totals: { calls: number; tokens_in: number; tokens_out: number; cost_usd: number };
  cap_usd: number;
  recent: {
    turn_id: number; role: string; model: string;
    tokens_in: number; tokens_out: number; cost_usd: number; created_at: string;
  }[];
};
```

2. `frontend/src/api/rest.ts`：import type 列表加入 `UsageSummary`（字母序：`ModuleInfo` 与 `Timeline` 之间）；`api` 对象追加：
```ts
  usage: (id: string) => jsonFetch<UsageSummary>(`/api/campaigns/${id}/usage`),
```

3. 新建 `frontend/src/components/CostPanel.tsx`：
```tsx
import { useEffect, useState } from "react";

import { api } from "../api/rest";
import type { UsageSummary } from "../types";

export default function CostPanel({ campaignId }: { campaignId: string }) {
  const [usage, setUsage] = useState<UsageSummary | null>(null);

  useEffect(() => {
    let alive = true;
    api.usage(campaignId)
      .then((d) => { if (alive) setUsage(d); })
      .catch(() => {});                       // 拉取失败静默隐藏，不阻塞房间
    return () => { alive = false; };
  }, [campaignId]);

  if (!usage) return null;
  const pct = usage.cap_usd > 0
    ? Math.min(100, Math.round((usage.totals.cost_usd / usage.cap_usd) * 100))
    : 0;
  return (
    <section className="panel">
      <h3>成本</h3>
      <p className="muted">
        ${usage.totals.cost_usd.toFixed(4)} / ${usage.cap_usd.toFixed(2)}（{pct}%）
      </p>
      <div className="cost-bar"><span style={{ width: `${pct}%` }} /></div>
      <ul>
        {usage.recent.slice(0, 5).map((r, i) => (
          <li key={i}>{r.role} · {r.model} · ${r.cost_usd.toFixed(4)}</li>
        ))}
      </ul>
    </section>
  );
}
```

4. `frontend/src/views/Room.tsx`：import 区追加 `import CostPanel from "../components/CostPanel";`（按字母序，`CharacterPanel` 之后）；`aside.room-side` 内 `<DiceLogPanel ... />` 之后追加：
```tsx
          <CostPanel campaignId={session.campaignId} />
```

5. `frontend/src/styles.css` 追加（panel 样式区）：
```css
.cost-bar { height: 6px; margin: 6px 0; background: #2a3140; border-radius: 3px; overflow: hidden; }
.cost-bar span { display: block; height: 100%; background: #8fd18f; }
```

- [ ] **Step 8: 验证通过 + Commit**

Run: `cd frontend; npm run test`
Expected: PASS —— CostPanel 1 例 + Room 2 例（mock 更新后）+ 全量前端测试

```bash
git add backend/app/storage/repo.py backend/app/api/routes.py backend/tests/api/test_usage_api.py frontend/src/types.ts frontend/src/api/rest.ts frontend/src/components/CostPanel.tsx frontend/src/components/__tests__/CostPanel.test.tsx frontend/src/views/Room.tsx frontend/src/views/__tests__/Room.test.tsx frontend/src/styles.css
git commit -m "feat(api): per-campaign usage endpoint with cost panel in room sidebar"
```

---

### Task M5-6: 战斗规则与内容模型（纯函数 + NpcDef.combat）

**Files:**
- Create: `backend/app/rules/combat.py`、`backend/tests/rules/test_combat.py`
- Modify: `backend/app/content/schema.py`、`modules/misty_hollow.yaml`（仓库根；`whisperer` 补 `combat` 块）、`backend/tests/content/test_schema.py`

**Interfaces:**
- Consumes: `CheckDifficulty` / `CheckResult` / `roll_check`（M2 Task 3，M5-4 已支持奖惩骰）、`NpcDef`（M2 Task 4）
- Produces:
  - `parse_damage_dice(dice: str) -> tuple[int, int, int]`：`"1d6"` / `"2d4+1"` → `(n, sides, bonus)`；非法表达式 `ValueError`
  - `roll_damage(seed: int, dice: str) -> int`：确定性伤害骰
  - `CombatOutcome(attack: CheckResult, defense: CheckResult, hit: bool, damage: int)`（frozen dataclass）
  - `resolve_attack(actor, skill, attack_value, defender, defense_value, damage_dice, seed, difficulty=REGULAR, bonus=0, penalty=0) -> CombatOutcome`：攻击检定（支持奖惩骰）→ NPC 闪避检定 → `hit = 攻击成功且防御失败` → 命中才掷伤害（单一 seed 派生三条子流，完全可复现）
  - `NpcCombat(defense=40, damage="1d4", hp=8)`；`NpcDef.combat: NpcCombat | None = None`（缺省不可被攻击；damage 用 `parse_damage_dice` 校验）
- 边界（规格 §14）：单次结算；无先攻/轮循环/NPC 反击/武器表；攻击者=玩家角色，目标=当前场景 NPC（M5-7 接入）。

- [ ] **Step 1: 写失败测试（规则层）**

新建 `backend/tests/rules/test_combat.py`：
```python
import pytest

from app.rules.combat import parse_damage_dice, resolve_attack, roll_damage


def test_parse_damage_dice_forms():
    assert parse_damage_dice("1d6") == (1, 6, 0)
    assert parse_damage_dice("2d4+1") == (2, 4, 1)
    assert parse_damage_dice("d8") == (1, 8, 0)              # N 可省略


@pytest.mark.parametrize("bad", ["", "1d", "abc", "1d6-2", "3x6"])
def test_parse_damage_dice_rejects(bad):
    with pytest.raises(ValueError):
        parse_damage_dice(bad)


def test_roll_damage_deterministic_and_in_range():
    for s in range(50):
        assert roll_damage(s, "1d6") == roll_damage(s, "1d6")
        assert 1 <= roll_damage(s, "1d6") <= 6
        assert 3 <= roll_damage(s, "2d4+1") <= 9


def test_resolve_attack_reproducible():
    a = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", 42)
    b = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", 42)
    assert a == b


def test_hit_iff_attack_succeeds_and_defense_fails():
    for s in range(300):
        o = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", s)
        assert o.hit == (o.attack.success and not o.defense.success)
        if not o.hit:
            assert o.damage == 0


def test_damage_range_when_hit():
    hits = [o for o in (resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", s)
                        for s in range(300)) if o.hit]
    assert hits and all(1 <= o.damage <= 6 for o in hits)


def test_bonus_passed_to_attack_check():
    o = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", 123, bonus=2)
    assert o.attack.bonus == 2 and o.attack.penalty == 0
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/rules/test_combat.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.rules.combat'`

- [ ] **Step 3: 实现 combat.py**

`backend/app/rules/combat.py`：
```python
"""轻量战斗结算（规格 §14：单次攻击对单 NPC；无先攻/轮循环/NPC 反击）。"""
import random
import re
from dataclasses import dataclass

from app.rules.check import CheckDifficulty, CheckResult, roll_check

DICE_EXPR_RE = re.compile(r"^(\d*)d(\d+)(?:\+(\d+))?$")


def parse_damage_dice(dice: str) -> tuple[int, int, int]:
    """'1d6' / '2d4+1' → (n, sides, bonus)；非法表达式抛 ValueError。"""
    m = DICE_EXPR_RE.match(dice.strip())
    if not m:
        raise ValueError(f"bad damage dice expression: {dice!r}")
    return int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0)


def roll_damage(seed: int, dice: str) -> int:
    n, sides, bonus = parse_damage_dice(dice)
    rng = random.Random(seed)
    return sum(rng.randint(1, sides) for _ in range(n)) + bonus


@dataclass(frozen=True)
class CombatOutcome:
    attack: CheckResult      # 攻击检定（支持奖惩骰，M5-4）
    defense: CheckResult     # 防御检定（NPC 闪避）
    hit: bool                # 命中 = 攻击成功且防御失败
    damage: int              # 命中伤害；未命中恒为 0


def resolve_attack(actor: str, skill: str, attack_value: int,
                   defender: str, defense_value: int, damage_dice: str,
                   seed: int, difficulty: CheckDifficulty = CheckDifficulty.REGULAR,
                   bonus: int = 0, penalty: int = 0) -> CombatOutcome:
    rng = random.Random(seed)          # 单一 seed 派生三条子流：可复现且互不干扰
    attack = roll_check(actor, skill, attack_value, difficulty, rng.randbits(64),
                        bonus=bonus, penalty=penalty)
    defense = roll_check(defender, "闪避", defense_value, CheckDifficulty.REGULAR,
                         rng.randbits(64))
    hit = attack.success and not defense.success
    damage = roll_damage(rng.randbits(64), damage_dice) if hit else 0
    return CombatOutcome(attack=attack, defense=defense, hit=hit, damage=damage)
```

- [ ] **Step 4: 验证规则层通过**

Run: `cd backend; uv run pytest tests/rules -q`
Expected: PASS —— test_combat.py 11 例全绿（含 5 个参数化非法表达式）+ 其余 rules 回归

- [ ] **Step 5: 写失败测试（内容模型）**

`backend/tests/content/test_schema.py`：import 区更新为（isort 顺序）：
```python
import pytest
from copy import deepcopy

from pydantic import ValidationError

from app.content.schema import Module
```
文件尾追加：
```python
def test_npc_combat_optional_and_parsed():
    m = Module.model_validate(MINIMAL)
    assert m.npc("guard").combat is None                     # 无战斗块：不可被攻击
    data = deepcopy(MINIMAL)
    data["npcs"][0]["combat"] = {"defense": 45, "damage": "1d6", "hp": 12}
    m2 = Module.model_validate(data)
    assert m2.npc("guard").combat.hp == 12
    assert m2.npc("guard").combat.defense == 45


def test_npc_combat_rejects_bad_damage_expression():
    data = deepcopy(MINIMAL)
    data["npcs"][0]["combat"] = {"damage": "1d6-2"}
    with pytest.raises(ValidationError):
        Module.model_validate(data)
```
（`import pytest` 与 `from copy import deepcopy` 的顺序以上面为准；仓内既有风格是 `import pytest` 在前。）

- [ ] **Step 6: 验证失败**

Run: `cd backend; uv run pytest tests/content/test_schema.py -q`
Expected: FAIL —— `AttributeError: 'NpcDef' object has no attribute 'combat'`

- [ ] **Step 7: 实现内容模型 + 示例模组**

1. `backend/app/content/schema.py`：
   - import 区替换为：
```python
from pydantic import BaseModel, Field, field_validator

from app.rules.combat import parse_damage_dice
```
   - 在 `NpcDef` 之前插入：
```python
class NpcCombat(BaseModel):
    defense: int = Field(default=40, ge=1, le=100)   # 防御（闪避）技能值
    damage: str = "1d4"                              # 伤害骰表达式（NdM+K）
    hp: int = Field(default=8, ge=1)

    @field_validator("damage")
    @classmethod
    def _damage_must_parse(cls, v: str) -> str:
        parse_damage_dice(v)
        return v
```
   - `NpcDef` 尾部追加字段：
```python
    initial_attitude: int = 50
    combat: NpcCombat | None = None      # 存在即可被攻击（M5-7）；缺省 NPC 不可被攻击
```

2. `modules/misty_hollow.yaml`（仓库根）：`whisperer` 的 `initial_attitude: 50` 行后追加（同级缩进）：
```yaml
    combat:
      defense: 45
      damage: "1d6"
      hp: 12
```

- [ ] **Step 8: 验证通过（含全量回归）**

Run: `cd backend; uv run pytest tests/content tests/rules -q`
Expected: PASS —— test_schema 5 例（3 既有 + 2 新增）+ rules 全绿

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 全量绿；`test_replay_smoke` 仍通过（模组仅追加可选字段，回放基线不受影响）

- [ ] **Step 9: Commit**

```bash
git add backend/app/rules/combat.py backend/tests/rules/test_combat.py backend/app/content/schema.py backend/tests/content/test_schema.py modules/misty_hollow.yaml
git commit -m "feat(rules): lightweight combat resolution and npc combat stats in content schema"
```

---

### Task M5-7: 战斗结算接入主图（combat_resolve 节点 + target 路由 + HP 快照）

**Files:**
- Modify: `backend/app/graph/state.py`（`npc_hp` / `combat_log` 两字段）
- Modify: `backend/app/graph/schemas.py`（`CheckRequest.target`）
- Modify: `backend/app/graph/nodes/turn.py`（intake 装载 npc_hp / wait_input、fallback 清空两键 / resolve_checks 过滤 target / post_turn 快照加 npc_hp / 新增 `_combat_roll_row` + `build_combat_resolve_node`）
- Modify: `backend/app/graph/nodes/gm.py`（validate 增加 `_normalize_targets` / 新增 `_combat_lines` / narrate 提示词条件插入战斗块 / `DECIDE_SYSTEM` 加 target 说明）
- Modify: `backend/app/graph/main.py`（import、`_route_after_validate` 三分支、新增 `_route_after_combat`、装配 `combat_resolve` 节点与边）
- Test: `backend/tests/graph/test_combat.py`（新建）、`backend/tests/graph/test_endings.py`（追加 1 例）

**Interfaces:**
- Consumes: `resolve_attack / CombatOutcome`（M5-6）、`_resolve_plain_check`（M5-4）、`bonus_note`（M5-4）、`build_validate_node(client, module)` 循环版（M3-4）、`_guarded` / `_skill_value` / `new_seed` / `add_dice_record(..., secret=False, bonus=0, penalty=0)`（M2 / M4-4 / M5-4）、`get_counters().record_fallback`（M5-3）
- Produces：
  - `GameState.npc_hp: dict[str, int]`（intake 从 L2 快照重建，缺省 = 各 NPC 的 `combat.hp`）；`GameState.combat_log: list[dict]`（本回合战斗记录）
  - `CheckRequest.target: str | None = None`
  - `build_combat_resolve_node(repo, module) -> Callable[[GameState], dict]`：返回 `{"combat_log": [...], "npc_hp": {...}}`；记录条目固定形状 `{npc_id, name, hit, damage, hp_before, hp_after, attack, defense}`，attack/defense 为掷骰行形状 `{actor, skill, roll, skill_value, level, success, bonus, penalty}`
  - `_combat_lines(state) -> str`（gm.py；无记录时返回 `""`）
  - `_route_after_validate`：`error→fallback / 任何 check 带 target→combat_resolve / 否则→resolve_checks`；`_route_after_combat`：`error→fallback / 否则→resolve_checks`
  - `post_turn` 快照新增 `npc_hp`（L2 持久化；重开/重连由 intake 装载）
- 语义边界（规格 §14，YAGNI）：
  - 败亡 = HP 归零：0 HP 的 NPC 不可再被攻击（validate 降级为普通检定 + combat_resolve 防御性跳过）；无独立败亡字段、无战败流程、无先攻/轮循环/NPC 反击
  - target 校验为**静默降级**（非法/场景外/无 combat/已败亡 → 移除 target，检定保留为普通检定），不触发 repair
  - `combat` 事件仅落 L2（不在 WS 推送白名单，玩家经 dice 行 + 叙事感知；与 M4 的 gm-only 事件同策略）
  - 无 target 时全链路行为与 M5-6 之前逐字符/逐分支一致（提示词不出现"战斗结算"）

- [ ] **Step 1: 写失败测试（test_combat.py 新建 + test_endings.py 追加）**

`backend/tests/graph/test_combat.py`：
```python
import json

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.content.schema import Module
from app.graph.main import build_game_graph
from app.graph.nodes.gm import build_narrate_node, build_validate_node
from app.graph.nodes.turn import build_combat_resolve_node, build_resolve_checks_node
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.check import CheckDifficulty, CheckResult, SuccessLevel
from app.rules.combat import CombatOutcome

MODULE_WITH_COMBAT = {
    "meta": {"id": "combat_mod", "title": "战斗模组"},
    "opening": {"narration": "开场叙述", "scene_id": "yard"},
    "scenes": [{"id": "yard", "name": "后院", "npcs": ["thug", "kid"], "exits": []}],
    "npcs": [
        {"id": "thug", "name": "流氓", "persona": "凶悍的打手", "initial_attitude": 30,
         "combat": {"defense": 40, "damage": "1d4", "hp": 8}},
        {"id": "kid", "name": "小孩", "persona": "好奇的孩子", "initial_attitude": 60},
    ],
    "clues": [],
    "endings": [],
}


def make_client(script):
    settings = Settings()
    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    built: dict = {}

    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script))
        return built[model]

    return LLMClient(settings, pricing, model_factory=factory), built


def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "scene_id": "yard", "is_opening": False,
            "characters": {"pc_1": {"id": "pc_1", "skills": {"格斗": 70, "侦查": 50}}},
            "npc_hp": {},
            "player_inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我挥拳打过去"}],
            "check_results": [], "npc_reactions": {}, "memory_context": "",
            "budget_level": "ok", "decision": {"checks": []}, **extra}


def fake_outcome(hit=True, damage=4):
    attack = CheckResult("pc_1", "格斗", 70, CheckDifficulty.REGULAR, 22, 777,
                         SuccessLevel.HARD, True)
    defense = CheckResult("thug", "闪避", 40, CheckDifficulty.REGULAR, 80, 778,
                          SuccessLevel.FAIL, False)
    return CombatOutcome(attack=attack, defense=defense, hit=hit,
                         damage=damage if hit else 0)


@pytest.fixture
def resolve_node(repo, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: 123)
    return build_resolve_checks_node(repo)


def test_combat_resolve_applies_damage_and_records(repo, campaign, monkeypatch):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    seen: dict = {}

    def fake_resolve_attack(actor, skill, attack_value, defender, defense_value, damage_dice,
                            seed, difficulty=CheckDifficulty.REGULAR, bonus=0, penalty=0):
        seen.update(actor=actor, skill=skill, attack_value=attack_value, defender=defender,
                    defense_value=defense_value, damage_dice=damage_dice)
        return fake_outcome()

    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack", fake_resolve_attack)
    upd = build_combat_resolve_node(repo, module)(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "difficulty": "regular", "target": "thug"}]}))
    assert seen["attack_value"] == 70 and seen["defender"] == "thug"
    assert seen["defense_value"] == 40 and seen["damage_dice"] == "1d4"
    assert upd["npc_hp"] == {"thug": 4}
    entry = upd["combat_log"][0]
    assert entry["npc_id"] == "thug" and entry["name"] == "流氓" and entry["hit"] is True
    assert entry["hp_before"] == 8 and entry["hp_after"] == 4 and entry["damage"] == 4
    assert entry["attack"]["level"] == "hard" and entry["defense"]["success"] is False
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert [r.skill for r in rows] == ["格斗", "闪避"]     # 攻击 + 防御各落一条骰子记录
    assert rows[0].seed == 777 and rows[1].seed == 778
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["combat"])
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload["npc_id"] == "thug" and payload["hp_after"] == 4
    assert "HP 8→4" in payload["text"]


def test_combat_miss_keeps_hp(repo, campaign, monkeypatch):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack",
                        lambda *a, **kw: fake_outcome(hit=False))
    upd = build_combat_resolve_node(repo, module)(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "target": "thug"}]}))
    assert upd["npc_hp"]["thug"] == 8 and upd["combat_log"][0]["hit"] is False
    assert upd["combat_log"][0]["damage"] == 0


def test_combat_hp_floor_at_zero(repo, campaign, monkeypatch):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack",
                        lambda *a, **kw: fake_outcome(damage=99))
    upd = build_combat_resolve_node(repo, module)(base_state(
        campaign, npc_hp={"thug": 3}, decision={"checks": [
            {"actor": "pc_1", "skill": "格斗", "target": "thug"}]}))
    assert upd["npc_hp"]["thug"] == 0 and upd["combat_log"][0]["hp_before"] == 3


def test_combat_skips_dead_noncombat_and_outsiders(repo, campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    node = build_combat_resolve_node(repo, module)     # 全部跳过：resolve_attack 不会被调用
    upd = node(base_state(campaign, npc_hp={"thug": 0}, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "target": "thug"},     # 已败亡
        {"actor": "pc_1", "skill": "格斗", "target": "kid"},      # 无 combat 块
        {"actor": "pc_1", "skill": "格斗", "target": "ghost"},    # 场景外
        {"actor": "pc_1", "skill": "格斗"}]}))                    # 无 target：不归它管
    assert upd["combat_log"] == [] and upd["npc_hp"] == {"thug": 0}
    assert repo.list_dice_records(campaign.id, campaign.active_branch_id) == []


def test_resolve_checks_skips_combat_targets(resolve_node, repo, campaign):
    upd = resolve_node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "target": "thug"},
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular"}]}))
    assert [r["skill"] for r in upd["check_results"]] == ["侦查"]
    assert len(repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)) == 1


def test_validate_normalizes_targets(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client([])
    raw = ('{"intent_summary": "打", "checks": ['
           '{"actor": "pc_1", "skill": "格斗", "target": "thug"},'
           '{"actor": "pc_1", "skill": "格斗", "target": "kid"},'
           '{"actor": "pc_1", "skill": "格斗", "target": "ghost"}]}')
    upd = build_validate_node(client, module)({
        "decision_raw": raw, "scene_id": "yard", "budget_level": "ok",
        "campaign_id": "c", "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] is None
    checks = upd["decision"]["checks"]
    assert checks[0]["target"] == "thug"          # 场景内且有 combat：保留
    assert checks[1]["target"] is None            # 无 combat：降级为普通检定
    assert checks[2]["target"] is None            # 场景外：降级为普通检定
    assert built == {}                            # 合法输入不触发 repair 调用


def test_validate_degrades_dead_target(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client([])
    raw = '{"intent_summary": "打", "checks": [{"actor": "pc_1", "skill": "格斗", "target": "thug"}]}'
    upd = build_validate_node(client, module)({
        "decision_raw": raw, "scene_id": "yard", "npc_hp": {"thug": 0},
        "budget_level": "ok", "campaign_id": "c", "branch_id": "c@main", "turn_id": 1})
    assert upd["decision"]["checks"][0]["target"] is None   # 已败亡：不可再被攻击


def test_narrate_includes_combat_line(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client(["打斗叙事。"])
    build_narrate_node(client, module)(base_state(campaign, combat_log=[
        {"npc_id": "thug", "name": "流氓", "hit": True, "damage": 4,
         "hp_before": 8, "hp_after": 4,
         "attack": {"roll": 22, "skill_value": 70, "level": "hard", "success": True},
         "defense": {"roll": 80, "skill_value": 40, "level": "fail", "success": False}},
        {"npc_id": "thug", "name": "流氓", "hit": True, "damage": 4,
         "hp_before": 4, "hp_after": 0,
         "attack": {"roll": 10, "skill_value": 70, "level": "extreme", "success": True},
         "defense": {"roll": 90, "skill_value": 40, "level": "fail", "success": False}}]))
    prompt = built["qwen-plus"].calls[0][1].content
    assert "战斗结算" in prompt and "流氓" in prompt and "8→4" in prompt
    assert "倒下" in prompt                       # HP 归零：败亡提示


def test_narrate_prompt_unchanged_without_combat(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client(["叙事。"])
    build_narrate_node(client, module)(base_state(campaign))
    prompt = built["qwen-plus"].calls[0][1].content
    assert "战斗结算" not in prompt and "NPC 反应" in prompt


def test_graph_routes_combat_and_persists_hp(repo, campaign, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack",
                        lambda *a, **kw: fake_outcome())
    module = Module.model_validate(MODULE_WITH_COMBAT)
    opening_decide = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                      ' "scene_transition": null, "memory_queries": []}')
    attack_decide = ('{"intent_summary": "攻击", "checks": [{"actor": "pc_1", "skill": "格斗",'
                     ' "difficulty": "regular", "target": "thug"}],'
                     ' "proactive_npc_triggers": [], "scene_transition": null,'
                     ' "memory_queries": []}')
    script = {"qwen-plus": [opening_decide, "开场叙事。", attack_decide, "你一拳把流氓打退半步。"]}
    queues = {m: list(v) for m, v in script.items()}

    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    pricing = Pricing(models={
        "qwen-plus": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "qwen-turbo": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
        "deepseek-chat": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    client = LLMClient(Settings(), pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, module, JournalMemory(repo), client,
                             BudgetGuard(Settings()), MemorySaver())
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1,
                                 "inputs": [{"player_id": "p1", "character_id": "pc_1",
                                             "text": "我挥拳打过去"}],
                                 "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["turn_id"] == 2
    snapshot = repo.get_state_at(campaign.id, campaign.active_branch_id, 1)
    assert snapshot["npc_hp"] == {"thug": 4}     # 战斗结果已随 post_turn 落 L2 快照
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["combat"])
    assert len(events) == 1
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert [r.skill for r in rows] == ["格斗", "闪避"]
```

`backend/tests/graph/test_endings.py` 文件尾追加（兼容无场景上下文的 validate 调用）：
```python
def test_validate_keeps_target_without_scene(campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    raw = '{"intent_summary": "x", "checks": [{"actor": "pc_1", "skill": "格斗", "target": "ghost"}]}'
    client, built = make_client([])
    upd = build_validate_node(client, module)({
        "decision_raw": raw, "budget_level": "ok", "campaign_id": "c",
        "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] is None
    assert upd["decision"]["checks"][0]["target"] == "ghost"   # 无 scene_id：target 原样保留
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_combat.py tests/graph/test_endings.py -q`
Expected: FAIL —— test_combat.py 收集期 `ImportError: cannot import name 'build_combat_resolve_node' from 'app.graph.nodes.turn'`；test_endings 追加用例 `KeyError: 'target'`（CheckRequest 尚无该字段）

- [ ] **Step 3: 实现状态与契约（state / schemas）**

`backend/app/graph/state.py` 两处插入：
1. `npc_attitudes` 行之后插入：
```python
    npc_hp: dict[str, int]        # M5-7：NPC 当前 HP（intake 从 L2 快照重建；combat_resolve 写回）
```
2. `check_results` 行之后插入：
```python
    combat_log: list[dict]        # M5-7：本回合战斗结算记录（随 wait_input / fallback 清空）
```

`backend/app/graph/schemas.py` 的 `CheckRequest` 尾部追加（`penalty` 行之后）：
```python
    target: str | None = None     # 攻击目标 NPC id（限当前场景且含 combat 块；validate 负责规范化/降级）
```

- [ ] **Step 4: 实现 turn.py（intake / wait_input / fallback / resolve_checks / post_turn / combat_resolve）**

1. 头部 import：`from app.rules.check import CheckDifficulty, bonus_note, roll_check` 替换为两行：
```python
from app.rules.check import CheckDifficulty, CheckResult, bonus_note, roll_check
from app.rules.combat import resolve_attack
```

2. `build_intake_node` 整体替换为（装载 `npc_hp`、清空 `combat_log`；M5-3 的 paused 计数行保留不动）：
```python
def build_intake_node(repo, module, guard):
    def intake(state: GameState) -> dict:
        campaign_id = state["campaign_id"]
        branch_id = state["branch_id"]
        turn_id = state["turn_id"]
        snap = repo.get_state_at(campaign_id, branch_id, turn_id) or {}
        scene_id = snap.get("scene_id", module.opening.scene_id)
        attitudes = snap.get("npc_attitudes") or {n.id: n.initial_attitude for n in module.npcs}
        npc_hp = snap.get("npc_hp") or {n.id: n.combat.hp for n in module.npcs
                                       if n.combat is not None}
        chars = {c["id"]: c for c in repo.list_characters_at(campaign_id, branch_id, turn_id)}
        inputs = state.get("player_inputs", [])
        is_opening = turn_id == 0 and not inputs

        turn_tokens = repo.turn_token_total(campaign_id, branch_id, turn_id)
        cost = repo.campaign_cost_total(campaign_id)
        level = str(guard.check(turn_tokens, cost))

        repo.add_event(campaign_id, branch_id, turn_id, type="turn_start",
                       payload={"inputs": [i.get("text", "") for i in inputs],
                                "is_opening": is_opening, "budget_level": level})

        upd: dict = {"scene_id": scene_id, "npc_attitudes": attitudes, "characters": chars,
                     "npc_hp": npc_hp, "combat_log": [],
                     "is_opening": is_opening, "budget_level": level, "error": None}
        if level == "paused":
            get_counters().record_fallback("budget_paused")
            upd["error"] = "budget_paused"
        return upd

    return intake
```

3. `wait_input` 的 return 字典替换为（追加 `combat_log / npc_hp` 两键；M3-4 的 `ending_reached` 行保留）：
```python
    return {
        "player_inputs": inputs,
        "is_opening": False,
        # 清空本回合 pending（与"失败不推进/读档重掷"语义一致）
        "decision": None,
        "decision_raw": "",
        "check_results": [],
        "npc_reactions": {},
        "narration": "",
        "narration_segments": [],
        "memory_context": "",
        "error": None,
        "degraded": {},
        "ending_reached": None,
        "combat_log": [],
        "npc_hp": {},
    }
```

4. `fallback` 整体替换为（追加两键；M3-4 的 `ending_reached` 保留）：
```python
def fallback(state: GameState) -> dict:
    """失败不推进：清空本轮 pending，保留 error 供调用方读取（wait_input 恢复时清除）。"""
    return {"player_inputs": [], "decision": None, "decision_raw": "",
            "check_results": [], "npc_reactions": {}, "narration": "",
            "narration_segments": [], "degraded": {}, "ending_reached": None,
            "combat_log": [], "npc_hp": {}}
```

5. `build_resolve_checks_node` 替换为（过滤 target 条目；`_resolve_plain_check` 不动）：
```python
def build_resolve_checks_node(repo):
    def resolve_checks(state: GameState) -> dict:
        checks = (state.get("decision") or {}).get("checks", [])
        # M5-7：带 target 的条目已由 combat_resolve 结算，这里只处理普通检定
        return {"check_results": [_resolve_plain_check(repo, state, chk)
                                  for chk in checks if not chk.get("target")]}

    return resolve_checks
```

6. `build_post_turn_node` 的 `repo.append_state(...)` 调用替换为（快照持久化 npc_hp）：
```python
        repo.append_state(campaign_id, branch_id, turn_id,
                          {"scene_id": state.get("scene_id"),
                           "npc_attitudes": state.get("npc_attitudes", {}),
                           "npc_hp": state.get("npc_hp") or {}})
```

7. 文件尾（`fallback` 之后）追加战斗节点（`_combat_roll_row` + `build_combat_resolve_node`）：
```python
def _combat_roll_row(r: CheckResult) -> dict:
    """战斗记录里的单次掷骰行（形状与 check_results 行一致，提示词/事件/测试共用）。"""
    return {"actor": r.actor, "skill": r.skill, "roll": r.roll, "skill_value": r.skill_value,
            "level": str(r.level), "success": r.success, "bonus": r.bonus, "penalty": r.penalty}


def build_combat_resolve_node(repo, module):
    """战斗结算（规格 §14 边界）：对带 target 的检定逐条执行单次攻击（攻击对抗 → 伤害 → HP）。

    败亡 = HP 归零；非法目标（场景外 / 无 combat / 已败亡）静默跳过——validate 已降级为普通检定，
    此处为防御性兜底（直接调用该节点时也不会抛异常）。
    """
    def combat_resolve(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        checks = [chk for chk in (state.get("decision") or {}).get("checks", [])
                  if chk.get("target")]
        npc_hp = dict(state.get("npc_hp") or {})
        if not checks:
            return {"combat_log": [], "npc_hp": npc_hp}
        try:
            scene = module.scene(state.get("scene_id", ""))
        except KeyError:
            return {"combat_log": [], "npc_hp": npc_hp}
        log: list[dict] = []
        for chk in checks:
            npc_id = chk.get("target")
            if npc_id not in scene.npcs:
                continue                                   # 场景外目标：跳过
            try:
                npc = module.npc(npc_id)
            except KeyError:
                continue
            if npc.combat is None:
                continue                                   # 无 combat 块：不可被攻击
            before = npc_hp.get(npc_id, npc.combat.hp)
            if before <= 0:
                continue                                   # 已败亡：不可再被攻击
            actor, skill = chk["actor"], chk["skill"]
            outcome = resolve_attack(
                actor, skill, _skill_value(state, actor, skill),
                npc.id, npc.combat.defense, npc.combat.damage, new_seed(),
                CheckDifficulty(chk.get("difficulty", "regular")),
                bonus=int(chk.get("bonus", 0)), penalty=int(chk.get("penalty", 0)))
            after = max(0, before - outcome.damage) if outcome.hit else before
            npc_hp[npc_id] = after
            for row in (outcome.attack, outcome.defense):
                repo.add_dice_record(campaign_id, branch_id, turn_id, row.actor, row.skill,
                                     row.skill_value, str(row.difficulty), row.roll,
                                     str(row.level), row.seed,
                                     bonus=row.bonus, penalty=row.penalty)
            verdict = "命中" if outcome.hit else "未命中"
            fall_note = "，目标倒下" if after == 0 else ""
            entry = {"npc_id": npc.id, "name": npc.name, "hit": outcome.hit,
                     "damage": outcome.damage, "hp_before": before, "hp_after": after,
                     "attack": _combat_roll_row(outcome.attack),
                     "defense": _combat_roll_row(outcome.defense)}
            log.append(entry)
            repo.add_event(campaign_id, branch_id, turn_id, type="combat",
                           payload={"text": f"{actor} 对 {npc.name}（{npc.id}）的攻击：{verdict}，"
                                            f"伤害 {outcome.damage}，HP {before}→{after}{fall_note}",
                                    **entry})
        return {"combat_log": log, "npc_hp": npc_hp}

    return combat_resolve
```
（无 target 时返回空日志、零 L2 写入；`combat` 事件 `visibility` 取默认 `"all"`，暗骰链路与此无关。）

- [ ] **Step 5: 实现 gm.py（validate 规范化 / 战斗行 / 提示词 / DECIDE_SYSTEM）**

1. `build_validate_node` 整体替换为（新增 `_normalize_targets`，在成功分支调用；循环结构与 repair 语义为 M3-4 原样，**M5-3 在循环外 return 前的 `get_counters().record_fallback("decision_invalid")` 行保留勿丢**）：
```python
def build_validate_node(client: LLMClient, module=None) -> Callable[[GameState], dict]:
    def _check_refs(decision) -> str | None:
        if module is None:
            return None
        known_clues = {c.id for c in module.clues}
        unknown = [c for c in decision.clues_revealed if c not in known_clues]
        if unknown:
            return f"未知线索 id：{unknown}（可用：{sorted(known_clues)}）"
        if decision.ending_reached is not None:
            known_endings = {e.id for e in module.endings}
            if decision.ending_reached not in known_endings:
                return f"未知结局 id：{decision.ending_reached}（可用：{sorted(known_endings)}）"
        return None

    def _normalize_targets(decision, state: GameState) -> None:
        """非法/已败亡的攻击目标就地降级为普通检定（不触发 repair）；无 module/场景信息时跳过。"""
        if module is None:
            return
        try:
            scene = module.scene(state.get("scene_id", ""))
        except KeyError:
            return
        npc_hp = state.get("npc_hp") or {}
        for chk in decision.checks:
            if chk.target is None:
                continue
            try:
                npc = module.npc(chk.target)
            except KeyError:
                chk.target = None
                continue
            if (npc.combat is None or chk.target not in scene.npcs
                    or int(npc_hp.get(chk.target, 1)) <= 0):
                chk.target = None

    def validate_decision(state: GameState) -> dict:
        raw = state.get("decision_raw", "")
        repair_msg = ""
        for _ in range(2):  # 首次 + repair 重试恰好 1 次（规格 §8）
            try:
                decision = parse_decision_json(raw)
                ref_error = _check_refs(decision)
                if ref_error is None:
                    _normalize_targets(decision, state)
                    return {"decision": decision.model_dump(mode="json"), "error": None}
                repair_msg = ref_error
            except Exception as exc:
                repair_msg = str(exc)
            messages = [ChatMessage(
                role="user",
                content=(f"你上次的输出不合格（{repair_msg}）。"
                         f"请只输出合法 JSON，字段要求不变。上次输出：\n{raw}"))]
            try:
                raw = client.chat("gm", messages, _ctx(state), cheap=_cheap(state))
            except Exception as exc:
                repair_msg = str(exc)
        get_counters().record_fallback("decision_invalid")
        return {"error": "decision_invalid", "decision": None,
                "degraded": {"decision_invalid": True}}
```

2. 在 `_reaction_lines` 之后、`build_narrate_node` 之前插入 `_combat_lines`：
```python
def _combat_lines(state: GameState) -> str:
    lines = []
    for c in state.get("combat_log", []):
        atk, dfn = c.get("attack", {}), c.get("defense", {})
        if c.get("hit"):
            outcome = f"命中，伤害 {c['damage']}（HP {c['hp_before']}→{c['hp_after']}）"
            if c.get("hp_after") == 0:
                outcome += "，目标倒下（败亡）"
        else:
            outcome = "未命中"
        lines.append(f"- {c['name']}（{c['npc_id']}）：{outcome}；"
                     f"攻击 {atk.get('roll')}/{atk.get('skill_value')} → {atk.get('level')}，"
                     f"闪避 {dfn.get('roll')}/{dfn.get('skill_value')} → {dfn.get('level')}")
    return "\n".join(lines)
```

3. `gm_narrate` 内 `user = (...)` 组装替换为（无战斗记录时 `combat_block == ""`，提示词与 M3-3 逐字符一致）：
```python
        combat_lines = _combat_lines(state)
        combat_block = f"战斗结算：\n{combat_lines}\n" if combat_lines else ""
        user = (
            f"{opening_line}{ending_line}"
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"玩家行动：\n{inputs_txt}\n"
            f"检定结果：\n{_check_lines(state)}\n"
            f"{combat_block}"
            f"NPC 反应：\n{_reaction_lines(state, module)}\n"
            "请输出本回合的完整叙事。"
        )
```

4. `DECIDE_SYSTEM` 整体替换（在 M5-4 版基础上加 target 字段说明与规则句；`clues_revealed/ending_reached` 两行与 bonus/penalty 说明保留）：
```python
DECIDE_SYSTEM = (
    "你是跑团主持人（COC 风格）。基于玩家行动与当前场景做结构化裁决，只输出一个 JSON 对象，字段：\n"
    'intent_summary(str)、checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme),'
    '"secret"(bool，可选，默认 false),"bonus"(0-2，可选),"penalty"(0-2，可选),'
    '"target"(str，可选，攻击目标 NPC 的 id)})、'
    'proactive_npc_triggers(数组，元素 {"npc_id","trigger"})、'
    'scene_transition(null 或 {"to_scene","reason"})、'
    'clues_revealed(数组，元素为线索 id，仅当本回合玩家明确获得线索时填写)、'
    'ending_reached(null 或模块给定结局 id，仅当叙事故意收束到结局时填写)、'
    'memory_queries(字符串数组)。\n'
    "规则：只为玩家的主动行动要求检定，每回合最多 2 个检定；NPC 只能用场景内列出的；"
    "奖励/惩罚骰仅在情境明显有利/不利时给出（如充分准备、恶劣环境），每项最多 2，默认省略；"
    "开场回合可以引入场面但不要要求检定；"
    "target 仅在玩家攻击当前场景内某个 NPC 时填写（被攻击者必须可被攻击），其余检定不要填 target；"
    "secret=true 表示玩家角色无从察觉的暗骰（如暗中进行的观察或聆听），其检定与结果不得在叙事中直接暴露。"
)
```

- [ ] **Step 6: 实现 main.py（路由与装配）**

1. import 行替换：
```python
from app.graph.nodes.turn import (build_intake_node, build_post_turn_node,
                                  build_resolve_checks_node, fallback, wait_input)
```
→
```python
from app.graph.nodes.turn import (build_combat_resolve_node, build_intake_node,
                                  build_post_turn_node, build_resolve_checks_node,
                                  fallback, wait_input)
```

2. `_route_after_validate` 替换并追加新路由（放在 `_route_after_validate` 之后）：
```python
def _route_after_validate(state: GameState) -> str:
    return "fallback" if state.get("error") else "resolve_checks"
```
→
```python
def _route_after_validate(state: GameState) -> str:
    if state.get("error"):
        return "fallback"
    checks = (state.get("decision") or {}).get("checks", [])
    return "combat_resolve" if any(c.get("target") for c in checks) else "resolve_checks"


def _route_after_combat(state: GameState) -> str:
    return "fallback" if state.get("error") else "resolve_checks"
```

3. `build_game_graph` 内两处：
   - `g.add_node("validate", build_validate_node(client, module))` 之后追加一行：
```python
    g.add_node("combat_resolve",
               _guarded("combat_failed", build_combat_resolve_node(repo, module)))
```
   - validate 条件边替换为三分支映射，并在其后追加 combat_resolve 条件边：
```python
    g.add_conditional_edges("validate", _route_after_validate,
                            {"fallback": "fallback", "combat_resolve": "combat_resolve",
                             "resolve_checks": "resolve_checks"})
    g.add_conditional_edges("combat_resolve", _route_after_combat,
                            {"fallback": "fallback", "resolve_checks": "resolve_checks"})
```
（`combat_resolve` 的唯一出口：成功 → `resolve_checks`；真异常经 `_guarded("combat_failed")` → `_route_after_combat` → `fallback`，不再执行普通检定。）

- [ ] **Step 7: 定向验证（战斗 + 图回归）**

Run: `cd backend; uv run pytest tests/graph/test_combat.py tests/graph/test_endings.py -q`
Expected: PASS —— test_combat.py 10 例全绿（含图级路由与 HP 快照用例）+ test_endings 既有用例与新增 `test_validate_keeps_target_without_scene` 全绿

Run: `cd backend; uv run pytest tests/graph tests/rules -q`
Expected: PASS —— 零回归（重点确认 test_resolve_checks / test_gm_decide / test_gm_narrate / test_replay_smoke 不受 validate 三分支与 narrate 条件块影响）

- [ ] **Step 8: 全量回归**

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 后端全量绿（含 M2 回放冒烟；test_replay_smoke 无 target 字段，行为与接入前一致）

- [ ] **Step 9: Commit**

```bash
git add backend/app/graph/state.py backend/app/graph/schemas.py backend/app/graph/nodes/turn.py backend/app/graph/nodes/gm.py backend/app/graph/main.py backend/tests/graph/test_combat.py backend/tests/graph/test_endings.py
git commit -m "feat(graph): combat resolution node with target routing and npc hp snapshot"
```

---

## 计划自审（M5）

**规格覆盖表**（对照 `docs/superpowers/specs/2026-09-24-ensemble-design.md`）：

| 规格章节 | 覆盖任务 |
| --- | --- |
| §13-M5 Graphiti 适配器 | M5-1（`MemoryService` 协议实现、懒加载 + 优雅回退、`build_memory` 切换） |
| §10 可观测性（LangSmith + 本地 JSONL 降级） | M5-2（Tracer：JSONL 字段对齐 run 格式、LangSmith 开关、chat/chat_stream 包裹） |
| §10 /metrics 四指标（不引入 Prometheus） | M5-3（每回合延迟 / LLM 成功率 / 降级计数 / NPC 激活分布 + 成本汇总） |
| §9 成本控制（用量记账 + 前端成本面板） | M5-5（usage API + CostPanel；分级路由与熔断为 M2 已交付，本计划只补面板） |
| §13-M5 奖惩骰（COC 7e 全链路） | M5-4（规则 → GM 提示词 → 存储迁移 → API → 前端标注） |
| §5.3 私密信息（暗骰链路兼容） | M5-4（secret 与 bonus/penalty 正交）、M5-7（combat 事件仅 L2，不新增 WS 白名单） |
| §13-M5 战斗子图 + §14 YAGNI 边界 | M5-6（纯函数 rules/combat.py + NpcDef.combat）、M5-7（combat_resolve 节点、target 路由、HP 快照/败亡） |

**已知边界（有意为之）**：
- 败亡 = HP 归零：0 HP 的 NPC 从此不可再被攻击（validate 静默降级 + combat_resolve 防御性跳过）；无战败结算流程、无先攻/战斗轮/NPC 反击，与 §14 YAGNI 一致。
- target 校验为**静默降级**（非法/场景外/无 combat/已败亡 → 移除 target，检定保留为普通检定），不触发 repair——repair 仍只服务 JSON 解析与引用类错误，避免字段错误放大为回合失败。
- 战斗记录 `combat_log` 为本回合内存态，不持久化；权威 HP（`npc_hp`）随 `post_turn` 落 L2 快照，重开/重连由 intake 重建。重连视图经 dice 行（攻击 + 闪避各一条）与叙事感知战斗，无独立战斗面板。
- 无 target 时全链路行为与接入前一致：提示词不含"战斗结算"、路由直达 resolve_checks（`test_narrate_prompt_unchanged_without_combat` 守护）。
- 可选依赖（graphiti-core / langsmith）未安装时全部走回退路径，M5 验收不要求安装（相关测试均以注入替身/延迟导入路径验证）。

**类型一致性抽查**：
- `combat_log` 条目形状 `{npc_id, name, hit, damage, hp_before, hp_after, attack, defense}` 四处一致：M5-7 节点产出、test_combat 断言、`_combat_lines` 读取、`combat` 事件 payload（`**entry` + `text`）。
- 掷骰行 `_combat_roll_row` 与 `check_results` 行同构（`actor/skill/roll/skill_value/level/success/bonus/penalty`）：测试以 `entry["attack"]["level"] == "hard"`（StrEnum JSON 序列化）与 `rows[0].seed == 777` 双重锚定。
- `npc_hp` 五处一致：`GameState.npc_hp` → intake 重建（`snap.get("npc_hp") or {n.id: n.combat.hp ...}`）→ combat_resolve 写回 → post_turn `append_state` 持久化 → wait_input / fallback 清空（失败不推进语义）。
- `CheckRequest.target` 三层一致：M5-7 schemas 定义 → validate `_normalize_targets` 就地降级 → `_route_after_validate` 分流键与 combat_resolve 过滤条件同源（`chk.get("target")`）。
- 路由名一致：`_route_after_validate` 返回值（`fallback` / `combat_resolve` / `resolve_checks`）与 `add_conditional_edges` 映射键逐一对应；`_route_after_combat` 与之同构。

---

## 执行交接（M5）

本计划 7 个任务按依赖序排列：M5-1（Graphiti，独立）→ M5-2（追踪）→ M5-3（metrics + 降级计数）→ M5-4（奖惩骰）→ M5-5（成本面板）→ M5-6（战斗纯函数）→ M5-7（战斗接入主图，依赖 M5-4 的 `_resolve_plain_check` 与 M5-6 的 `resolve_attack`）。多个任务触碰同一文件（`config.py` / `turn.py` / `gm.py` / `main.py` / `session.py`），必须按任务号线性执行，避免交叉合并。

执行方式二选一：
1. **Subagent 逐任务执行（推荐）**：每个任务派发新的子代理实现，任务间人工审查把关；
2. **本会话内批量执行**：按 executing-plans 流水线推进，在检查点停顿复核。

交接前确认：
- M2（Task 1-24）、M3（T1-T17）、M4（M4-1~M4-7）全部完成且 `cd backend; uv run pytest -q` 全绿；`cd frontend; npm run test` 全绿；
- 可选依赖无需预装（M5-1/M5-2 的回退路径即验收路径；如需真联 Graphiti / LangSmith，再 `uv sync --extra graph --extra observability` 并按 `.env.example` 配置）；
- 战斗验收含手测项：运行示例模组（Web 或 CLI），对 `misty_hollow` 的 `whisperer` 发起攻击，观察骰子行 ×2（攻击 + 闪避）、叙事出现"战斗结算"与 HP 变化、败亡后不再可被攻击。

---
