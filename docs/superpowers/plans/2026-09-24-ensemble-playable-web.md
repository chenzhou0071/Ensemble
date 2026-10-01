# Ensemble 可玩 Web（M3）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M1+M2 后端核心之上交付浏览器可玩版本：FastAPI + WebSocket 接入层、TurnBuffer 回合窗口（N=1 防抖）、NPC 台词真流式推送、React 房间页（打字机叙事 + 骰子动画 + 角色卡 + 线索面板），出口标准 = 浏览器里跑完示例模组一条结局线。

**Architecture:** 依赖方向 `api → graph → {rules, memory, content, llm, storage}`（规格 §3）。新增 `app/api/` 接入层：SessionManager 是图的唯一驱动者（规格 §4.2），TurnBuffer 状态机独立可测；叙事流由 gm_narrate 节点经 LangGraph custom stream 发射，API 层经 WS `token` 事件转发；结局/线索机制补齐（M2 只有静态校验，无运行时触发）。

**Tech Stack:** FastAPI + uvicorn（WebSocket）、React 18 + Vite + TypeScript + zustand、vitest + @testing-library/react；其余沿用 M1+M2（Python 3.12 / uv / LangGraph / SQLModel + SQLite / pytest）。

**依据规格:** `docs/superpowers/specs/2026-09-24-ensemble-design.md`（§3 / §4 / §5.3 / §6 / §7 / §11）
**前置依赖:** `docs/superpowers/plans/2026-09-24-ensemble-backend-core.md`（M1+M2）全部 24 个任务完成；本计划在其代码基线上增量修改。

## Global Constraints

以下约束适用于本计划**每一个任务**，值均拷贝自规格原文：

- Python 3.12+；uv；新增后端依赖 `fastapi`、`uvicorn[standard]`；dev 依赖追加 `httpx`、`pytest-asyncio`；前端 Node 20+，React + Vite + TS + zustand（规格 §15）
- WS 事件统一 schema：`{seq, type, visibility, payload}`；`type ∈ token|dice|actor|scene|state|turn|error`；`seq` 支持断线重连重放（规格 §6.3）
- 叙事有序性：NPC 台词**不独立推送**；`gm_narrate` 统一编排后流式推送，`token.payload = {"speaker": "gm"|"npc:<id>", "text": ...}`；前端按 speaker 渲染（规格 §4.1）
- TurnBuffer 状态机固定：`IDLE → COLLECTING(turn_id) → RESUME`；单人（N=1）提交后 **2 秒防抖**关窗；全员提交或超时（默认 60s，`Settings.turn_window_seconds`）关窗；窗口外输入进 `pending_next` 预填（规格 §4.2）
- 挂起检测：API 层是图的唯一驱动者；每轮图执行结束检查 `get_state(config)`，停在 `wait_input` 才开窗（规格 §4.2）
- 活跃玩家定义 = 已加入且在线；M3 只验证 N=1；全员窗口/超时/掉线语义在 M4 完善（规格 §4.2 全量语义本次只实现单人分支 + 通用状态机）
- 事件统一携带 `visibility`（`all | player:{id}`）；服务端过滤后推送，前端只负责渲染（规格 §5.3）
- 预算熔断：`paused` 时 UI 明示原因，手动恢复（规格 §9）；M3 不做 LangSmith / `/metrics` / Graphiti / 成本面板（M5）
- 分叉语义（规格 §7）：`restore` 从历史 turn 创建**新分支并切换**；原分支完整保留；L2 按 branch_id 复制 ≤ 目标 turn；checkpoint 复制到新 thread
- 存档点 = `post_turn` 结束时的 turn 边界快照；`thread_id = {campaign_id}@{branch_id}`，主分支 `main`（沿用）
- 所有命令在 Windows PowerShell 下执行，用 `;` 串联；工作目录统一为 `e:\pro\Ensemble`
- 每任务结束独立提交；提交保持本地不推送（用户确认后再推送）

---

## File Structure（本计划涉及的全部文件）

```
ensemble/
├── README.md                          # Task M3-17（开发运行说明）
├── modules/                           # 不改动（misty_hollow.yaml 沿用）
├── backend/
│   ├── pyproject.toml                 # Task M3-5（新增 fastapi/uvicorn/httpx/pytest-asyncio）
│   ├── app/
│   │   ├── config.py                  # Task M3-5（新增 modules_dir / cors / debounce / ws 配置）
│   │   ├── cli.py                     # Task M3-4（结局提示）
│   │   ├── content/
│   │   │   └── registry.py            # Task M3-5（模组扫描与按 id 查找）
│   │   ├── storage/
│   │   │   └── repo.py                # Task M3-5（玩家）、Task M3-6（分支回合数）、Task M3-7（分叉复制）
│   │   ├── llm/
│   │   │   ├── client.py              # Task M3-1（chat_stream 流式）
│   │   │   └── fakes.py               # Task M3-1（FakeLLM.chat_stream）
│   │   ├── graph/
│   │   │   ├── state.py               # Task M3-4（ending_reached 字段）
│   │   │   ├── schemas.py             # Task M3-4（clues_revealed / ending_reached）、Task M3-4A（attitude_deltas）
│   │   │   ├── narrative.py           # Task M3-2（IncrementalSegmenter）
│   │   │   ├── nodes/gm.py            # Task M3-3（narrate 流式）、Task M3-4（提示词/校验）、Task M3-4A（DECIDE_SYSTEM 态度字段）
│   │   │   ├── nodes/turn.py          # Task M3-4（post_turn 线索/结局、fallback 清理）、Task M3-4A（态度应用 + attitude 事件）
│   │   │   ├── main.py                # Task M3-4（结局路由）
│   │   │   └── fork.py                # Task M3-7（checkpoint 链复制）
│   │   ├── rules/
│   │   │   └── attitude.py            # Task M3-4A（好感度硬边界纯函数）
│   │   └── api/
│   │       ├── __init__.py            # Task M3-5
│   │       ├── events.py              # Task M3-8（EventBus）
│   │       ├── turn_buffer.py         # Task M3-9（TurnBuffer 状态机）
│   │       ├── session.py             # Task M3-10（RoomSession / SessionManager）
│   │       ├── routes.py              # Task M3-5/6/7（REST）
│   │       ├── ws.py                  # Task M3-11（WS 端点）
│   │       └── app.py                 # Task M3-11（create_app 装配）
│   └── tests/
│       ├── conftest.py                # 追加 api 公共 fixture（Task M3-11 起）
│       ├── harness/replay.py          # Task M3-3（chat_stream 支持）
│       ├── llm/test_stream.py         # Task M3-1
│       ├── graph/test_incremental.py  # Task M3-2
│       ├── graph/test_gm_narrate.py   # Task M3-3（追加流式用例）
│       ├── graph/test_endings.py      # Task M3-4
│       ├── graph/test_attitude.py     # Task M3-4A（post_turn 集成 + 正向链路）
│       ├── graph/test_gm_decide.py    # Task M3-4A（追加 DECIDE_SYSTEM 断言）
│       ├── graph/test_fork.py         # Task M3-7
│       ├── rules/test_attitude.py     # Task M3-4A（纯函数全覆盖）
│       └── api/
│           ├── test_campaigns_api.py  # Task M3-5
│           ├── test_timeline_api.py   # Task M3-6
│           ├── test_restore_api.py    # Task M3-7
│           ├── test_event_bus.py      # Task M3-8
│           ├── test_turn_buffer.py    # Task M3-9
│           ├── test_session.py        # Task M3-10
│           ├── test_ws.py             # Task M3-11
│           └── test_e2e_web.py        # Task M3-17
└── frontend/
    ├── package.json                   # Task M3-12
    ├── vite.config.ts                 # Task M3-12
    ├── tsconfig.json / index.html     # Task M3-12
    └── src/
        ├── main.tsx / App.tsx         # Task M3-12
        ├── types.ts                   # Task M3-12（WS/REST 类型）
        ├── api/rest.ts                # Task M3-12
        ├── api/ws.ts                  # Task M3-12（重连 + resume_from）
        ├── stores/game.ts             # Task M3-13（zustand + 纯 reducer）
        ├── views/Lobby.tsx            # Task M3-14
        ├── views/Room.tsx             # Task M3-15
        └── components/
            ├── NarrationStream.tsx    # Task M3-15
            ├── Typewriter.tsx         # Task M3-15
            ├── InputBar.tsx           # Task M3-15
            ├── DiceOverlay.tsx        # Task M3-16
            ├── CharacterPanel.tsx     # Task M3-16
            ├── NpcPanel.tsx           # Task M3-16
            ├── CluePanel.tsx          # Task M3-16
            └── EndingOverlay.tsx      # Task M3-16
```

---

### Task M3-1: LLM 流式输出（chat_stream + StreamUsage）

**Files:**
- Modify: `backend/app/llm/client.py`（StreamUsage、ChatModel 协议、OpenAICompatModel.chat_stream、LLMClient.chat_stream）
- Modify: `backend/app/llm/fakes.py`（FakeLLM.chunk_size + chat_stream）
- Test: `backend/tests/llm/test_stream.py`

**Interfaces:**
- Consumes: M2 Task 11 的 `LLMClient` / `FakeLLM` / `ChatModel` 协议
- Produces：
  - `StreamUsage`（dataclass：`tokens_in: int = 0, tokens_out: int = 0`，模型实现就地累写）
  - `ChatModel` 协议新增 `chat_stream(messages: list[ChatMessage], usage: StreamUsage) -> Iterator[str]`
  - `LLMClient.chat_stream(role, messages, ctx, cheap=False) -> Iterator[str]`：流结束后**记录一次** usage；provider 未回 usage 时按字符估算（`tokens_in = max(1, 输入字符//2)`、`tokens_out = max(1, 输出字符//2)`）；消费方中途放弃不记账（生成器语义，文档注明）
  - `FakeLLM(script, tokens_in=10, tokens_out=20, chunk_size=8)`：`chat_stream` 与 `chat` 共用脚本消耗逻辑，按 `chunk_size` 切块 yield

- [ ] **Step 1: 写失败测试**

`backend/tests/llm/test_stream.py`：
```python
from app.config import Pricing, PricingEntry, Settings
from app.llm.client import ChatMessage, ChatResponse, LLMClient, LlmContext
from app.llm.fakes import FakeLLM

MSGS = [ChatMessage(role="user", content="你好")]
CTX = LlmContext(campaign_id="c1", branch_id="c1@main", turn_id=1)

def make_pricing():
    return Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "alt-cheap-model": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })

def make_client(script):
    # gm 用真名；cheap 用虚构名以区分"超限切换"路由（生产两档同名，见 config.py）
    settings = Settings(gm_model="qwen3.8-flash", cheap_model="alt-cheap-model")
    rows, built = [], {}
    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script))
        return built[model]
    class Sink:
        def record_usage(self, *a, **kw):
            rows.append(kw)
    return LLMClient(settings, make_pricing(), usage_sink=Sink(), model_factory=factory), built, rows

def test_stream_joins_to_full_text_and_records_once():
    client, built, rows = make_client(["你好，世界！"])
    text = "".join(client.chat_stream("gm", MSGS, CTX))
    assert text == "你好，世界！"
    assert len(rows) == 1
    assert rows[0]["model"] == "qwen3.8-flash"
    assert rows[0]["tokens_in"] == 10 and rows[0]["tokens_out"] == 20

def test_stream_cheap_routing():
    client, built, rows = make_client(["x"])
    text = "".join(client.chat_stream("gm", MSGS, CTX, cheap=True))
    assert text == "x" and "alt-cheap-model" in built
    assert rows[0]["model"] == "alt-cheap-model"

def test_stream_usage_estimate_when_provider_silent():
    class SilentModel:
        def chat(self, messages):
            return ChatResponse(text="")
        def chat_stream(self, messages, usage):
            yield "abcd"
            yield "ef"
    rows = []
    class Sink:
        def record_usage(self, *a, **kw):
            rows.append(kw)
    client = LLMClient(Settings(), make_pricing(), usage_sink=Sink(),
                       model_factory=lambda *_: SilentModel())
    text = "".join(client.chat_stream("gm", MSGS, CTX))
    assert text == "abcdef"
    assert rows[0]["tokens_out"] == 3          # 6 字符 // 2
    assert rows[0]["tokens_in"] >= 1           # 估算兜底

def test_stream_chunks_respect_text():
    client, built, _ = make_client([ChatResponse(text="0123456789", tokens_in=1, tokens_out=2)])
    chunks = list(client.chat_stream("gm", MSGS, CTX))
    assert "".join(chunks) == "0123456789" and len(chunks) == 2   # chunk_size=8
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/llm/test_stream.py -q`
Expected: FAIL —— `AttributeError: 'LLMClient' object has no attribute 'chat_stream'`

- [ ] **Step 3: 修改 client.py**

头部 `dataclass` import 已存在（M2）；在 `ChatResponse` 之后追加：
```python
from typing import Iterator  # 追加到 typing import 行


@dataclass
class StreamUsage:
    tokens_in: int = 0
    tokens_out: int = 0
```

`ChatModel` 协议追加一行：
```python
class ChatModel(Protocol):
    def chat(self, messages: list[ChatMessage]) -> ChatResponse: ...
    def chat_stream(self, messages: list[ChatMessage], usage: StreamUsage) -> Iterator[str]: ...
```

`OpenAICompatModel` 追加方法：
```python
    def chat_stream(self, messages, usage):
        payload = {"model": self.model, "messages": [m.model_dump() for m in messages]}
        try:
            stream = self._client.chat.completions.create(
                **payload, stream=True, stream_options={"include_usage": True})
        except Exception:
            # 部分兼容端点不认 stream_options：退化为无 usage 流（由 LLMClient 估算）
            stream = self._client.chat.completions.create(**payload, stream=True)
        for chunk in stream:
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage.tokens_in = getattr(u, "prompt_tokens", 0) or 0
                usage.tokens_out = getattr(u, "completion_tokens", 0) or 0
            if getattr(chunk, "choices", None):
                text = getattr(chunk.choices[0].delta, "content", None)
                if text:
                    yield text
```

`LLMClient` 追加方法（放在 `chat` 之后）：
```python
    def chat_stream(self, role: Role, messages: list[ChatMessage], ctx: LlmContext,
                    cheap: bool = False) -> Iterator[str]:
        """流式输出；流正常结束后记一次账（消费方中途放弃则不记账）。"""
        model, base_url, api_key = self._resolve(role, cheap)
        model_obj = self._factory(model, base_url, api_key)
        usage = StreamUsage()
        chars = 0
        start = time.perf_counter()
        for delta in model_obj.chat_stream(messages, usage):
            chars += len(delta)
            yield delta
        latency_ms = int((time.perf_counter() - start) * 1000)
        if usage.tokens_in == 0 and usage.tokens_out == 0:
            usage.tokens_in = max(1, sum(len(m.content) for m in messages) // 2)
            usage.tokens_out = max(1, chars // 2)
        cost = compute_cost(self._pricing, model, usage.tokens_in, usage.tokens_out)
        if self._usage_sink is not None:
            self._usage_sink.record_usage(ctx.campaign_id, ctx.branch_id, ctx.turn_id,
                                          role, model, usage.tokens_in, usage.tokens_out,
                                          cost, latency_ms)
```

- [ ] **Step 4: 修改 fakes.py**

`FakeLLM.__init__` 签名改为 `(self, script, tokens_in=10, tokens_out=20, chunk_size=8)`（保存 `self.chunk_size = chunk_size`）；把现有脚本消耗逻辑抽出为 `_next(self)`：

```python
    def _next(self):
        if not self.script:
            raise IndexError("FakeLLM script exhausted")
        return self.script.pop(0)

    def chat(self, messages):
        self.calls.append(list(messages))
        item = self._next()
        if isinstance(item, ChatResponse):
            return item
        return ChatResponse(text=item, tokens_in=self.tokens_in, tokens_out=self.tokens_out)

    def chat_stream(self, messages, usage):
        self.calls.append(list(messages))
        item = self._next()
        if isinstance(item, ChatResponse):
            usage.tokens_in, usage.tokens_out = item.tokens_in, item.tokens_out
            text = item.text
        else:
            usage.tokens_in, usage.tokens_out = self.tokens_in, self.tokens_out
            text = item
        for i in range(0, len(text), self.chunk_size):
            yield text[i:i + self.chunk_size]
```
（原 `chat` 实现中已有的 `calls.append` 与脚本耗尽 `IndexError("FakeLLM script exhausted")` 行为保持不变。）

- [ ] **Step 5: 验证通过（含 M2 全量回归）**

Run: `cd backend; uv run pytest tests/llm tests/graph -q`
Expected: PASS（新用例 + M2 原有 llm/graph 用例全绿）

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm/client.py backend/app/llm/fakes.py backend/tests/llm/test_stream.py
git commit -m "feat(llm): streaming chat with usage accounting and fake stream support"
```

---

### Task M3-2: 增量分段器（流式叙事说话人）

**Files:**
- Modify: `backend/app/graph/narrative.py`（追加 `IncrementalSegmenter`）
- Test: `backend/tests/graph/test_incremental.py`

**Interfaces:**
- Consumes: `narrative.py` 既有标记约定（`[[npc:<id>]]...[[/npc]]`，M2 Task 14）
- Produces：
  - `IncrementalSegmenter`：`feed(chunk: str) -> list[tuple[str, str]]`（增量产出 `(speaker, text)`，speaker 为 `"gm"` 或 `"npc:<id>"`）；`flush() -> list[tuple[str, str]]`
  - 处理**跨 chunk 截断**：buf 末尾若匹配标记前缀则保留（holdback），不产出半截标记
  - 权威分段仍由 `parse_segments` 在节点末尾生成（落库用）；本分段器只服务实时推送展示层

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_incremental.py`：
```python
from app.graph.narrative import IncrementalSegmenter

def collect(chunks):
    seg = IncrementalSegmenter()
    out = []
    for c in chunks:
        out.extend(seg.feed(c))
    out.extend(seg.flush())
    return out

def test_marker_split_across_chunks():
    out = collect(["你推开门。[[np", "c:guard]]站住！[[/n", "pc]]他盯着你。"])
    assert out == [("gm", "你推开门。"), ("npc:guard", "站住！"), ("gm", "他盯着你。")]

def test_plain_text_streams_immediately():
    out = collect(["第一句。", "第二句。"])
    assert out == [("gm", "第一句。"), ("gm", "第二句。")]

def test_holdback_only_prefix():
    seg = IncrementalSegmenter()
    assert seg.feed("他说[") == [("gm", "他说")]
    assert seg.feed("[不是标记]") == [("gm", "[不是标记]")]

def test_multiple_markers_one_chunk():
    out = collect(["[[npc:a]]一[[/npc]]中[[npc:b]]二[[/npc]]尾"])
    assert out == [("npc:a", "一"), ("gm", "中"), ("npc:b", "二"), ("gm", "尾")]

def test_flush_emits_leftover():
    seg = IncrementalSegmenter()
    seg.feed("[[npc:ghost]]说了半句")
    assert seg.flush() == [("npc:ghost", "说了半句")]
    assert seg.flush() == []
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_incremental.py -q`
Expected: FAIL —— `ImportError: cannot import name 'IncrementalSegmenter'`

- [ ] **Step 3: 实现（追加到 narrative.py）**

```python
OPEN_MARK = "[[npc:"
CLOSE_MARK = "[[/npc]]"


def _holdback_len(buf: str, marker: str) -> int:
    """buf 末尾可能是 marker 前缀（跨 chunk 截断）时需保留的字符数。"""
    for k in range(min(len(marker) - 1, len(buf)), 0, -1):
        if buf.endswith(marker[:k]):
            return k
    return 0


class IncrementalSegmenter:
    """流式叙事分段器：与 parse_segments 同一标记语法，处理跨 chunk 截断。

    只用于实时推送（展示层）；落库的权威分段由 parse_segments 在节点末尾生成。
    已知差异：输出不合法（标记未闭合）时两者兜底切分可能不同——重连后以落库分段为准。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._speaker = "gm"

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self._buf += chunk
        out: list[tuple[str, str]] = []
        while self._buf:
            if self._speaker == "gm":
                idx = self._buf.find(OPEN_MARK)
                if idx == -1:
                    hold = _holdback_len(self._buf, OPEN_MARK)
                    emit = self._buf[: len(self._buf) - hold]
                    self._buf = self._buf[len(self._buf) - hold:]
                    if emit:
                        out.append(("gm", emit))
                    break
                emit, self._buf = self._buf[:idx], self._buf[idx:]
                if emit:
                    out.append(("gm", emit))
                end = self._buf.find("]]")
                if end == -1:
                    break  # 开标签跨 chunk：等待更多输入
                npc_id = self._buf[len(OPEN_MARK):end]
                self._speaker = f"npc:{npc_id}"
                self._buf = self._buf[end + 2:]
            else:
                idx = self._buf.find(CLOSE_MARK)
                if idx == -1:
                    hold = _holdback_len(self._buf, CLOSE_MARK)
                    emit = self._buf[: len(self._buf) - hold]
                    self._buf = self._buf[len(self._buf) - hold:]
                    if emit:
                        out.append((self._speaker, emit))
                    break
                emit, self._buf = self._buf[:idx], self._buf[idx + len(CLOSE_MARK):]
                if emit:
                    out.append((self._speaker, emit))
                self._speaker = "gm"
        return out

    def flush(self) -> list[tuple[str, str]]:
        """流结束时调用：剩余缓冲按当前说话人输出（未闭合标记的兜底）。"""
        if not self._buf:
            return []
        out = [(self._speaker, self._buf)]
        self._buf = ""
        return out
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/graph/test_incremental.py tests/graph/test_narrative.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/narrative.py backend/tests/graph/test_incremental.py
git commit -m "feat(graph): incremental segmenter for streaming narrative"
```

---

### Task M3-3: gm_narrate 流式化 + 回放客户端适配

**Files:**
- Modify: `backend/app/graph/nodes/gm.py`（narrate 改用 `chat_stream` + stream writer 发射分段）
- Modify: `backend/tests/harness/replay.py`（ReplayModels.chat_stream；录制工厂支持流）
- Test: `backend/tests/graph/test_gm_narrate.py`（追加流式用例）

**Interfaces:**
- Consumes: `LLMClient.chat_stream`（M3-1）、`IncrementalSegmenter`（M3-2）
- Produces：
  - `build_narrate_node` 行为扩展：在 LangGraph stream 上下文中经 `get_stream_writer()` 发射 `{"speaker","text"}` 增量与每次尝试开头的 `{"reset": True}`；**invoke/CLI 场景 writer 为 no-op，返回值与 M2 完全一致**（`narration` / `narration_segments` / `error`）
  - 结局提示：`state["decision"]["ending_reached"]` 存在时，提示词附加结局收束指令（读 `module.ending(eid).condition`）
  - `ReplayModels.chat_stream(messages, usage)`：与 `chat` 相同的顺序断言与消耗逻辑；文本按 8 字符切片 yield
  - `make_recording_factory` 的录制模型新增 `chat_stream`：流结束后把完整文本记入 collected

- [ ] **Step 1: 写失败测试（追加到 test_gm_narrate.py）**

```python
from langgraph.graph import END, START, StateGraph

from app.graph.state import GameState


def stream_chunks(node, state):
    g = StateGraph(GameState)
    g.add_node("gm_narrate", node)
    g.add_edge(START, "gm_narrate")
    g.add_edge("gm_narrate", END)
    app = g.compile()
    return [c for c in app.stream(state, stream_mode="custom")]


def merge_speakers(chunks):
    merged = []
    for c in chunks:
        if c.get("reset"):
            continue
        if merged and merged[-1][0] == c["speaker"]:
            merged[-1][1] += c["text"]
        else:
            merged.append([c["speaker"], c["text"]])
    return merged


def test_narrate_streams_speaker_tagged_chunks(campaign, mini_module):
    client, built = make_client(["你推开门。[[npc:guard]]站住！[[/npc]]他警惕地盯着你。"])
    chunks = stream_chunks(build_narrate_node(client, mini_module), base_state(campaign))
    assert chunks[0] == {"reset": True}
    merged = merge_speakers(chunks)
    assert [s for s, _ in merged] == ["gm", "npc:guard", "gm"]
    assert "".join(t for _, t in merged) == "你推开门。站住！他警惕地盯着你。"


def test_narrate_streams_reset_on_retry(campaign, mini_module):
    client, built = make_client(["", "补上的有效叙事。"])
    chunks = stream_chunks(build_narrate_node(client, mini_module), base_state(campaign))
    resets = [c for c in chunks if c.get("reset")]
    assert len(resets) == 2                       # 首次尝试 + repair 尝试各一次
    merged = merge_speakers(chunks)
    assert "".join(t for _, t in merged) == "补上的有效叙事。"


def test_ending_instruction_in_prompt(campaign, mini_module):
    client, built = make_client(["结局叙事。"])
    state = base_state(campaign, decision={"ending_reached": "e1", "checks": [],
                                           "clues_revealed": [], "proactive_npc_triggers": [],
                                           "scene_transition": None, "memory_queries": []})
    build_narrate_node(client, mini_module)(state)
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "揭开真相" in prompt                    # mini_module 结局 e1 的 condition
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_gm_narrate.py -q`
Expected: FAIL —— 新用例 `IndexError`（无 writer 上下文）或断言失败

- [ ] **Step 3: 修改 gm.py（narrate 实现替换）**

头部追加 import：
```python
from app.graph.narrative import IncrementalSegmenter, parse_segments
```

在 `build_narrate_node` 之前追加：
```python
def _stream_writer():
    """LangGraph custom stream writer；invoke/CLI 场景返回 no-op（版本差异兜底）。"""
    try:
        from langgraph.config import get_stream_writer
        return get_stream_writer()
    except Exception:
        return lambda _payload: None
```

`build_narrate_node` 的 `gm_narrate` 内部替换为（其余组装逻辑不变）：
```python
    def gm_narrate(state: GameState) -> dict:
        scene = module.scene(state["scene_id"])
        inputs_txt = "\n".join(
            f"- {i['player_id']}: {i['text']}" for i in state.get("player_inputs", [])
        ) or "（开场回合，无玩家行动）"
        opening_line = ""
        if state.get("is_opening"):
            opening_line = f"开场设定（请扩写为叙事）：\n{module.opening.narration}\n"
        ending_line = ""
        decision = state.get("decision") or {}
        if decision.get("ending_reached"):
            try:
                ending_line = (f"结局收束（{decision['ending_reached']}）："
                               f"{module.ending(decision['ending_reached']).condition}\n")
            except KeyError:
                ending_line = ""
        user = (
            f"{opening_line}{ending_line}"
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"玩家行动：\n{inputs_txt}\n"
            f"检定结果：\n{_check_lines(state)}\n"
            f"NPC 反应：\n{_reaction_lines(state, module)}\n"
            "请输出本回合的完整叙事。"
        )
        messages = [ChatMessage(role="system", content=NARRATE_SYSTEM),
                    ChatMessage(role="user", content=user)]
        writer = _stream_writer()
        last_error = ""
        for _ in range(2):  # 首次 + repair 重试 1 次（规格 §8）
            writer({"reset": True})
            segmenter = IncrementalSegmenter()
            parts: list[str] = []
            try:
                for delta in client.chat_stream("gm", messages, _ctx(state),
                                                cheap=_cheap(state)):
                    parts.append(delta)
                    for speaker, text in segmenter.feed(delta):
                        writer({"speaker": speaker, "text": text})
                for speaker, text in segmenter.flush():
                    writer({"speaker": speaker, "text": text})
                raw = "".join(parts)
                segs = parse_segments(raw)
                if segs:
                    return {"narration": raw,
                            "narration_segments": [{"speaker": s.speaker, "text": s.text}
                                                   for s in segs],
                            "error": None}
                last_error = "empty narration"
            except Exception as exc:
                last_error = str(exc)
            messages = messages + [ChatMessage(
                role="user",
                content=f"上次输出不合格（{last_error}）。请重新输出完整叙事，"
                        "NPC 台词必须带 [[npc:id]] 标记。")]
        return {"error": "narrate_failed", "degraded": {"narrate_failed": True},
                "narration": "", "narration_segments": []}
```

- [ ] **Step 4: 修改 replay.py（两处）**

`ReplayModels` 追加方法（与 `chat` 共用顺序断言）：
```python
    def chat_stream(self, messages, usage):
        if self.index >= len(self.entries):
            raise IndexError("replay entries exhausted")
        entry = self.entries[self.index]
        self.index += 1
        assert entry["model"] == self._current_model, (
            f"回放顺序错位：录制为 {entry['model']}，本次请求路由到 {self._current_model}")
        self.calls.append({"model": self._current_model,
                           "messages": [m.model_dump() for m in messages]})
        usage.tokens_in, usage.tokens_out = 10, 20
        text = entry["text"]
        for i in range(0, len(text), 8):
            yield text[i:i + 8]
```

`make_recording_factory` 的 `_RecordingModel` 追加：
```python
            def chat_stream(self, messages, usage):
                text = ""
                for delta in inner.chat_stream(messages, usage):
                    text += delta
                    yield delta
                collected.append({"model": model, "text": text})
```

- [ ] **Step 5: 验证通过（含 M2 回放与图回归）**

Run: `cd backend; uv run pytest tests/graph tests/llm -q`
Expected: PASS —— 新增流式用例 + M2 全部 graph 用例（含 `test_replay_smoke.py`）全绿（narrate 改走 `chat_stream` 后 ReplayModels 消耗计数不变）

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/nodes/gm.py backend/tests/harness/replay.py backend/tests/graph/test_gm_narrate.py
git commit -m "feat(graph): streaming narrate via custom stream writer with replay support"
```

---

### Task M3-4: 结局与线索机制（运行时触发）

**Files:**
- Modify: `backend/app/graph/schemas.py`（GmDecision 扩展两个字段）
- Modify: `backend/app/graph/state.py`（GameState.ending_reached）
- Modify: `backend/app/graph/nodes/gm.py`（DECIDE_SYSTEM、validate 校验模块引用）
- Modify: `backend/app/graph/nodes/turn.py`（post_turn 线索/结局；fallback / wait_input 清空 ending_reached）
- Modify: `backend/app/graph/main.py`（传 module、结局条件边）
- Modify: `backend/app/cli.py`（结局提示）
- Test: `backend/tests/graph/test_endings.py`

**Interfaces:**
- Consumes: `Module.clues/endings`（M2 Task 4）、`build_post_turn_node`（M2 Task 16）、`build_validate_node`（M2 Task 17）
- Produces：
  - `GmDecision` 新增：`clues_revealed: list[str] = []`、`ending_reached: str | None = None`
  - `GameState` 新增：`ending_reached: str | None`
  - `build_validate_node(client, module=None)`：module 提供时校验 `clues_revealed` 的每个 id 在 `module.clues`、`ending_reached` 在 `module.endings`；不合法 → 反馈 repair 重试 1 次；仍失败 → `decision_invalid`（M2 的两个调用点行为不变）
  - `build_post_turn_node(repo, memory, module=None)`：对每个新线索写 `clue` 事件（`payload={"clue_id", "text"}`，text 为模块线索内容）并 `memory.write_event(MemoryEvent(type="clue"))`；返回增加 `"ending_reached"`
  - 主图：`post_turn` → `_route_after_post_turn`（`ending_reached` 为真 → `END`，否则 → `wait_input`）
  - CLI：`play_loop` 检测到 `ending_reached` 时打印结局并返回 `"ended"`

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_endings.py`：
```python
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.content.schema import Module
from app.graph.main import build_game_graph
from app.graph.nodes.gm import build_validate_node
from app.graph.nodes.turn import build_post_turn_node, fallback
from app.graph.schemas import parse_decision_json
from app.llm.client import ChatMessage, LLMClient
from app.memory.base import MemoryEvent
from app.llm.fakes import FakeLLM

MODULE_WITH_CLUE = {
    "meta": {"id": "clue_mod", "title": "线索模组"},
    "opening": {"narration": "开场", "scene_id": "a"},
    "scenes": [{"id": "a", "name": "A", "npcs": [], "exits": [], "clues": ["c1"]}],
    "npcs": [],
    "clues": [{"id": "c1", "content": "壁炉灰里有烧焦的纸片", "unlocks": []}],
    "endings": [{"id": "ed", "scene": "a", "condition": "烧掉契约"}],
}


def test_decision_defaults_include_new_fields():
    d = parse_decision_json('{"intent_summary": "x"}')
    assert d.clues_revealed == [] and d.ending_reached is None


def make_client(script):
    rows, built = [], {}
    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script))
        return built[model]
    class Sink:
        def record_usage(self, *a, **kw):
            rows.append(kw)
    settings = Settings(gm_model="qwen3.8-flash", cheap_model="alt-cheap-model")
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "alt-cheap-model": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    return LLMClient(settings, pricing, usage_sink=Sink(), model_factory=factory), built


def test_validate_repairs_unknown_clue(campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    bad = '{"intent_summary": "x", "clues_revealed": ["ghost_clue"]}'
    good = '{"intent_summary": "x", "clues_revealed": ["c1"]}'
    client, built = make_client([good])
    upd = build_validate_node(client, module)(
        {"decision_raw": bad, "budget_level": "ok", "campaign_id": "c",
         "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] is None and upd["decision"]["clues_revealed"] == ["c1"]
    assert "ghost_clue" in built["qwen3.8-flash"].calls[0][1].content   # repair 反馈包含非法引用


def test_validate_gives_up_on_unknown_ending(campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    bad = '{"intent_summary": "x", "ending_reached": "nope"}'
    client, built = make_client([bad])
    upd = build_validate_node(client, module)(
        {"decision_raw": bad, "budget_level": "ok", "campaign_id": "c",
         "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] == "decision_invalid"
    assert built["qwen3.8-flash"].calls[0][1].role == "user"


def test_post_turn_writes_clue_event_and_ending(repo, campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    written: list[MemoryEvent] = []
    class SpyMemory:
        def update_summaries(self, *a): ...
        def write_event(self, campaign_id, branch_id, event):
            written.append(event)
    upd = build_post_turn_node(repo, SpyMemory(), module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id, "turn_id": 2,
        "scene_id": "a", "npc_attitudes": {}, "narration": "叙事",
        "narration_segments": [{"speaker": "gm", "text": "叙事"}],
        "decision": {"clues_revealed": ["c1"], "ending_reached": "ed",
                     "checks": [], "proactive_npc_triggers": [],
                     "scene_transition": None, "memory_queries": []},
    })
    assert upd["ending_reached"] == "ed" and upd["turn_id"] == 3
    import json
    clues = repo.list_events(campaign.id, campaign.active_branch_id, types=["clue"])
    assert len(clues) == 1
    payload = json.loads(clues[0].payload_json)
    assert payload["clue_id"] == "c1" and "烧焦的纸片" in payload["text"]
    assert written and written[0].type == "clue"


def test_fallback_clears_ending_reached():
    upd = fallback({"error": "x", "ending_reached": "ed"})
    assert upd["ending_reached"] is None


def test_graph_ends_on_ending(repo, campaign, mini_module):
    decide_ending = ('{"intent_summary": "终结", "checks": [], "proactive_npc_triggers": [],'
                     ' "scene_transition": null, "memory_queries": [],'
                     ' "clues_revealed": [], "ending_reached": "e1"}')
    script = {"qwen3.8-flash": [
        '{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
        ' "scene_transition": null, "memory_queries": []}',
        "开场叙事。", decide_ending, "尘埃落定，故事就此收束。"]}
    queues = {m: list(v) for m, v in script.items()}
    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    client = LLMClient(Settings(), pricing, usage_sink=repo, model_factory=factory)
    from app.llm.usage import BudgetGuard
    from app.memory.journal import JournalMemory
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(Settings()), MemorySaver())
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1,
                                 "inputs": [{"player_id": "p1", "character_id": "pc_p1",
                                             "text": "终结这一切"}],
                                 "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ()                       # 结局：图结束，不再开输入窗口
    assert snap.values["ending_reached"] == "e1"
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_endings.py -q`
Expected: FAIL —— `TypeError: build_validate_node() takes 1 positional argument`

- [ ] **Step 3: 实现修改**

`schemas.py` 的 `GmDecision` 追加两个字段：
```python
class GmDecision(BaseModel):
    intent_summary: str = ""
    checks: list[CheckRequest] = Field(default_factory=list)
    proactive_npc_triggers: list[NpcTrigger] = Field(default_factory=list)
    scene_transition: SceneTransition | None = None
    memory_queries: list[str] = Field(default_factory=list)
    clues_revealed: list[str] = Field(default_factory=list)
    ending_reached: str | None = None
```

`state.py` 的 `GameState` 追加：
```python
    ending_reached: str | None
```

`nodes/gm.py`：
- `DECIDE_SYSTEM` 字段说明追加（在 `memory_queries(字符串数组)。\n` 之前插入）：
```python
    'clues_revealed(数组，元素为线索 id，仅当本回合玩家明确获得线索时填写)、'
    'ending_reached(null 或模块给定结局 id，仅当叙事故意收束到结局时填写)、'
```
- `build_validate_node` 改为（新增 module 参数与引用校验）：
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

    def validate_decision(state: GameState) -> dict:
        raw = state.get("decision_raw", "")
        repair_msg = ""
        for _ in range(2):  # 首次 + repair 重试恰好 1 次（规格 §8）
            try:
                decision = parse_decision_json(raw)
                ref_error = _check_refs(decision)
                if ref_error is None:
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
        return {"error": "decision_invalid", "decision": None,
                "degraded": {"decision_invalid": True}}
```
（注意：与原实现相比，repair 现在只发生一次，且引用错误与解析错误共用同一重试路径；`test_gm_decide.py` 的既有用例语义不变。）

`nodes/turn.py`：
- `build_post_turn_node` 改为：
```python
def build_post_turn_node(repo, memory, module=None):
    def post_turn(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        narration = state.get("narration", "")
        if narration:
            repo.add_event(campaign_id, branch_id, turn_id, type="narration",
                           payload={"text": narration,
                                    "segments": state.get("narration_segments", [])})
        decision = state.get("decision") or {}
        # 场景移动回合：写 scene_changed 技术事件（持久化 + 供前端切换场景与 NPC 区，§4.3）
        # get_state_at 语义为「≤ turn_id 的最新快照」：本轮快照随后才写入，此刻取到的
        # 正是 intake 读过的回合初始状态（单写者：生产代码仅本节点写快照）
        new_scene = state.get("scene_id")
        old_scene = (repo.get_state_at(campaign_id, branch_id, turn_id) or {}).get("scene_id")
        if old_scene and new_scene and old_scene != new_scene:
            transition = decision.get("scene_transition") or {}
            repo.add_event(campaign_id, branch_id, turn_id, type="scene_changed",
                           payload={"from_scene": old_scene, "to_scene": new_scene,
                                    "reason": transition.get("reason") or ""})
        for clue_id in decision.get("clues_revealed", []):
            content = ""
            if module is not None:
                try:
                    content = module.clue(clue_id).content
                except KeyError:
                    content = ""
            repo.add_event(campaign_id, branch_id, turn_id, type="clue",
                           payload={"clue_id": clue_id, "text": content})
            memory.write_event(campaign_id, branch_id,
                               MemoryEvent(type="clue", text=content or clue_id,
                                           turn_id=turn_id))
        repo.append_state(campaign_id, branch_id, turn_id,
                          {"scene_id": new_scene,
                           "npc_attitudes": state.get("npc_attitudes", {})})
        memory.update_summaries(campaign_id, branch_id, turn_id)
        return {"turn_id": turn_id + 1, "decision": None,
                "ending_reached": decision.get("ending_reached")}

    return post_turn
```
头部 import 追加：`from app.memory.base import MemoryEvent`（若 `module.clue` 方法名与 M2 不一致，按 M2 实际实现用 `module.clues` 列表查找同义替换）。
- `fallback` 的返回 dict 追加 `"ending_reached": None`；`wait_input` 的清空 dict 追加 `"ending_reached": None`。

`nodes/gm.py` 的 `parse_segments` 相关无改动；`Module` 若没有 `clue(id)` 方法则在 `content/schema.py` 的 Module 追加：
```python
    def clue(self, clue_id: str) -> Clue:
        for c in self.clues:
            if c.id == clue_id:
                return c
        raise KeyError(clue_id)
```

`graph/main.py`：
```python
def _route_after_post_turn(state: GameState) -> str:
    return "end" if state.get("ending_reached") else "wait_input"

# build_game_graph 内三处修改：
    g.add_node("validate", build_validate_node(client, module))
    g.add_node("post_turn", build_post_turn_node(repo, memory, module))
    g.add_conditional_edges("post_turn", _route_after_post_turn,
                            {"end": END, "wait_input": "wait_input"})
# 删除原 g.add_edge("post_turn", "wait_input")
```

`cli.py` 的 `play_loop`：在渲染叙事之后、`if not interrupts:` 之前插入：
```python
        if result.get("ending_reached"):
            print_fn(f"（结局已达：{result['ending_reached']}）")
            return "ended"
```

- [ ] **Step 4: 验证通过（含 M2 回归）**

Run: `cd backend; uv run pytest tests/graph tests/test_cli.py -q`
Expected: PASS —— 新用例 + M2 全部 graph/cli 用例（validate 的 repair 语义、post_turn 双参调用等）保持全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph backend/app/cli.py backend/tests/graph/test_endings.py
git commit -m "feat(graph): runtime clue reveal and ending trigger with graph termination"
```

---

### Task M3-4A: NPC 好感度演化（Phase 1：队伍级，追加任务）

> **来源**：`docs/superpowers/specs/2026-09-26-npc-attitude-evolution-design.md`（2026-10-01 决策并入 M3）。
> **执行位置**：M3-4 完成之后 —— post_turn 的 module 注入已就位，本任务只做单点追加；**既有回放基线逐字不变是硬验收**。

**Files:**
- Modify: `backend/app/graph/schemas.py`（新增 AttitudeDelta；GmDecision 加 attitude_deltas）
- Create: `backend/app/rules/attitude.py`（常量 + 纯函数）
- Modify: `backend/app/graph/nodes/turn.py`（post_turn 应用 + `attitude` 事件）
- Modify: `backend/app/graph/nodes/gm.py`（DECIDE_SYSTEM 字段说明）
- Test: `backend/tests/rules/test_attitude.py`（新建）、`backend/tests/graph/test_attitude.py`（新建）、`backend/tests/graph/test_gm_decide.py`（追加 1 个用例）

**Interfaces:**
- Consumes: `GmDecision`、`build_post_turn_node(repo, memory, module=None)`（M3-4 形态）、`SqliteRepository.add_event(..., visibility=)`（M2）
- Produces：
  - `AttitudeDelta{npc_id: str, delta: int, reason: str = ""}`；`GmDecision.attitude_deltas: list[AttitudeDelta] = Field(default_factory=list)`
  - `app.rules.attitude`：`MAX_DELTAS_PER_TURN=2`、`MAX_DELTA_ABS=15`、`ATTITUDE_MIN, ATTITUDE_MAX = 0, 100`、`DEFAULT_ATTITUDE=50`；`apply_attitude_deltas(current: dict[str, int], deltas: list[dict] | None, present_npcs: set[str]) -> tuple[dict[str, int], list[dict]]`（纯函数，不抛异常、不修改入参）
  - 事件契约：`type="attitude"`、`payload={"npc_id","old","new","delta","reason"}`（delta 为截断后净变化）、`visibility="all"`
  - `post_turn` 返回值：有变更时携带 `"npc_attitudes"`（新表）；无变更 / `module=None` 时不含该键

- [ ] **Step 1: 写失败测试（rules 纯函数全覆盖）**

`backend/tests/rules/test_attitude.py`：
```python
from app.rules.attitude import (ATTITUDE_MAX, ATTITUDE_MIN, MAX_DELTA_ABS,
                                apply_attitude_deltas)


def item(npc_id, delta, reason=""):
    return {"npc_id": npc_id, "delta": delta, "reason": reason}


def test_present_only_and_keeps_input_intact():
    current = {"guard": 40, "barkeep": 60}
    attitudes, changes = apply_attitude_deltas(
        current, [item("guard", -10, "被威胁"), item("ghost", 5)], {"guard", "barkeep"})
    assert attitudes["guard"] == 30 and attitudes["barkeep"] == 60
    assert current == {"guard": 40, "barkeep": 60}          # 不修改入参
    assert changes == [{"npc_id": "guard", "old": 40, "new": 30,
                        "delta": -10, "reason": "被威胁"}]


def test_slice_first_two_before_filtering():
    # 先保序取前 2 条再逐条过滤：非法的第 1 条占掉一个名额（写死语义）
    attitudes, changes = apply_attitude_deltas(
        {"a": 50, "b": 50, "c": 50},
        [item("ghost", 5), item("a", 5), item("b", 5), item("c", 5)], {"a", "b", "c"})
    assert [c["npc_id"] for c in changes] == ["a"]


def test_non_int_delta_dropped():
    for bad in (True, 3.5, "5", None):
        attitudes, changes = apply_attitude_deltas({"a": 50}, [item("a", bad)], {"a"})
        assert changes == [] and attitudes == {"a": 50}


def test_non_dict_item_skipped():
    attitudes, changes = apply_attitude_deltas({"a": 50}, [None, item("a", 5)], {"a"})
    assert attitudes["a"] == 55 and len(changes) == 1


def test_single_delta_truncated_then_merged_net_truncated():
    attitudes, changes = apply_attitude_deltas({"a": 50}, [item("a", 100)], {"a"})
    assert attitudes["a"] == 50 + MAX_DELTA_ABS and changes[0]["delta"] == MAX_DELTA_ABS
    attitudes, changes = apply_attitude_deltas(      # 合并 10+10=20 → 净再截断为 15
        {"a": 50}, [item("a", 10), item("a", 10)], {"a"})
    assert attitudes["a"] == 50 + MAX_DELTA_ABS and changes[0]["delta"] == MAX_DELTA_ABS


def test_same_npc_merges_and_keeps_first_reason():
    attitudes, changes = apply_attitude_deltas(
        {"a": 50}, [item("a", 5, "甲"), item("a", -2, "乙")], {"a"})
    assert attitudes["a"] == 53 and len(changes) == 1
    assert changes[0]["reason"] == "甲"


def test_clamped_to_bounds_delta_records_truncated_net():
    attitudes, changes = apply_attitude_deltas({"a": 95}, [item("a", 15)], {"a"})
    assert attitudes["a"] == ATTITUDE_MAX and changes[0]["delta"] == MAX_DELTA_ABS
    attitudes, changes = apply_attitude_deltas({"a": 5}, [item("a", -15)], {"a"})
    assert attitudes["a"] == ATTITUDE_MIN


def test_net_zero_or_no_actual_change_records_nothing():
    attitudes, changes = apply_attitude_deltas(
        {"a": 50}, [item("a", 5), item("a", -5)], {"a"})   # 净 0
    assert changes == [] and attitudes == {"a": 50}
    attitudes, changes = apply_attitude_deltas({"a": 100}, [item("a", 15)], {"a"})  # 卡边
    assert changes == [] and attitudes == {"a": 100}


def test_missing_attitude_defaults_to_50():
    attitudes, changes = apply_attitude_deltas({}, [item("a", 10)], {"a"})
    assert attitudes["a"] == 60 and changes[0]["old"] == 50


def test_non_list_deltas_treated_as_empty():
    attitudes, changes = apply_attitude_deltas({"a": 50}, None, {"a"})
    assert (attitudes, changes) == ({"a": 50}, [])
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/rules/test_attitude.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.rules.attitude'`

- [ ] **Step 3: 实现 rules 纯函数**

`backend/app/rules/attitude.py`：
```python
"""好感度硬边界：纯函数，写死常量；LLM 只说方向与理由，代码决定数值（设计 2026-09-26）。"""
MAX_DELTAS_PER_TURN = 2            # 保序取前 2 条
MAX_DELTA_ABS = 15                 # 单条与净变化双重上限
ATTITUDE_MIN, ATTITUDE_MAX = 0, 100
DEFAULT_ATTITUDE = 50


def _truncate(value: int) -> int:
    return max(-MAX_DELTA_ABS, min(MAX_DELTA_ABS, value))


def apply_attitude_deltas(
    current: dict[str, int],
    deltas: list[dict] | None,     # decision["attitude_deltas"] 原始 JSON
    present_npcs: set[str],        # 当前场景在场 npc_id 集合
) -> tuple[dict[str, int], list[dict]]:
    """返回 (新态度表副本, 变更记录)。纯函数：不抛异常、不修改入参、净 0/无变化不动。

    语义（写死）：保序取前 2 条 → 不在场/非 str npc_id 丢弃 → 非 int delta（含 bool）
    丢弃 → 单条截断到 ±15 → 同 npc 合并求和后净变化再截断 → clamp [0,100] →
    net==0 或 new==old 不更新不记录；记录取该 npc 首条 reason。
    """
    result = dict(current)
    if not isinstance(deltas, list):
        return result, []
    merged: dict[str, int] = {}
    first_reason: dict[str, str] = {}
    for entry in deltas[:MAX_DELTAS_PER_TURN]:
        if not isinstance(entry, dict):
            continue
        npc_id, raw = entry.get("npc_id"), entry.get("delta")
        if not isinstance(npc_id, str) or npc_id not in present_npcs:
            continue
        if isinstance(raw, bool) or not isinstance(raw, int):
            continue
        merged[npc_id] = merged.get(npc_id, 0) + _truncate(raw)
        first_reason.setdefault(npc_id, str(entry.get("reason") or ""))
    changes: list[dict] = []
    for npc_id, net in merged.items():
        net = _truncate(net)
        old = result.get(npc_id, DEFAULT_ATTITUDE)
        new = max(ATTITUDE_MIN, min(ATTITUDE_MAX, old + net))
        if net == 0 or new == old:
            continue
        result[npc_id] = new
        changes.append({"npc_id": npc_id, "old": old, "new": new,
                        "delta": net, "reason": first_reason[npc_id]})
    return result, changes
```

Run: `cd backend; uv run pytest tests/rules/test_attitude.py -q`
Expected: PASS —— 10 用例全绿（截断/合并/在场过滤/非 int/净 0/卡边/默认值/非列表/非 dict 分支全覆盖）

- [ ] **Step 4: 写失败测试（提示词契约 / post_turn 集成 / 正向链路）**

`tests/graph/test_gm_decide.py` 末尾追加：
```python
def test_decide_system_documents_attitude_deltas():
    """好感度契约：LLM 只说方向与理由，数值由代码截断（设计 2026-09-26）。"""
    assert "attitude_deltas" in DECIDE_SYSTEM
```

新建 `backend/tests/graph/test_attitude.py`：
```python
import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.graph.main import build_game_graph
from app.graph.nodes.turn import build_post_turn_node
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
OPENING_NARR = "雾气贴着地面爬行。"
THREATEN_DECIDE = ('{"intent_summary": "威胁守卫", "checks": [], "proactive_npc_triggers": [],'
                   ' "scene_transition": null, "memory_queries": [],'
                   ' "attitude_deltas": [{"npc_id": "guard", "delta": -10, "reason": "出言威胁"},'
                   ' {"npc_id": "barkeep", "delta": 5, "reason": "不在场应被丢弃"}]}')


class SpyMemory:
    def update_summaries(self, *args): ...


def test_post_turn_applies_present_delta_only(repo, campaign, mini_module):
    upd = build_post_turn_node(repo, SpyMemory(), mini_module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id, "turn_id": 2,
        "scene_id": "gate", "npc_attitudes": {"guard": 40, "barkeep": 60},
        "narration": "叙事", "narration_segments": [],
        "decision": {"attitude_deltas": [{"npc_id": "guard", "delta": -10, "reason": "出言威胁"},
                                         {"npc_id": "barkeep", "delta": 5, "reason": "不在场"}],
                     "clues_revealed": [], "ending_reached": None},
    })
    assert upd["npc_attitudes"] == {"guard": 30, "barkeep": 60}   # 仅在场者变化，返回值携带新表
    assert upd["turn_id"] == 3
    rows = repo.list_events(campaign.id, campaign.active_branch_id, types=["attitude"])
    assert len(rows) == 1 and rows[0].visibility == "all"
    assert json.loads(rows[0].payload_json) == {"npc_id": "guard", "old": 40, "new": 30,
                                                "delta": -10, "reason": "出言威胁"}
    snap = repo.get_state_at(campaign.id, campaign.active_branch_id, 2)
    assert snap["npc_attitudes"] == {"guard": 30, "barkeep": 60}  # 快照自动持久化


def test_post_turn_invalid_deltas_do_not_break_turn(repo, campaign, mini_module):
    upd = build_post_turn_node(repo, SpyMemory(), mini_module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id, "turn_id": 2,
        "scene_id": "gate", "npc_attitudes": {"guard": 40},
        "narration": "", "narration_segments": [],
        "decision": {"attitude_deltas": [{"npc_id": "ghost", "delta": 5, "reason": "幻觉"},
                                         {"npc_id": "guard", "delta": "大", "reason": "类型错"}],
                     "clues_revealed": [], "ending_reached": None},
    })
    assert upd["turn_id"] == 3 and "npc_attitudes" not in upd   # 无变更：不携带、无事件、不异常
    assert repo.list_events(campaign.id, campaign.active_branch_id, types=["attitude"]) == []
    snap = repo.get_state_at(campaign.id, campaign.active_branch_id, 2)
    assert snap["npc_attitudes"] == {"guard": 40}


def _env(repo, mini_module, script):
    settings = Settings(gm_model="qwen3.8-flash", cheap_model="qwen3.8-flash",
                        npc_model="deepseek-flash", extractor_model="qwen3.8-flash")
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.000113, output_per_1k=0.00038),
        "deepseek-flash": PricingEntry(input_per_1k=0.00028, output_per_1k=0.00113)})
    queues = {m: list(v) for m, v in script.items()}
    built: list[FakeLLM] = []

    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        llm = FakeLLM([items.pop(0)] if items else [])
        built.append(llm)
        return llm

    client = LLMClient(settings, pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    return graph, built


def test_attitude_change_reaches_next_turn_prompt(repo, campaign, mini_module):
    graph, built = _env(repo, mini_module, {"qwen3.8-flash": [
        OPENING_DECIDE, OPENING_NARR, THREATEN_DECIDE, "守卫冷冷地侧过身。",
        OPENING_DECIDE, "你看见他攥紧了枪带。"]})
    branch = repo.get_branch(campaign.active_branch_id)
    cfg = {"configurable": {"thread_id": repo.thread_id_for(branch)}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1, "inputs": [
        {"player_id": "p1", "character_id": "pc_1", "text": "我压低声音威胁守卫放行"}],
        "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["npc_attitudes"]["guard"] == 30
    rows = repo.list_events(campaign.id, campaign.active_branch_id, types=["attitude"])
    assert len(rows) == 1 and json.loads(rows[0].payload_json)["delta"] == -10

    graph.invoke(Command(resume={"turn_id": 2, "inputs": [
        {"player_id": "p1", "character_id": "pc_1", "text": "我径直朝酒馆走去"}],
        "skipped": []}), cfg)
    assert graph.get_state(cfg).next == ("wait_input",)
    prompt = built[4].calls[0][1].content        # 第 5 次 qwen 调用 = 回合 2 的 decide
    assert "当前态度 30" in prompt               # 变化自下一回合起生效
```

Run: `cd backend; uv run pytest tests/graph/test_attitude.py tests/graph/test_gm_decide.py -q`
Expected: FAIL —— 集成用例 `KeyError: 'npc_attitudes'`、正向链路 `assert 30 == 40`、提示词契约断言失败；容错用例此时通过（无变更路径与旧行为重合，属预期）

- [ ] **Step 5: 实现 schemas / 提示词 / post_turn 应用**

`schemas.py`：`SceneTransition` 之后、`GmDecision` 之前新增：
```python
class AttitudeDelta(BaseModel):
    npc_id: str
    delta: int                    # 建议 -15..15；代码最终截断
    reason: str = ""
```

`GmDecision` 追加字段：
```python
    attitude_deltas: list[AttitudeDelta] = Field(default_factory=list)   # 代码最多取前 2 条
```

`nodes/gm.py`：`DECIDE_SYSTEM` 在 `'memory_queries(字符串数组)。\n'` 之前插入一行：
```python
    'attitude_deltas(数组，元素 {"npc_id","delta"(整数),"reason"}，仅当玩家行为在本回合实质影响了某在场 NPC 对你们的态度时给出，最多 2 条，否则空数组；npc_id 只能用当前场景内列出的；delta 按行为严重程度取 -15..15，拿不准就不给)、'
```

`nodes/turn.py`：头部 import 追加 `from app.rules.attitude import apply_attitude_deltas`；`build_post_turn_node` 替换为：
```python
def build_post_turn_node(repo, memory, module=None):
    def post_turn(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        narration = state.get("narration", "")
        if narration:
            repo.add_event(campaign_id, branch_id, turn_id, type="narration",
                           payload={"text": narration,
                                    "segments": state.get("narration_segments", [])})
        decision = state.get("decision") or {}
        # 场景移动回合：写 scene_changed 技术事件（持久化 + 供前端切换场景与 NPC 区，§4.3）
        # get_state_at 语义为「≤ turn_id 的最新快照」：本轮快照随后才写入，此刻取到的
        # 正是 intake 读过的回合初始状态（单写者：生产代码仅本节点写快照）
        new_scene = state.get("scene_id")
        old_scene = (repo.get_state_at(campaign_id, branch_id, turn_id) or {}).get("scene_id")
        if old_scene and new_scene and old_scene != new_scene:
            transition = decision.get("scene_transition") or {}
            repo.add_event(campaign_id, branch_id, turn_id, type="scene_changed",
                           payload={"from_scene": old_scene, "to_scene": new_scene,
                                    "reason": transition.get("reason") or ""})
        for clue_id in decision.get("clues_revealed", []):
            content = ""
            if module is not None:
                try:
                    content = module.clue(clue_id).content
                except KeyError:
                    content = ""
            repo.add_event(campaign_id, branch_id, turn_id, type="clue",
                           payload={"clue_id": clue_id, "text": content})
            memory.write_event(campaign_id, branch_id,
                               MemoryEvent(type="clue", text=content or clue_id,
                                           turn_id=turn_id))
        # M3-4A：好感度应用（单点写入；module 未注入时零行为变化）
        attitudes = state.get("npc_attitudes", {})
        attitude_upd: dict = {}
        if module is not None:
            try:
                present = set(module.scene(new_scene).npcs)
                attitudes, changes = apply_attitude_deltas(
                    attitudes, decision.get("attitude_deltas", []), present)
                for change in changes:
                    repo.add_event(campaign_id, branch_id, turn_id, type="attitude",
                                   payload=change, visibility="all")
                if changes:
                    attitude_upd = {"npc_attitudes": attitudes}
            except Exception:      # 容错（设计 §4）：态度独立于回合成败，异常不更新
                attitudes = state.get("npc_attitudes", {})
                attitude_upd = {}
        repo.append_state(campaign_id, branch_id, turn_id,
                          {"scene_id": new_scene, "npc_attitudes": attitudes})
        memory.update_summaries(campaign_id, branch_id, turn_id)
        return {"turn_id": turn_id + 1, "decision": None,
                "ending_reached": decision.get("ending_reached"), **attitude_upd}

    return post_turn
```

- [ ] **Step 6: 跑目标测试**

Run: `cd backend; uv run pytest tests/rules/test_attitude.py tests/graph/test_attitude.py tests/graph/test_gm_decide.py -q`
Expected: PASS —— 新增用例全绿；`test_gm_decide.py` 既有 7 例不受影响

- [ ] **Step 7: 兼容硬验收（全量回归）**

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 既有全部用例（含 `tests/graph/test_replay_smoke.py` 回放基线与 `tests/graph/test_post_turn.py` 的 `module=None` 两参调用路径）逐字不变；无 fixture 改动

- [ ] **Step 8: Commit**

```bash
git add backend/app/rules/attitude.py backend/app/graph/schemas.py backend/app/graph/nodes/turn.py backend/app/graph/nodes/gm.py backend/tests/rules/test_attitude.py backend/tests/graph/test_attitude.py backend/tests/graph/test_gm_decide.py
git commit -m "feat(graph): NPC attitude evolution with bounded deltas and attitude events"
```

---

### Task M3-5: 模组注册表 + 玩家仓储 + 战役 REST（含最小 create_app）

**Files:**
- Modify: `backend/pyproject.toml`（依赖）
- Modify: `backend/app/config.py`（Settings 新字段 + env）
- Create: `backend/app/content/registry.py`
- Modify: `backend/app/storage/repo.py`（玩家方法 + `latest_snapshot`）
- Create: `backend/app/api/__init__.py`（空）、`backend/app/api/routes.py`、`backend/app/api/app.py`
- Test: `backend/tests/content/test_registry.py`、`backend/tests/storage/test_players.py`、`backend/tests/api/test_campaigns_api.py`

**Interfaces:**
- Consumes: `load_module`（M2 Task 6）、`SqliteRepository`（M2 Task 7/8/9）、`make_default_character`（M2 Task 3）
- Produces：
  - `list_modules(modules_dir: str) -> list[dict]`（`{id, title, version, path}`，按 id 排序）；`find_module_path(modules_dir, module_id) -> Path`（未找到 `KeyError`）
  - `SqliteRepository.add_player(campaign_id, display_name) -> Player`（`join_token = secrets.token_urlsafe(8)`）；`list_players(campaign_id)`；`get_player(player_id) -> Player | None`；`get_player_by_token(token) -> Player | None`；`latest_snapshot(campaign_id, branch_id) -> StateSnapshotRow | None`
  - `AppDeps(settings, repo, model_factory=None, manager=None)`；`create_app(deps) -> FastAPI`（本任务只挂 REST + `/healthz`；T11 扩展）
  - REST：`GET /api/modules`；`POST /api/campaigns {module_id, title, player_name="调查员"}` → `{campaign_id, branch_id, player_id, character_id}`；`GET /api/campaigns`；`GET /api/campaigns/{id}`（含 scene/turn/characters/players/clues/cost）

- [ ] **Step 1: pyproject 与 config 修改**

`backend/pyproject.toml` `dependencies` 追加 `"fastapi", "uvicorn[standard]"`；`[dependency-groups] dev` 追加 `"httpx", "pytest-asyncio"`。然后 `cd backend; uv sync`。

`backend/app/config.py` 的 `Settings` 追加字段与 property：
```python
    modules_dir: str = "../modules"
    cors_origins: str = "http://localhost:5173"
    single_player_debounce_seconds: float = 2.0
    ws_replay_size: int = 500

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
```
`load_settings()` 追加 env：`modules_dir=os.environ.get("ENSEMBLE_MODULES_DIR", "../modules")`、`pricing_path=os.environ.get("ENSEMBLE_PRICING_PATH", "config/pricing.yaml")`（默认值不变；SessionManager 会用它加载定价，测试与部署可用环境变量指向绝对路径）。

- [ ] **Step 2: 写失败测试**

`backend/tests/content/test_registry.py`：
```python
from pathlib import Path
import pytest
from app.content.registry import find_module_path, list_modules

TWO_MODULES = {
    "m_a.yaml": 'meta: { id: aaa, title: 甲 }\nopening: { narration: x, scene_id: s }\n'
                'scenes: [{ id: s, name: S, npcs: [], exits: [] }]\nnpcs: []\nclues: []\n'
                'endings: [{ id: e, scene: s, condition: c }]\n',
    "m_b.yaml": 'meta: { id: bbb, title: 乙 }\nopening: { narration: x, scene_id: s }\n'
                'scenes: [{ id: s, name: S, npcs: [], exits: [] }]\nnpcs: []\nclues: []\n'
                'endings: [{ id: e, scene: s, condition: c }]\n',
}

@pytest.fixture
def moddir(tmp_path):
    for name, text in TWO_MODULES.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path

def test_list_modules_sorted(moddir):
    mods = list_modules(str(moddir))
    assert [m["id"] for m in mods] == ["aaa", "bbb"]
    assert mods[0]["title"] == "甲" and Path(mods[0]["path"]).exists()

def test_find_module_path_missing_raises(moddir):
    assert find_module_path(str(moddir), "bbb").name == "m_b.yaml"
    with pytest.raises(KeyError):
        find_module_path(str(moddir), "nope")
```

`backend/tests/storage/test_players.py`：
```python
def test_add_and_lookup_player(repo, campaign):
    p = repo.add_player(campaign.id, "张三")
    assert p.join_token and len(p.join_token) >= 8
    assert repo.get_player(p.id).display_name == "张三"
    assert repo.get_player_by_token(p.join_token).id == p.id
    assert repo.get_player("ghost") is None
    assert [x.id for x in repo.list_players(campaign.id)] == [p.id]
```

`backend/tests/api/test_campaigns_api.py`：
```python
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
    engine = make_engine(str(tmp_path / "api.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "api.db"),
                        modules_dir=str(ROOT / "modules"))
    return TestClient(create_app(AppDeps(settings=settings, repo=repo))), repo

def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}

def test_modules_listed(client):
    c, _ = client
    ids = [m["id"] for m in c.get("/api/modules").json()]
    assert "misty_hollow" in ids

def test_create_campaign_creates_player_and_character(client):
    c, repo = client
    r = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                       "title": "初探", "player_name": "张三"})
    assert r.status_code == 200
    data = r.json()
    assert data["campaign_id"] and data["player_id"] and data["character_id"]
    chars = repo.list_characters_at(data["campaign_id"], data["branch_id"], 10**9)
    assert chars[0]["name"] == "张三" and chars[0]["player_id"] == data["player_id"]

def test_get_campaign_detail(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "初探"}).json()["campaign_id"]
    r = c.get(f"/api/campaigns/{cid}")
    d = r.json()
    assert d["title"] == "初探" and d["scene_id"] == "square" and d["turn_id"] == 0
    assert len(d["players"]) == 1 and d["characters"]

def test_get_campaign_404(client):
    c, _ = client
    assert c.get("/api/campaigns/ghost").status_code == 404
```

- [ ] **Step 3: 验证失败**

Run: `cd backend; uv run pytest tests/content/test_registry.py tests/storage/test_players.py tests/api/test_campaigns_api.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 4: 实现 registry.py / repo 追加 / api 三文件**

`backend/app/content/registry.py`：
```python
"""模组注册表：扫描目录、按 id 查找（api 层用）。"""
from pathlib import Path

import yaml

from app.content.loader import load_module


def _iter_module_files(modules_dir: str):
    return sorted(Path(modules_dir).glob("*.yaml"))


def list_modules(modules_dir: str) -> list[dict]:
    out = []
    for p in _iter_module_files(modules_dir):
        meta = yaml.safe_load(p.read_text(encoding="utf-8"))["meta"]
        out.append({"id": meta["id"], "title": meta.get("title", meta["id"]),
                    "version": str(meta.get("version", "")), "path": str(p)})
    out.sort(key=lambda m: m["id"])
    return out


def find_module_path(modules_dir: str, module_id: str) -> Path:
    for p in _iter_module_files(modules_dir):
        meta = yaml.safe_load(p.read_text(encoding="utf-8"))["meta"]
        if meta["id"] == module_id:
            return p
    raise KeyError(f"module not found: {module_id}")
```
（`load_module` 的 import 供调用方 `load_module(find_module_path(...))` 使用；若 lint 报未用，保留 import 并在 routes 中以 `registry.find_module_path` + `load_module` 组合使用。）

`repo.py` 追加（events 区块之后）：
```python
    # ---------- players ----------

    def add_player(self, campaign_id: str, display_name: str) -> Player:
        import secrets
        player = Player(id=uuid.uuid4().hex[:12], campaign_id=campaign_id,
                        display_name=display_name, join_token=secrets.token_urlsafe(8))
        with Session(self.engine) as s:
            s.add(player)
            s.commit()
            s.refresh(player)
        return player

    def list_players(self, campaign_id: str) -> list[Player]:
        with Session(self.engine) as s:
            return list(s.exec(select(Player).where(Player.campaign_id == campaign_id)).all())

    def get_player(self, player_id: str) -> Player | None:
        with Session(self.engine) as s:
            return s.get(Player, player_id)

    def get_player_by_token(self, join_token: str) -> Player | None:
        with Session(self.engine) as s:
            return s.exec(select(Player).where(Player.join_token == join_token)).first()

    def latest_snapshot(self, campaign_id: str, branch_id: str) -> StateSnapshotRow | None:
        q = (select(StateSnapshotRow).where(StateSnapshotRow.branch_id == branch_id)
             .order_by(StateSnapshotRow.turn_id.desc(), StateSnapshotRow.id.desc()))
        with Session(self.engine) as s:
            return s.exec(q).first()
```
import 行同步加入 `Player`（`from app.storage.models import ... Player ...`）。

`backend/app/api/__init__.py`：留空。

`backend/app/api/app.py`：
```python
"""FastAPI 装配：REST + /healthz（WS/SessionManager 在 Task M3-11 挂载）。"""
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.storage.repo import SqliteRepository


@dataclass
class AppDeps:
    settings: Settings
    repo: SqliteRepository
    model_factory: object | None = None   # ModelFactory；测试注入 FakeLLM 工厂
    manager: object | None = None         # SessionManager；M3-10 后由 create_app 装配


def create_app(deps: AppDeps) -> FastAPI:
    from app.api import routes

    app = FastAPI(title="Ensemble")
    app.state.deps = deps
    app.add_middleware(CORSMiddleware, allow_origins=deps.settings.cors_origin_list,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(routes.router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
```

`backend/app/api/routes.py`：
```python
"""REST：模组、战役（M3-5）；时间线（M3-6）；分叉恢复（M3-7）。"""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


def _deps(request: Request):
    return request.app.state.deps


class CreateCampaignRequest(BaseModel):
    module_id: str
    title: str
    player_name: str = "调查员"


@router.get("/modules")
def list_modules_endpoint(request: Request):
    from app.content.registry import list_modules
    return list_modules(_deps(request).settings.modules_dir)


@router.post("/campaigns")
def create_campaign(req: CreateCampaignRequest, request: Request):
    from app.content.loader import load_module
    from app.content.registry import find_module_path
    from app.rules.character import make_default_character

    deps = _deps(request)
    try:
        module = load_module(find_module_path(deps.settings.modules_dir, req.module_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    campaign = deps.repo.create_campaign(module.meta.id, req.title)
    player = deps.repo.add_player(campaign.id, req.player_name)
    char = make_default_character(player.id, req.player_name)
    deps.repo.append_character(campaign.id, campaign.active_branch_id, 0,
                               char.id, asdict(char))
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "player_id": player.id, "character_id": char.id}


@router.get("/campaigns")
def list_campaigns(request: Request):
    repo = _deps(request).repo
    from app.storage.models import Campaign
    from sqlmodel import Session, select
    with Session(repo.engine) as s:
        rows = s.exec(select(Campaign).order_by(Campaign.created_at.desc())).all()
    for c in rows:
        out.append({"id": c.id, "title": c.title, "module_id": c.module_id,
                    "active_branch_id": c.active_branch_id,
                    "created_at": c.created_at.isoformat()})
    return out


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, request: Request):
    import json
    deps = _deps(request)
    repo = deps.repo
    try:
        campaign = repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    from app.content.loader import load_module
    from app.content.registry import find_module_path
    module = load_module(find_module_path(deps.settings.modules_dir, campaign.module_id))
    branch_id = campaign.active_branch_id
    snap = repo.latest_snapshot(campaign_id, branch_id)
    scene_id = (json.loads(snap.data_json).get("scene_id") if snap else None) \
        or module.opening.scene_id
    turn_id = (snap.turn_id + 1) if snap else 0
    players = [{"id": p.id, "display_name": p.display_name}
               for p in repo.list_players(campaign_id)]
    characters = repo.list_characters_at(campaign_id, branch_id, 10**9)
    seen, clues = set(), []
    for e in repo.list_events(campaign_id, branch_id, types=["clue"]):
        payload = json.loads(e.payload_json)
        if payload.get("clue_id") not in seen:
            seen.add(payload.get("clue_id"))
            clues.append(payload)
    return {"id": campaign.id, "title": campaign.title, "module_id": campaign.module_id,
            "module_title": module.meta.title, "active_branch_id": branch_id,
            "scene_id": scene_id, "turn_id": turn_id,
            "cost_usd": repo.campaign_cost_total(campaign_id),
            "players": players, "characters": characters, "clues_revealed": clues}
```

- [ ] **Step 5: 验证通过**

Run: `cd backend; uv run pytest tests/content tests/storage tests/api -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/app/content/registry.py backend/app/storage/repo.py backend/app/api backend/tests/content/test_registry.py backend/tests/storage/test_players.py backend/tests/api
git commit -m "feat(api): module registry, player repository, campaign REST endpoints"
```

---

### Task M3-6: 时间线 API（timeline / switch）

**Files:**
- Modify: `backend/app/storage/repo.py`（`branch_turn_count`）
- Modify: `backend/app/api/routes.py`（两个端点）
- Test: `backend/tests/api/test_timeline_api.py`

**Interfaces:**
- Consumes: `Branch` 模型（M2 Task 7）、`state` 快照（M2 Task 8）
- Produces：
  - `repo.branch_turn_count(branch_id) -> int`（= 最新 state 快照 `turn_id + 1`；无快照为 0，与 `GET /campaigns/{id}` 的 `turn_id` 口径一致）
  - `GET /api/campaigns/{id}/timeline` → `{active_branch_id, branches: [{id, name, parent_branch_id, fork_turn_id, completed_turns, created_at}]}`
  - `POST /api/campaigns/{id}/switch {branch_id}` → `{active_branch_id}`；分支不属于该战役 → 400；切换成功后若 `deps.manager` 存在则调用 `await manager.on_branch_switch(campaign_id)`（T10 实现）

- [ ] **Step 1: 写失败测试**

`backend/tests/api/test_timeline_api.py`：
```python
def _mk(client, repo, title="时间线"):
    cid = client.post("/api/campaigns", json={"module_id": "misty_hollow",
                                              "title": title}).json()["campaign_id"]
    return cid

def test_timeline_lists_branches_with_counts(client):
    c, repo = client
    cid = _mk(c, repo)
    cemp = repo.get_campaign(cid)
    for t in range(3):
        repo.append_state(cid, cemp.active_branch_id, t, {"scene_id": "square",
                                                          "npc_attitudes": {}})
    data = c.get(f"/api/campaigns/{cid}/timeline").json()
    assert data["active_branch_id"] == cemp.active_branch_id
    assert data["branches"][0]["completed_turns"] == 3

def test_switch_branch(client):
    c, repo = client
    cid = _mk(c, repo)
    camp = repo.get_campaign(cid)
    b2 = repo.create_branch(cid, "alt", fork_turn_id=0, parent_branch_id=camp.active_branch_id)
    r = c.post(f"/api/campaigns/{cid}/switch", json={"branch_id": b2.id})
    assert r.json()["active_branch_id"] == b2.id
    assert repo.get_campaign(cid).active_branch_id == b2.id

def test_switch_rejects_foreign_branch(client):
    c, repo = client
    cid1, cid2 = _mk(c, repo, "甲"), _mk(c, repo, "乙")
    b_foreign = repo.get_campaign(cid2).active_branch_id
    r = c.post(f"/api/campaigns/{cid1}/switch", json={"branch_id": b_foreign})
    assert r.status_code == 400
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_timeline_api.py -q`
Expected: FAIL —— 404（路由未定义）

- [ ] **Step 3: 实现**

`repo.py` 追加：
```python
    def branch_turn_count(self, branch_id: str) -> int:
        q = (select(StateSnapshotRow).where(StateSnapshotRow.branch_id == branch_id)
             .order_by(StateSnapshotRow.turn_id.desc()))
        with Session(self.engine) as s:
            row = s.exec(q).first()
        return (row.turn_id + 1) if row else 0
```

`routes.py` 追加：
```python
class SwitchBranchRequest(BaseModel):
    branch_id: str


@router.get("/campaigns/{campaign_id}/timeline")
def timeline(campaign_id: str, request: Request):
    repo = _deps(request).repo
    try:
        campaign = repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    branches = [{"id": b.id, "name": b.name, "parent_branch_id": b.parent_branch_id,
                 "fork_turn_id": b.fork_turn_id,
                 "completed_turns": repo.branch_turn_count(b.id),
                 "created_at": b.created_at.isoformat()}
                for b in repo.list_branches(campaign_id)]
    return {"active_branch_id": campaign.active_branch_id, "branches": branches}


@router.post("/campaigns/{campaign_id}/switch")
async def switch_branch(campaign_id: str, req: SwitchBranchRequest, request: Request):
    deps = _deps(request)
    try:
        campaign = deps.repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    branch = deps.repo.get_branch(req.branch_id)
    if branch is None or branch.campaign_id != campaign_id:
        raise HTTPException(status_code=400, detail="branch not in campaign")
    deps.repo.switch_branch(campaign_id, req.branch_id)
    if deps.manager is not None:
        await deps.manager.on_branch_switch(campaign_id)
    return {"active_branch_id": req.branch_id}
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/api -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/repo.py backend/app/api/routes.py backend/tests/api/test_timeline_api.py
git commit -m "feat(api): branch timeline and switch endpoints"
```

---

### Task M3-7: 分叉恢复（restore：L2 复制 + checkpoint 链复制）

**Files:**
- Modify: `backend/app/storage/repo.py`（`copy_branch_state`）
- Create: `backend/app/graph/fork.py`
- Modify: `backend/app/api/routes.py`（`POST /campaigns/{id}/restore`）
- Test: `backend/tests/api/test_restore_api.py`、`backend/tests/graph/test_fork.py`

**Interfaces:**
- Consumes: `StateSnapshotRow`/`GameEventRow` 等模型、SqliteSaver 表结构（`checkpoints` / `writes`，M2 Task 21 `build_checkpointer` 建表）
- Produces：
  - `repo.copy_branch_state(campaign_id, src_branch_id, dst_branch_id, upto_turn) -> None`：复制 events / state 快照 / characters / summaries / dice（`turn_id <= upto_turn`，`upto_turn` 含）；**不复制 usage**（用量是 campaign 级，避免成本重复累计）
  - `fork_thread(db_path, src_thread, dst_thread, upto_turn) -> None`：把源 thread 上"第 `upto_turn+1` 个挂起点"（即 turn `upto_turn` 结束后的 `wait_input` 挂起 checkpoint）及其祖先链复制到目标 thread；找不到该边界 → `ValueError`
  - `POST /api/campaigns/{id}/restore {turn_id}` → 新建分支（名称 `rollback-{turn_id}-{随机 4 位}`）→ 复制 checkpoint 链 → 复制 L2 → 切换 active；返回 `{branch_id, name}`
  - 恢复后新 thread 的图状态中 `branch_id` 仍是旧分支 ID —— **由 SessionManager 恢复执行时经 `Command(resume=..., update={"branch_id": ...})` 修正**（T10 落实；本任务测试直接验证 `get_state` 的挂起与 `turn_id`）

- [ ] **Step 1: 写失败测试**

`backend/tests/graph/test_fork.py`：
```python
from dataclasses import asdict
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.graph.fork import fork_thread
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

OPENING = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
           ' "scene_transition": null, "memory_queries": []}')
PLAIN = ('{"intent_summary": "继续", "checks": [], "proactive_npc_triggers": [],'
         ' "scene_transition": null, "memory_queries": []}')

def _env(tmp_path, script):
    db = str(tmp_path / "fork.db")
    engine = make_engine(db)
    init_db(engine)
    repo = SqliteRepository(engine)
    campaign = repo.create_campaign("mini", "分叉测试")
    char = make_default_character("p1", "调查员")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    queues = {m: list(v) for m, v in script.items()}
    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    settings = Settings(sqlite_path=db)
    client = LLMClient(settings, pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, _mini(), JournalMemory(repo), client,
                             BudgetGuard(settings), build_checkpointer(db))
    return db, repo, campaign, graph, settings

def _mini():
    from app.content.schema import Module
    return Module.model_validate({
        "meta": {"id": "mini", "title": "迷你"},
        "opening": {"narration": "开场叙述", "scene_id": "gate"},
        "scenes": [{"id": "gate", "name": "村口", "npcs": [], "exits": []}],
        "npcs": [], "clues": [],
        "endings": [{"id": "e1", "scene": "gate", "condition": "真相大白"}]})

def test_fork_copies_chain_and_strands_at_boundary(tmp_path):
    db, repo, campaign, graph, settings = _env(tmp_path, {"qwen3.8-flash": [
        OPENING, "开场叙事。", PLAIN, "第二回合叙事。"]})
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1,
                                 "inputs": [{"player_id": "p1", "character_id": "pc_p1",
                                             "text": "继续"}], "skipped": []}), cfg)
    assert graph.get_state(cfg).values["turn_id"] == 2   # 已完成 turn 0 与 turn 1

    dst = f"{campaign.id}@rollback"
    fork_thread(db, campaign.active_branch_id, dst, upto_turn=1)

    snap = graph.get_state({"configurable": {"thread_id": dst}})
    assert snap.next == ("wait_input",)                  # 复制的挂起点生效
    assert snap.values["turn_id"] == 2                   # = upto_turn + 1
    # 目标 thread 可继续推进
    result = graph.invoke(Command(resume={"turn_id": 2,
                                          "inputs": [{"player_id": "p1",
                                                      "character_id": "pc_p1",
                                                      "text": "新分支行动"}],
                                          "skipped": []},
                                  update={"branch_id": dst}),
                          {"configurable": {"thread_id": dst}})
    assert result.get("__interrupt__"), "fork 后可继续回合"

def test_fork_missing_boundary_raises(tmp_path):
    import pytest
    db, repo, campaign, graph, settings = _env(tmp_path, {"qwen3.8-flash": [OPENING, "开场。" ]})
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    with pytest.raises(ValueError):
        fork_thread(db, campaign.active_branch_id, f"{campaign.id}@x", upto_turn=5)
```

`backend/tests/api/test_restore_api.py`：
```python
def test_restore_creates_branch_and_switches(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "恢复"}).json()["campaign_id"]
    # 无 checkpoint（本测试环境未跑图）→ restore 应报 400 且不切分支
    r = c.post(f"/api/campaigns/{cid}/restore", json={"turn_id": 0})
    assert r.status_code == 400
    assert repo.get_campaign(cid).active_branch_id.endswith("@main")
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/graph/test_fork.py tests/api/test_restore_api.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.graph.fork'`

- [ ] **Step 3: 实现 fork.py**

`backend/app/graph/fork.py`：
```python
"""checkpoint 分叉：把源 thread 的历史挂起点链复制到新 thread（规格 §7 读档回滚）。

实现要点：不做反序列化、原样复制 rows。挂起点判定 = 该 checkpoint 存在
`__interrupt__` 写（langgraph 把 interrupt 存为 reserved 通道的 write）。
第 k 个挂起点（从最旧数起，1-based）= 第 k-1 个回合结束后的 wait_input 挂起。
"""
import sqlite3


def _chain(db_path: str, thread_id: str) -> list[str]:
    """按从旧到新返回该 thread 的 checkpoint 链（沿 parent_checkpoint_id 上溯）。"""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT checkpoint_id, parent_checkpoint_id FROM checkpoints "
            "WHERE thread_id = ?", (thread_id,)).fetchall()
    parents = {cid: pid for cid, pid in rows}
    children = {pid: cid for cid, pid in rows if pid}
    roots = [cid for cid, pid in rows if not pid or pid not in parents]
    if not roots:
        return []
    chain, cur = [], roots[0]
    while cur:
        chain.append(cur)
        cur = children.get(cur)
    return chain


def fork_thread(db_path: str, src_thread: str, dst_thread: str, upto_turn: int) -> None:
    chain = _chain(db_path, src_thread)
    if not chain:
        raise ValueError(f"no checkpoints on thread {src_thread}")
    with sqlite3.connect(db_path) as conn:
        parked = {cid for (cid,) in conn.execute(
            "SELECT DISTINCT checkpoint_id FROM writes "
            "WHERE thread_id = ? AND channel = '__interrupt__'", (src_thread,)).fetchall()}
        ordered_parked = [cid for cid in chain if cid in parked]
        if len(ordered_parked) <= upto_turn:
            raise ValueError(
                f"turn boundary not found: turn {upto_turn} "
                f"(仅 {len(ordered_parked)} 个已完成回合挂起点)")
        boundary = ordered_parked[upto_turn]          # 第 upto_turn+1 个挂起点
        copy_ids = chain[: chain.index(boundary) + 1]  # 含边界在内的全部祖先

        for table in ("checkpoints", "writes"):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            marks = ",".join("?" for _ in cols)
            sel = (f"SELECT {','.join(cols)} FROM {table} "
                   f"WHERE thread_id = ? AND checkpoint_id IN ({','.join('?' for _ in copy_ids)})")
            rows = conn.execute(sel, [src_thread, *copy_ids]).fetchall()
            ins = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({marks})"
            for row in rows:
                values = dict(zip(cols, row))
                values["thread_id"] = dst_thread
                conn.execute(ins, [values[c] for c in cols])
        conn.commit()
```

- [ ] **Step 4: repo.copy_branch_state + restore 路由**

`repo.py` 追加：
```python
    def copy_branch_state(self, campaign_id: str, src_branch_id: str,
                          dst_branch_id: str, upto_turn: int) -> None:
        """分叉：把源分支 ≤ upto_turn 的 L2 行原样复制到目标分支（usage 不复制）。"""
        with Session(self.engine) as s:
            for model, turn_attr in ((GameEventRow, "turn_id"), (StateSnapshotRow, "turn_id"),
                                     (CharacterStateRow, "turn_id"), (DiceRecordRow, "turn_id")):
                q = select(model).where(model.branch_id == src_branch_id,
                                        getattr(model, turn_attr) <= upto_turn)
                for row in s.exec(q).all():
                    data = row.model_dump()
                    data.pop("id", None)
                    data["branch_id"] = dst_branch_id
                    s.add(model(**data))
            q = (select(SummaryRow).where(SummaryRow.branch_id == src_branch_id,
                                          SummaryRow.upto_turn <= upto_turn))
            for row in s.exec(q).all():
                s.add(SummaryRow(campaign_id=campaign_id, branch_id=dst_branch_id,
                                 upto_turn=row.upto_turn, content=row.content))
            s.commit()
```
import 行同步加入 `DiceRecordRow, SummaryRow`。

`routes.py` 追加：
```python
class RestoreRequest(BaseModel):
    turn_id: int


@router.post("/campaigns/{campaign_id}/restore")
async def restore_campaign(campaign_id: str, req: RestoreRequest, request: Request):
    import uuid as _uuid
    from app.graph.fork import fork_thread
    deps = _deps(request)
    try:
        campaign = deps.repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    src = campaign.active_branch_id
    name = f"rollback-{req.turn_id}-{_uuid.uuid4().hex[:4]}"
    dst = f"{campaign_id}@{name}"
    try:
        fork_thread(deps.settings.sqlite_path, src, dst, upto_turn=req.turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    deps.repo.copy_branch_state(campaign_id, src, dst, req.turn_id)
    deps.repo.create_branch(campaign_id, name, fork_turn_id=req.turn_id,
                            parent_branch_id=src)
    deps.repo.switch_branch(campaign_id, dst)
    if deps.manager is not None:
        await deps.manager.on_branch_switch(campaign_id)
    return {"branch_id": dst, "name": name}
```
（`create_branch` 的 id 规则 `f"{campaign_id}@{name}"` 与 `dst` 一致——如 M2 实现不同则以 repo 实际规则调整 dst 计算，保持"先算 dst → fork → create_branch → switch"顺序。）

- [ ] **Step 5: 验证通过（含 M2 回归）**

Run: `cd backend; uv run pytest tests/graph tests/api tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/fork.py backend/app/storage/repo.py backend/app/api/routes.py backend/tests/graph/test_fork.py backend/tests/api/test_restore_api.py
git commit -m "feat(api): branch restore with L2 copy and checkpoint chain fork"
```

---

### Task M3-8: WS 事件总线（EventBus：seq / 可见性过滤 / 断线重放）

**Files:**
- Create: `backend/app/api/events.py`
- Test: `backend/tests/api/test_event_bus.py`

**Interfaces:**
- Consumes: 无（纯内存组件，不依赖存储与图）
- Produces：
  - `WsEvent`（frozen dataclass）：`seq: int, type: str, visibility: str, payload: dict`
    - `to_json() -> str`（`{"seq","type","visibility","payload"}`，`ensure_ascii=False`）
    - `visible_to(player_id) -> bool`：`all` → 所有人；`player:<id>` → 仅该玩家
  - `Subscriber(player_id, queue: asyncio.Queue)`
  - `EventBus(replay_size=500)`：
    - `push(event_type, payload, visibility="all") -> WsEvent`：seq 从 1 自增；写入环形缓冲；分发给可见订阅者
    - `subscribe(player_id) -> Subscriber` / `unsubscribe(sub)`
    - `replay(since_seq, player_id) -> tuple[list[WsEvent], bool]`：该玩家可见的增量 + `gap`；`gap=True` 表示 `since_seq+1` 早于缓冲最旧 seq（缓冲已截断），调用方应改为全量 resync
    - `current_seq` property（resync 游标对齐用）
  - **M3 事件类型枚举（定稿，前端 reducer 按此实现）**：
    - `token`：`{speaker, text}` 叙事增量；`{reset: true}` 表示本回合重新生成（清空后接收新 token）
    - `dice`：`{actor, skill, skill_value, difficulty, roll, level, seed, success}`
    - `actor`：`{player_id, text}`（某玩家已提交行动）
    - `scene`：`{scene_id, name, description, npcs, reason?}`（`reason` 由 `scene_changed` 事件驱动时携带）
    - `turn`：`{phase, turn_id, ending_reached?}`（`phase ∈ resolving|collecting|ended|paused`）
    - `state`：全量状态快照（结构见 T10 `_state_payload`；重连 resync 时含 `segments/dice/phase`）
    - `clue`：`{clue_id, text}`（新线索揭示）
    - `notice`：`{message}` 或 `{kind:"submit", status:"accepted"|"deferred"}`（仅当事人的提示）
    - `error`：`{message}`（可见性默认 `all`）

- [ ] **Step 1: 写失败测试**

`backend/tests/api/test_event_bus.py`：
```python
import json

from app.api.events import EventBus


def drain(sub):
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


def test_push_assigns_increasing_seq_and_json_roundtrip():
    bus = EventBus()
    e1 = bus.push("token", {"speaker": "gm", "text": "雾气"})
    e2 = bus.push("turn", {"phase": "collecting", "turn_id": 1})
    assert (e1.seq, e2.seq, bus.current_seq) == (1, 2, 2)
    data = json.loads(e2.to_json())
    assert data == {"seq": 2, "type": "turn", "visibility": "all",
                    "payload": {"phase": "collecting", "turn_id": 1}}


def test_private_event_only_reaches_target_player():
    bus = EventBus()
    s1 = bus.subscribe("p1")
    s2 = bus.subscribe("p2")
    bus.push("token", {"text": "公开"})
    bus.push("notice", {"message": "秘密"}, visibility="player:p1")
    assert [e.type for e in drain(s1)] == ["token", "notice"]
    assert [e.type for e in drain(s2)] == ["token"]


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    s1 = bus.subscribe("p1")
    bus.unsubscribe(s1)
    bus.push("token", {"text": "x"})
    assert drain(s1) == []


def test_replay_filters_by_player_and_since_seq():
    bus = EventBus()
    bus.push("token", {"text": "1"})
    bus.push("state", {"x": 1}, visibility="player:p2")
    bus.push("token", {"text": "2"})
    events, gap = bus.replay(0, "p1")
    assert [e.seq for e in events] == [1, 3] and gap is False


def test_replay_reports_gap_when_buffer_trimmed():
    bus = EventBus(replay_size=2)
    for i in range(3):
        bus.push("token", {"text": str(i)})
    events, gap = bus.replay(0, "p1")
    assert gap is True
    events2, gap2 = bus.replay(1, "p1")
    assert gap2 is False and [e.seq for e in events2] == [2, 3]
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_event_bus.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.api.events'`

- [ ] **Step 3: 实现 events.py**

`backend/app/api/events.py`：
```python
"""WS 事件总线：seq 分配、可见性过滤、断线重放环形缓冲（纯内存，无 IO）。"""
import asyncio
import json
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WsEvent:
    seq: int
    type: str
    visibility: str
    payload: dict

    def to_json(self) -> str:
        return json.dumps({"seq": self.seq, "type": self.type,
                           "visibility": self.visibility, "payload": self.payload},
                          ensure_ascii=False)

    def visible_to(self, player_id: str) -> bool:
        return self.visibility == "all" or self.visibility == f"player:{player_id}"


@dataclass
class Subscriber:
    player_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class EventBus:
    def __init__(self, replay_size: int = 500):
        self._seq = 0
        self._buffer: deque[WsEvent] = deque(maxlen=replay_size)
        self._subscribers: list[Subscriber] = []

    @property
    def current_seq(self) -> int:
        return self._seq

    def push(self, event_type: str, payload: dict, visibility: str = "all") -> WsEvent:
        self._seq += 1
        evt = WsEvent(seq=self._seq, type=event_type, visibility=visibility,
                      payload=payload)
        self._buffer.append(evt)
        for sub in list(self._subscribers):
            if evt.visible_to(sub.player_id):
                sub.queue.put_nowait(evt)
        return evt

    def subscribe(self, player_id: str) -> Subscriber:
        sub = Subscriber(player_id=player_id)
        self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        if sub in self._subscribers:
            self._subscribers.remove(sub)

    def replay(self, since_seq: int, player_id: str) -> tuple[list[WsEvent], bool]:
        """该玩家可见的增量事件 + gap 标志（缓冲被截断时调用方应全量 resync）。"""
        events = [e for e in self._buffer if e.seq > since_seq and e.visible_to(player_id)]
        gap = bool(self._buffer) and self._buffer[0].seq > since_seq + 1
        return events, gap
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/api/test_event_bus.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/events.py backend/tests/api/test_event_bus.py
git commit -m "feat(api): in-memory ws event bus with visibility filter and replay buffer"
```

---

### Task M3-9: TurnBuffer（回合输入收集状态机）

**Files:**
- Create: `backend/app/api/turn_buffer.py`
- Test: `backend/tests/api/test_turn_buffer.py`

**Interfaces:**
- Consumes: 无（纯内存状态机，时间由调用方以 `now: float` 注入，便于测试）
- Produces：
  - `TurnBuffer(window_seconds=60.0, single_player_debounce_seconds=2.0)`：
    - `open(turn_id, active_players, now) -> int`：进入 `collecting`；把上一窗口间隙提交的 `pending_next` 顺延为初始提交；返回新 `epoch`（定时器凭 epoch 判断自己是否过期）
    - `submit(player_id, entry, now) -> str`：`"accepted"`（本轮生效，后发覆盖前发）/ `"deferred"`（本轮已收口，顺延下一轮）/ `"ignored"`（非本局玩家）
    - `all_submitted() -> bool`
    - `should_close(now, window_started) -> bool`：单人提交后需过防抖（等补充输入）；多人齐全立即收口；否则窗口超时（规格 §4.2）
    - `close() -> dict`：产出 interrupt resume payload（结构 = `TurnInputs.model_dump()`：`{turn_id, inputs, skipped}`）；置回 `idle`
  - `entry` 结构（由调用方构造）：`{player_id, character_id, text, submitted_at}`

- [ ] **Step 1: 写失败测试**

`backend/tests/api/test_turn_buffer.py`：
```python
from app.api.turn_buffer import TurnBuffer


def entry(p, text):
    return {"player_id": p, "character_id": f"pc_{p}", "text": text,
            "submitted_at": ""}


def test_single_player_debounce_then_close():
    buf = TurnBuffer(single_player_debounce_seconds=2.0)
    epoch = buf.open(1, ["p1"], now=100.0)
    assert epoch == 1 and buf.phase == "collecting"
    assert buf.submit("p1", entry("p1", "进门"), now=101.0) == "accepted"
    assert not buf.should_close(now=102.5, window_started=100.0)   # 防抖未满 2 秒
    assert buf.should_close(now=103.0, window_started=100.0)
    payload = buf.close()
    assert payload["turn_id"] == 1 and payload["skipped"] == []
    assert payload["inputs"][0]["text"] == "进门"
    assert buf.phase == "idle"


def test_resubmit_overwrites_before_close():
    buf = TurnBuffer(single_player_debounce_seconds=0.0)
    buf.open(1, ["p1"], now=0.0)
    buf.submit("p1", entry("p1", "第一次"), now=1.0)
    buf.submit("p1", entry("p1", "改主意了"), now=2.0)
    payload = buf.close()
    assert [i["text"] for i in payload["inputs"]] == ["改主意了"]


def test_timeout_records_skipped():
    buf = TurnBuffer(window_seconds=60.0)
    buf.open(3, ["p1", "p2"], now=100.0)
    buf.submit("p1", entry("p1", "我上"), now=101.0)
    assert not buf.should_close(now=150.0, window_started=100.0)
    assert buf.should_close(now=160.0, window_started=100.0)
    assert buf.close()["skipped"] == ["p2"]


def test_multi_player_all_submitted_closes_immediately():
    buf = TurnBuffer(window_seconds=60.0)
    buf.open(1, ["p1", "p2"], now=0.0)
    buf.submit("p1", entry("p1", "a"), now=1.0)
    assert not buf.should_close(now=1.0, window_started=0.0)
    buf.submit("p2", entry("p2", "b"), now=2.0)
    assert buf.should_close(now=2.0, window_started=0.0)   # 多人：齐全即收，无防抖


def test_submit_between_windows_deferred_to_next():
    buf = TurnBuffer()
    buf.open(1, ["p1"], now=0.0)
    buf.submit("p1", entry("p1", "第一回合"), now=1.0)
    buf.close()
    assert buf.submit("p1", entry("p1", "抢在下一轮前"), now=5.0) == "deferred"
    buf.open(2, ["p1"], now=6.0)
    payload = buf.close()
    assert payload["turn_id"] == 2
    assert [i["text"] for i in payload["inputs"]] == ["抢在下一轮前"]


def test_unknown_player_ignored():
    buf = TurnBuffer()
    buf.open(1, ["p1"], now=0.0)
    assert buf.submit("ghost", entry("ghost", "x"), now=1.0) == "ignored"
    assert buf.close()["skipped"] == ["p1"]


def test_epoch_bumps_on_open_and_close():
    buf = TurnBuffer()
    e1 = buf.open(1, ["p1"], now=0.0)
    buf.close()
    e2 = buf.open(2, ["p1"], now=10.0)
    assert e2 == e1 + 2      # close 与 open 各 +1，旧定时器据此退出
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_turn_buffer.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.api.turn_buffer'`

- [ ] **Step 3: 实现 turn_buffer.py**

`backend/app/api/turn_buffer.py`：
```python
"""回合输入收集状态机：单人防抖、多人齐全即收、超时跳过、后发覆盖、间隙顺延。

时间一律由调用方传入（now / window_started），便于测试注入与定时器复用。
"""
from dataclasses import dataclass, field


@dataclass
class TurnBuffer:
    window_seconds: float = 60.0
    single_player_debounce_seconds: float = 2.0
    phase: str = "idle"                        # idle | collecting
    turn_id: int | None = None
    epoch: int = 0                             # open/close 均自增；旧定时器凭它退出
    active_players: list[str] = field(default_factory=list)
    submissions: dict[str, dict] = field(default_factory=dict)
    pending_next: dict[str, dict] = field(default_factory=dict)
    last_submit_ts: float | None = None

    def open(self, turn_id: int, active_players: list[str], now: float) -> int:
        self.phase = "collecting"
        self.turn_id = turn_id
        self.active_players = list(active_players)
        self.submissions = dict(self.pending_next)   # 窗口间隙的提交顺延入本轮
        self.pending_next = {}
        self.last_submit_ts = now if self.submissions else None
        self.epoch += 1
        return self.epoch

    def submit(self, player_id: str, entry: dict, now: float) -> str:
        if player_id not in self.active_players:
            return "ignored"
        if self.phase == "collecting":
            self.submissions[player_id] = entry     # 后发覆盖前发
            self.last_submit_ts = now
            return "accepted"
        self.pending_next[player_id] = entry
        return "deferred"

    def all_submitted(self) -> bool:
        return bool(self.active_players) and all(p in self.submissions
                                                 for p in self.active_players)

    def should_close(self, now: float, window_started: float) -> bool:
        if self.phase != "collecting":
            return False
        if self.all_submitted():
            if len(self.active_players) == 1 and self.last_submit_ts is not None:
                return (now - self.last_submit_ts) >= self.single_player_debounce_seconds
            return True
        return (now - window_started) >= self.window_seconds

    def close(self) -> dict:
        """收口并产出 interrupt resume payload（TurnInputs.model_dump() 结构）。"""
        inputs = [self.submissions[p] for p in self.active_players
                  if p in self.submissions]
        skipped = [p for p in self.active_players if p not in self.submissions]
        payload = {"turn_id": self.turn_id, "inputs": inputs, "skipped": skipped}
        self.phase = "idle"
        self.turn_id = None
        self.submissions = {}
        self.last_submit_ts = None
        self.epoch += 1
        return payload
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/api/test_turn_buffer.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/turn_buffer.py backend/tests/api/test_turn_buffer.py
git commit -m "feat(api): turn buffer state machine with single-player debounce and window carry-over"
```

---

### Task M3-10: RoomSession 与 SessionManager（会话驱动核心）

**Files:**
- Modify: `backend/app/storage/db.py`（SQLite WAL + busy_timeout：多连接并发安全）
- Modify: `backend/app/graph/main.py`（`build_checkpointer` 加 busy_timeout）
- Modify: `backend/pyproject.toml`（`asyncio_mode = "auto"`）
- Create: `backend/app/api/session.py`
- Test: `backend/tests/api/test_session.py`

**Interfaces:**
- Consumes: `build_game_graph`/`build_checkpointer`（M2）、`EventBus`（M3-8）、`TurnBuffer`（M3-9）、`AppDeps`（M3-5）、`load_pricing`/`JournalMemory`/`BudgetGuard`（M2）
- Produces：
  - `RoomSession`（dataclass）：`campaign_id, repo, settings, module, graph, bus, buffer, branch_id, started, driving, ended, prev_scene, last_clue_id, last_scene_id, window_task, window_started`；`config` property = `{"configurable": {"thread_id": branch_id}}`
  - `SessionManager(deps)`（`deps` 鸭子类型：`.settings/.repo/.model_factory`）：
    - `get(campaign_id) -> RoomSession`（不存在 `KeyError`）
    - `ensure_started(campaign_id) -> RoomSession`：幂等；首访组装会话并驱动开场（或挂起续玩开窗），并发连接不重复驱动
    - `on_branch_switch(campaign_id)`：丢弃旧会话状态、复用同一 `EventBus`（已连接 WS 不断）、按新 active 分支重新组装并启动
    - `handle_submit(campaign_id, player_id, text) -> str`（`accepted|deferred|ignored`；accepted 广播 `actor`，deferred 回本人 `notice`）
    - `resync_payload(session) -> dict`：重连 gap 的全量对齐（`_state_payload`（含全量权威 `segments`）+ `dice` + `phase`）
    - `close()`：取消残留窗口定时器（应用 shutdown 用）
  - 驱动语义（**图的唯一驱动者**）：
    - `_drive(session, inp)`：`async for chunk in graph.astream(inp, config, stream_mode="custom")` → 逐条 `bus.push("token", chunk)`；异常不致命（push `error`）
    - resume 一律 `Command(resume=payload, update={"branch_id": session.branch_id})`——修正 M3-7 fork 恢复后 checkpoint 内的旧 branch_id
    - 收口 `_push_snapshot`：从 L2 读权威结果推 `dice`（按刚结束回合）、新 `clue`、`scene_changed` 事件 → `scene`（含 `reason`；无事件时仅“会话首推”兜底）、`state` 快照；然后按挂起状态推 `turn`：`collecting`（开窗）/ `paused`（预算熔断或中间态，仅熔断锁输入）/ `ended`（结局）
    - 窗口定时器：0.05s 轮询 `should_close`，凭 `buffer.epoch` 判断过期退出
  - 细节约定：
    - `budget_paused`：push `error` + `turn(paused)`，**不开窗口**（前端锁输入）
    - 其他 `error`（fallback 场景）：push `error` + 正常开窗（玩家重新输入）
    - 骰子 `success = level ∈ {critical, extreme, hard, regular}`（与 M2 rules 口径一致）

- [ ] **Step 1: 并发安全前置修改（db.py / main.py / pyproject.toml）**

`backend/app/storage/db.py` 的 `make_engine` 替换为（WAL：读写并发不互斥；busy_timeout：写锁等待而非立即失败）：
```python
"""SQLite 引擎与建表（WAL + busy_timeout：多连接并发安全）。"""
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel


def make_engine(sqlite_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{sqlite_path}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
```

`backend/app/graph/main.py` 的 `build_checkpointer` 替换为（同库同文件，同样需要 busy_timeout）：
```python
def build_checkpointer(sqlite_path: str) -> SqliteSaver:
    """SqliteSaver：CLI 重启后仍可恢复挂起的回合（断点续玩）。"""
    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
```

`backend/pyproject.toml` 的 `[tool.pytest.ini_options]` 追加：
```toml
asyncio_mode = "auto"
```

- [ ] **Step 2: 写失败测试**

`backend/tests/api/test_session.py`：
```python
import asyncio
import time
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
TURN_DECIDE = ('{"intent_summary": "调查", "checks": [], "proactive_npc_triggers": [],'
               ' "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    """按模型名消耗脚本；每次 chat 新建 FakeLLM（与 LLMClient 的工厂调用方式一致）。"""
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


@pytest.fixture
def room(tmp_path):
    engine = make_engine(str(tmp_path / "api.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "api.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=3.0)
    campaign = repo.create_campaign("misty_hollow", "会话测试")
    player = repo.add_player(campaign.id, "张三")
    char = make_default_character(player.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    return repo, settings, campaign, player


async def collect_until(session, predicate, timeout=8.0):
    """订阅总线收集事件直到 predicate(events) 为真（测试辅助）。"""
    sub = session.bus.subscribe("__test__")
    try:
        events = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                evt = await asyncio.wait_for(
                    sub.queue.get(), timeout=max(deadline - time.time(), 0.01))
            except asyncio.TimeoutError:
                break
            events.append(evt)
            if predicate(events):
                return events
        raise AssertionError(f"condition not met; got {[e.type for e in events]}")
    finally:
        session.bus.unsubscribe(sub)


async def test_opening_then_round_trip(room):
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。",
                              TURN_DECIDE, "你蹲下查看井边。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    assert session.buffer.phase == "collecting"

    status = await manager.handle_submit(campaign.id, player.id, "我绕到喷泉后面")
    assert status == "accepted"

    events = await collect_until(session, lambda evts: any(
        e.type == "turn" and e.payload.get("phase") == "collecting"
        and e.payload.get("turn_id") == 2 for e in evts))
    assert any(e.type == "state" for e in events)
    assert any(e.type == "actor" for e in events)
    assert session.buffer.phase == "collecting"
    await manager.close()


async def test_ensure_started_is_idempotent(room):
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "开场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    seq = session.bus.current_seq
    again = await manager.ensure_started(campaign.id)
    assert again is session and again.bus.current_seq == seq   # 不重复驱动、不重复计费
    await manager.close()


async def test_branch_switch_reassembles_and_reopens(room):
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "开场。",
                              OPENING_DECIDE, "新分支开场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    old_bus = session.bus

    repo.create_branch(campaign.id, "alt", fork_turn_id=0,
                       parent_branch_id=campaign.active_branch_id)
    repo.switch_branch(campaign.id, f"{campaign.id}@alt")
    await manager.on_branch_switch(campaign.id)

    new = manager.get(campaign.id)
    assert new is not session and new.bus is old_bus
    assert new.branch_id == f"{campaign.id}@alt"
    assert new.buffer.phase == "collecting"      # 无 checkpoint 的分支自动全新开场
    await manager.close()
```

- [ ] **Step 3: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_session.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.api.session'`

- [ ] **Step 4: 实现 session.py**

`backend/app/api/session.py`：
```python
"""会话驱动：RoomSession（每战役一个）与 SessionManager（图的唯一驱动者）。

职责：把 LangGraph 的挂起/恢复（interrupt/resume）翻译成 WS 事件流；
窗口收集玩家输入（TurnBuffer）；从 L2 读权威结果（骰子/线索）推送。
"""
import asyncio
import json
import time
from dataclasses import dataclass, field

from langgraph.types import Command

from app.api.events import EventBus
from app.api.turn_buffer import TurnBuffer
from app.config import Settings, load_pricing
from app.content.loader import load_module
from app.content.registry import find_module_path
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.memory.scheduler import BackgroundSummaries
from app.memory.summarizer import LLMSummarizer
from app.storage.repo import SqliteRepository
from app.tasks import BackgroundQueue

_SUCCESS_LEVELS = ("critical", "extreme", "hard", "regular")
_TICK_SECONDS = 0.05


def _dice_payload(row) -> dict:
    return {"actor": row.actor, "skill": row.skill, "skill_value": row.skill_value,
            "difficulty": row.difficulty, "roll": row.roll, "level": row.level,
            "seed": row.seed, "success": row.level in _SUCCESS_LEVELS}


def _scene_payload(session, scene_id) -> dict | None:
    """场景展示数据；scene_id 不在模组中（越界/历史分支）→ None。"""
    try:
        scene = session.module.scene(scene_id)
    except KeyError:
        return None
    return {"scene_id": scene.id, "name": scene.name,
            "description": scene.description, "npcs": list(scene.npcs)}


@dataclass
class RoomSession:
    campaign_id: str
    repo: SqliteRepository
    settings: Settings
    module: object
    graph: object
    bus: EventBus
    buffer: TurnBuffer
    branch_id: str
    queue: BackgroundQueue
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started: bool = False
    driving: bool = False
    ended: bool = False
    prev_scene: str | None = None
    last_clue_id: int = 0
    last_scene_id: int = 0
    window_task: asyncio.Task | None = None
    window_started: float = 0.0

    @property
    def config(self) -> dict:
        return {"configurable": {"thread_id": self.branch_id}}


class SessionManager:
    def __init__(self, deps):
        self._deps = deps
        self._sessions: dict[str, RoomSession] = {}
        self._lock = asyncio.Lock()

    # ---------- 查询 ----------

    def get(self, campaign_id: str) -> RoomSession:
        session = self._sessions.get(campaign_id)
        if session is None:
            raise KeyError(campaign_id)
        return session

    # ---------- 生命周期 ----------

    def _assemble(self, campaign_id: str) -> RoomSession:
        deps = self._deps
        campaign = deps.repo.get_campaign(campaign_id)
        module = load_module(find_module_path(deps.settings.modules_dir,
                                              campaign.module_id))
        client = LLMClient(deps.settings, load_pricing(deps.settings.pricing_path),
                           usage_sink=deps.repo, model_factory=deps.model_factory)
        journal = JournalMemory(deps.repo, summarizer=LLMSummarizer(client))
        queue = BackgroundQueue(lambda key, payload: journal.update_summaries(*payload),
                                name="summary")
        queue.start()
        graph = build_game_graph(deps.repo, module, BackgroundSummaries(journal, queue),
                                 client, BudgetGuard(deps.settings),
                                 build_checkpointer(deps.settings.sqlite_path))
        session = RoomSession(
            campaign_id=campaign_id, repo=deps.repo, settings=deps.settings,
            module=module, graph=graph, queue=queue,
            bus=EventBus(replay_size=deps.settings.ws_replay_size),
            buffer=TurnBuffer(window_seconds=deps.settings.turn_window_seconds,
                              single_player_debounce_seconds=(
                                  deps.settings.single_player_debounce_seconds)),
            branch_id=campaign.active_branch_id)
        self._sessions[campaign_id] = session
        return session

    async def ensure_started(self, campaign_id: str) -> RoomSession:
        async with self._lock:
            session = self._sessions.get(campaign_id)
            if session is None:
                session = self._assemble(campaign_id)
            if session.started:
                return session
            session.started = True
        await self._start(session)
        return session

    async def _start(self, session: RoomSession) -> None:
        """按 checkpoint 挂起状态决定：续玩开窗 / 全新开场 / 中间态报错 / 已结束。"""
        snap = session.graph.get_state(session.config)
        if snap.next == ("wait_input",):
            self._open_window(session)
            return
        if snap.next:
            session.bus.push("error",
                             {"message": f"图处于中间状态 {snap.next}，暂无法续玩"})
            return
        if not snap.values:
            await self._drive(session, {"campaign_id": session.campaign_id,
                                        "branch_id": session.branch_id,
                                        "turn_id": 0, "player_inputs": []})
            return
        if (snap.values or {}).get("ending_reached"):
            session.ended = True
            session.bus.push("turn", {"phase": "ended",
                                      "ending_reached": snap.values["ending_reached"]})

    async def on_branch_switch(self, campaign_id: str) -> None:
        async with self._lock:
            old = self._sessions.pop(campaign_id, None)
            if old is not None:
                if old.window_task is not None and not old.window_task.done():
                    old.window_task.cancel()
                old.queue.stop()          # 旧分支摘要队列：跑完在队任务后退出
            session = self._assemble(campaign_id)
            if old is not None:
                session.bus = old.bus          # 已连接的 WS 订阅保持有效
                old.bus.push("notice", {"message": f"已切换到分支 {session.branch_id}"})
            session.started = True
        await self._start(session)

    async def handle_submit(self, campaign_id: str, player_id: str, text: str) -> str:
        session = self.get(campaign_id)
        player = session.repo.get_player(player_id)
        if player is None or player.campaign_id != campaign_id:
            raise KeyError(player_id)
        entry = {"player_id": player_id, "character_id": f"pc_{player_id}",
                 "text": text.strip(),
                 "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        status = session.buffer.submit(player_id, entry, now=time.time())
        if status == "accepted":
            session.bus.push("actor", {"player_id": player_id, "text": entry["text"]})
        elif status == "deferred":
            session.bus.push("notice",
                             {"kind": "submit", "status": "deferred",
                              "message": "本轮已开始结算，你的行动将在下一轮生效"},
                             visibility=f"player:{player_id}")
        return status

    async def close(self) -> None:
        for session in list(self._sessions.values()):
            if session.window_task is not None and not session.window_task.done():
                session.window_task.cancel()
            session.queue.flush(2.0)      # 退出前尽力收尾摘要（丢任务无害：watermark 自愈）
            session.queue.stop()
        self._sessions.clear()

    # ---------- 驱动 ----------

    async def _drive(self, session: RoomSession, inp) -> None:
        session.driving = True
        snap0 = session.graph.get_state(session.config)
        session.bus.push("turn", {"phase": "resolving",
                                  "turn_id": int((snap0.values or {}).get("turn_id", 0))})
        try:
            async for chunk in session.graph.astream(inp, session.config,
                                                     stream_mode="custom"):
                if isinstance(chunk, dict) and ("text" in chunk or "reset" in chunk):
                    session.bus.push("token", dict(chunk))
        except Exception as exc:      # 图执行意外崩溃：提示但保留会话（可重连续玩）
            session.bus.push("error", {"message": f"图执行失败：{exc}"})
        finally:
            session.driving = False
        self._push_snapshot(session)

    def _push_snapshot(self, session: RoomSession) -> None:
        """驱动收口：从 L2 读权威结果推送，并决定下一步（开窗/暂停/结束）。"""
        snap = session.graph.get_state(session.config)
        values = snap.values or {}
        finished_turn = max(int(values.get("turn_id", 1)) - 1, 0)
        for row in session.repo.list_dice_records(session.campaign_id,
                                                  session.branch_id,
                                                  turn_id=finished_turn):
            session.bus.push("dice", _dice_payload(row))
        for event in session.repo.list_events(session.campaign_id, session.branch_id,
                                              types=["clue"]):
            if event.id is not None and event.id > session.last_clue_id:
                session.last_clue_id = event.id
                session.bus.push("clue", json.loads(event.payload_json))
        for event in session.repo.list_events(session.campaign_id, session.branch_id,
                                              types=["scene_changed"]):
            if event.id is not None and event.id > session.last_scene_id:
                session.last_scene_id = event.id
                changed = json.loads(event.payload_json)
                payload = _scene_payload(session, changed.get("to_scene"))
                if payload is not None:
                    session.prev_scene = payload["scene_id"]
                    session.bus.push("scene", {**payload,
                                               "reason": changed.get("reason", "")})
        scene_id = values.get("scene_id")
        if scene_id and session.prev_scene is None:      # 首推兜底：本会话尚未推送过场景
            payload = _scene_payload(session, scene_id)
            if payload is not None:
                session.prev_scene = payload["scene_id"]
                session.bus.push("scene", payload)
        session.bus.push("state", self._state_payload(session))

        error = values.get("error")
        if error == "budget_paused":
            session.bus.push("error", {"message": "本局预算已熔断暂停（budget paused）。"})
            session.bus.push("turn", {"phase": "paused",
                                      "turn_id": int(values.get("turn_id", 0))})
            return
        if error:
            session.bus.push("error", {"message": f"本回合失败：{error}，请重新输入"})
        if snap.next == ("wait_input",):
            self._open_window(session)
            return
        if not snap.next:
            ending = values.get("ending_reached")
            if ending:
                session.ended = True
                session.bus.push("turn", {"phase": "ended", "ending_reached": ending})
            return
        session.bus.push("turn", {"phase": "paused",
                                  "turn_id": int(values.get("turn_id", 0))})

    # ---------- 输入窗口 ----------

    def _open_window(self, session: RoomSession) -> None:
        players = [p.id for p in session.repo.list_players(session.campaign_id)]
        snap = session.graph.get_state(session.config)
        turn_id = int((snap.values or {}).get("turn_id", 0))
        session.window_started = time.time()
        epoch = session.buffer.open(turn_id, players, now=session.window_started)
        session.bus.push("turn", {"phase": "collecting", "turn_id": turn_id})
        if session.window_task is not None and not session.window_task.done():
            session.window_task.cancel()
        session.window_task = asyncio.create_task(self._window_timer(session, epoch))

    async def _window_timer(self, session: RoomSession, epoch: int) -> None:
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            buf = session.buffer
            if buf.epoch != epoch:      # 窗口已被替换或关闭：本定时器退出
                return
            if buf.should_close(time.time(), session.window_started):
                payload = buf.close()
                await self._drive(session,
                                  Command(resume=payload,
                                          update={"branch_id": session.branch_id}))
                return

    # ---------- 快照 ----------

    def _state_payload(self, session: RoomSession) -> dict:
        values = session.graph.get_state(session.config).values or {}
        campaign_id, branch_id = session.campaign_id, session.branch_id
        seen, clues = set(), []
        for event in session.repo.list_events(campaign_id, branch_id, types=["clue"]):
            payload = json.loads(event.payload_json)
            if payload.get("clue_id") not in seen:
                seen.add(payload.get("clue_id"))
                clues.append(payload)
        segments = []
        for event in session.repo.list_events(campaign_id, branch_id,
                                              types=["narration"]):
            segments.extend(json.loads(event.payload_json).get("segments", []))
        return {"campaign_id": campaign_id, "branch_id": branch_id,
                "turn_id": int(values.get("turn_id", 0)),
                "scene_id": values.get("scene_id"),
                "characters": session.repo.list_characters_at(campaign_id, branch_id,
                                                              10**9),
                "clues_revealed": clues,
                "ending_reached": values.get("ending_reached"),
                "segments": segments,
                "cost_usd": session.repo.campaign_cost_total(campaign_id)}

    def resync_payload(self, session: RoomSession) -> dict:
        """重连 gap 时的全量对齐：状态快照（含权威叙事分段）+ 最近骰子 + 当前相位。"""
        payload = self._state_payload(session)
        rows = session.repo.list_dice_records(session.campaign_id, session.branch_id)
        phase = ("ended" if session.ended else
                 "collecting" if session.buffer.phase == "collecting" else "resolving")
        payload.update({"dice": [_dice_payload(r) for r in rows[-12:]],
                        "phase": phase})
        return payload
```

- [ ] **Step 5: 验证通过（含 M2 回归）**

Run: `cd backend; uv run pytest tests/api -q; uv run pytest tests/graph tests/storage tests/rules -q`
Expected: PASS —— 新用例全绿；M2 回归全绿（db.py 改动不影响既有测试）

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/session.py backend/app/storage/db.py backend/app/graph/main.py backend/pyproject.toml backend/tests/api/test_session.py
git commit -m "feat(api): room session manager driving graph via custom stream with windows and resync"
```

---

### Task M3-11: FastAPI 装配扩展与 WebSocket 端点

**Files:**
- Create: `backend/app/api/ws.py`
- Modify: `backend/app/api/app.py`（替换 T5 的 `create_app`：自动装配 SessionManager、挂 ws router、lifespan 清理）
- Test: `backend/tests/api/test_ws.py`

**Interfaces:**
- Consumes: `SessionManager`/`RoomSession`（M3-10）、`EventBus`/`WsEvent`（M3-8）、`AppDeps`（M3-5）
- Produces：
  - `GET /ws/campaign/{campaign_id}?player_id=<id>&resume_from=<seq>`
    - 校验：`manager` 未装配 → close `4403`；玩家不存在或跨战役 → close `4404`
    - 建连：`accept` → `ensure_started` → `subscribe` → 回放策略：
      - `resume_from == 0 且无 gap`：逐条回放缓冲（含开场以来的全部 token——F5 刷新即可恢复完整叙事）
      - `resume_from > 0 且无 gap`：只回放增量
      - `gap`：发一条全量 `state` 事件（payload = `manager.resync_payload(session)`，seq 取 `current_seq`）
    - 服务循环：sender（订阅队列 → `send_text`）+ receiver（`{"type":"input","text":...}` → `manager.handle_submit`）
    - 断开：`unsubscribe`；客户端先断/服务端先断均安全
  - `create_app(deps)`（替换 T5 版本）：`deps.manager is None` 时自动 `SessionManager(deps)`；lifespan shutdown 调用 `manager.close()`
  - `AppDeps.manager` 类型更新为 `SessionManager | None`（T5 的 `object | None` 收窄）

- [ ] **Step 1: 写失败测试**

`backend/tests/api/test_ws.py`：
```python
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
TURN_DECIDE = ('{"intent_summary": "调查", "checks": [], "proactive_npc_triggers": [],'
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
def app(tmp_path):
    engine = make_engine(str(tmp_path / "ws.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "ws.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=3.0)
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。",
                              TURN_DECIDE, "你蹲下查看井边。"])
    deps = AppDeps(settings=settings, repo=repo, model_factory=factory)
    campaign = repo.create_campaign("misty_hollow", "联调")
    player = repo.add_player(campaign.id, "张三")
    char = make_default_character(player.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    return create_app(deps), campaign, player


def test_ws_full_round_trip(app):
    application, campaign, player = app
    last_seq = 0
    seen = set()
    with TestClient(application) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            turn_id = None
            while turn_id is None:                      # 收开场流直到窗口打开
                evt = json.loads(ws.receive_text())
                assert evt["seq"] > last_seq            # seq 严格单调
                last_seq = evt["seq"]
                seen.add(evt["type"])
                if evt["type"] == "turn" and evt["payload"].get("phase") == "collecting":
                    turn_id = evt["payload"]["turn_id"]
            assert turn_id == 1
            assert "token" in seen and "scene" in seen and "state" in seen

            ws.send_text(json.dumps({"type": "input", "text": "我绕到喷泉后面"}))

            got2 = False
            while not got2:                             # 等第二轮窗口
                evt = json.loads(ws.receive_text())
                assert evt["seq"] > last_seq
                last_seq = evt["seq"]
                if (evt["type"] == "turn" and evt["payload"].get("phase") == "collecting"
                        and evt["payload"].get("turn_id") == 2):
                    got2 = True
            assert got2


def test_ws_rejects_ghost_player(app):
    application, campaign, player = app
    with TestClient(application) as client:
        url = f"/ws/campaign/{campaign.id}?player_id=ghost"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url) as ws:
                ws.receive_text()
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_ws.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.api.ws'`

- [ ] **Step 3: 实现 ws.py 与 app.py 修改**

`backend/app/api/ws.py`：
```python
"""WebSocket 端点：实时事件流 + 玩家输入。"""
import asyncio
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.events import WsEvent

router = APIRouter()


def _deps(websocket: WebSocket):
    return websocket.app.state.deps


@router.websocket("/ws/campaign/{campaign_id}")
async def ws_campaign(websocket: WebSocket, campaign_id: str,
                      player_id: str = Query(...), resume_from: int = Query(0)):
    deps = _deps(websocket)
    if deps.manager is None:
        await websocket.close(code=4403)
        return
    player = deps.repo.get_player(player_id)
    if player is None or player.campaign_id != campaign_id:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        session = await deps.manager.ensure_started(campaign_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    sub = session.bus.subscribe(player_id)
    try:
        events, gap = session.bus.replay(resume_from, player_id)
        if gap:
            resync = WsEvent(seq=session.bus.current_seq, type="state",
                             visibility="all",
                             payload=deps.manager.resync_payload(session))
            await websocket.send_text(resync.to_json())
        else:
            for evt in events:
                await websocket.send_text(evt.to_json())
        await _serve(websocket, session, sub, deps.manager, campaign_id, player_id)
    finally:
        session.bus.unsubscribe(sub)


async def _serve(websocket, session, sub, manager, campaign_id, player_id):
    async def sender():
        while True:
            evt = await sub.queue.get()
            await websocket.send_text(evt.to_json())

    async def receiver():
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "input":
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            try:
                await manager.handle_submit(campaign_id, player_id, text)
            except KeyError:
                continue

    sender_task = asyncio.create_task(sender())
    receiver_task = asyncio.create_task(receiver())
    try:
        await asyncio.wait({sender_task, receiver_task},
                           return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        receiver_task.cancel()
        await asyncio.gather(sender_task, receiver_task, return_exceptions=True)
```

`backend/app/api/app.py` 替换为：
```python
"""FastAPI 装配：REST + WS + 会话驱动生命周期。"""
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.session import SessionManager
from app.config import Settings
from app.storage.repo import SqliteRepository


@dataclass
class AppDeps:
    settings: Settings
    repo: SqliteRepository
    model_factory: object | None = None   # ModelFactory；测试注入 FakeLLM 工厂
    manager: SessionManager | None = None


def create_app(deps: AppDeps) -> FastAPI:
    from app.api import routes
    from app.api import ws as ws_module

    if deps.manager is None:
        deps.manager = SessionManager(deps)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        await deps.manager.close()

    app = FastAPI(title="Ensemble", lifespan=_lifespan)
    app.state.deps = deps
    app.add_middleware(CORSMiddleware, allow_origins=deps.settings.cors_origin_list,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(routes.router)
    app.include_router(ws_module.router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
```

- [ ] **Step 4: 验证通过（含 M2 与 M3 全量回归）**

Run: `cd backend; uv run pytest tests/api -q; uv run pytest -q`
Expected: PASS —— 新用例全绿；后端全量测试全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ws.py backend/app/api/app.py backend/tests/api/test_ws.py
git commit -m "feat(api): websocket endpoint with replay/resync and full app wiring"
```

---

### Task M3-12: 前端脚手架与 REST/WS 客户端

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/styles.css`, `frontend/src/test-setup.ts`
- Create: `frontend/src/types.ts`, `frontend/src/api/rest.ts`, `frontend/src/api/ws.ts`
- Test: `frontend/src/api/__tests__/rest.test.ts`、`frontend/src/api/__tests__/ws.test.ts`

**Interfaces:**
- Consumes: 后端 REST（M3-5/6/7）与 WS 协议（M3-8 事件枚举）；vite 代理 `/api`、`/ws` → `http://localhost:8000`
- Produces：
  - `types.ts`：`WsEvent`（按 `type` 的判别联合）、`Segment`、`DicePayload`、`TurnPayload`、`ScenePayload`、`CluePayload`、`StatePayload`、`NoticePayload`、`ModuleInfo`、`CampaignInfo`、`CreateResult`、`CampaignDetail`、`BranchInfo`、`Timeline`
  - `api/rest.ts`：`api.modules() / api.campaigns() / api.createCampaign(moduleId, title, playerName) / api.campaign(id) / api.timeline(id) / api.switchBranch(id, branchId) / api.restore(id, turnId)`
  - `api/ws.ts`：`WsClient(campaignId, playerId, handlers)`：`connect()`（自动重连，指数退避，`resume_from=lastSeq`）、`sendInput(text)`、`close()`；`handlers = { onEvent, onStatus }`

- [ ] **Step 1: 创建工程文件**

`frontend/package.json`：
```json
{
  "name": "ensemble-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^4.5.4"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

`frontend/vite.config.ts`：
```ts
/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: false,
  },
});
```

`frontend/tsconfig.json`：
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

`frontend/index.html`：
```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Ensemble · AI 跑团</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/test-setup.ts`：
```ts
import "@testing-library/jest-dom";
```

`frontend/src/main.tsx`（**不用 StrictMode**：避免开发模式双挂载造成 WS 双连接；备注在文件头）：
```tsx
// 不用 React.StrictMode：避免开发模式 effect 双执行造成 WebSocket 双连接。
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
```

`frontend/src/styles.css`（基础暗色主题；后续任务追加各自区块样式）：
```css
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  background: #14161a;
  color: #e8e6e3;
}
button {
  background: #2c3440; color: #e8e6e3; border: 1px solid #3d4757;
  border-radius: 6px; padding: 6px 14px; cursor: pointer;
}
button:disabled { opacity: 0.45; cursor: not-allowed; }
input, select {
  background: #1d222b; color: #e8e6e3; border: 1px solid #3d4757;
  border-radius: 6px; padding: 6px 10px;
}
.error-banner { background: #4a2020; border: 1px solid #8a3b3b;
  padding: 8px 12px; border-radius: 6px; margin: 8px 0; }
.lobby { max-width: 720px; margin: 0 auto; padding: 32px 16px; }
.lobby section { margin-top: 28px; }
.lobby label { display: block; margin: 10px 0; }
.lobby input, .lobby select { margin-left: 8px; min-width: 200px; }
.lobby ul { list-style: none; padding: 0; }
.lobby li { display: flex; justify-content: space-between; align-items: center;
  padding: 8px 0; border-bottom: 1px solid #262c36; }
.room { display: flex; flex-direction: column; height: 100vh; }
.room-header { display: flex; align-items: center; gap: 16px;
  padding: 10px 16px; border-bottom: 1px solid #262c36; }
.room-main { flex: 1; display: flex; overflow: hidden; }
.room-story { flex: 1; overflow-y: auto; padding: 20px 28px; line-height: 1.9; }
.room-side { width: 300px; border-left: 1px solid #262c36; overflow-y: auto;
  padding: 12px 16px; }
.room-footer { border-top: 1px solid #262c36; padding: 12px 16px;
  display: flex; gap: 10px; }
.room-footer input { flex: 1; }
.seg-gm { margin: 0 0 12px; white-space: pre-wrap; }
.seg-npc { margin: 0 0 12px; white-space: pre-wrap; color: #ffd88a; }
.seg-npc .npc-name { color: #ffb84d; font-weight: 600; margin-right: 6px; }
.cursor::after { content: "▍"; animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.conn-badge { font-size: 12px; padding: 2px 8px; border-radius: 10px;
  background: #3d2b2b; }
.conn-badge.open { background: #25402b; }
```

- [ ] **Step 2: 写失败测试**

`frontend/src/api/__tests__/rest.test.ts`：
```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../rest";

afterEach(() => vi.unstubAllGlobals());

describe("rest", () => {
  it("GETs modules and parses json", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => [{ id: "m", title: "M" }],
    });
    vi.stubGlobal("fetch", fetchMock);
    const mods = await api.modules();
    expect(fetchMock).toHaveBeenCalledWith("/api/modules", undefined);
    expect(mods[0].id).toBe("m");
  });

  it("POSTs create campaign with json body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ campaign_id: "c1" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await api.createCampaign("misty_hollow", "初探", "张三");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toBe("/api/campaigns");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      module_id: "misty_hollow", title: "初探", player_name: "张三",
    });
  });

  it("throws on non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 404, text: async () => "not found",
    }));
    await expect(api.modules()).rejects.toThrow("404");
  });
});
```

`frontend/src/api/__tests__/ws.test.ts`：
```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WsClient } from "../ws";

class FakeWS {
  static instances: FakeWS[] = [];
  static OPEN = 1;
  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  constructor(url: string) {
    this.url = url;
    FakeWS.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

beforeEach(() => {
  FakeWS.instances = [];
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function makeClient() {
  const events: unknown[] = [];
  const client = new WsClient("c1", "p1", {
    onEvent: (e) => events.push(e),
    onStatus: () => {},
  });
  client.connect();
  return { client, events };
}

describe("WsClient", () => {
  it("connects with resume_from and forwards seq tracked events", () => {
    const { client, events } = makeClient();
    const ws = FakeWS.instances[0];
    expect(ws.url).toContain("/ws/campaign/c1?player_id=p1&resume_from=0");
    ws.readyState = 1;
    ws.onmessage!({
      data: JSON.stringify({ seq: 5, type: "token", visibility: "all",
                             payload: { speaker: "gm", text: "x" } }),
    });
    expect(events).toHaveLength(1);
    client.close();
  });

  it("reconnects with updated resume_from after close", () => {
    const { client } = makeClient();
    const first = FakeWS.instances[0];
    first.readyState = 1;
    first.onmessage!({
      data: JSON.stringify({ seq: 7, type: "turn", visibility: "all",
                             payload: { phase: "collecting", turn_id: 1 } }),
    });
    first.onclose!();                                    // 服务端断开
    vi.advanceTimersByTime(1500);                        // 越过首次退避
    expect(FakeWS.instances).toHaveLength(2);
    expect(FakeWS.instances[1].url).toContain("resume_from=7");
    client.close();
  });

  it("sendInput sends json input frame only when open", () => {
    const { client } = makeClient();
    const ws = FakeWS.instances[0];
    client.sendInput("我进门");                          // 未 open：丢弃
    expect(ws.sent).toHaveLength(0);
    ws.readyState = 1;
    client.sendInput("我进门");
    expect(JSON.parse(ws.sent[0])).toEqual({ type: "input", text: "我进门" });
    client.close();
  });
});
```

- [ ] **Step 3: 验证失败**

Run: `cd frontend; npm install; npm run test`
Expected: FAIL —— `Failed to resolve import "../rest"`（文件未创建）

- [ ] **Step 4: 实现 types.ts / rest.ts / ws.ts**

`frontend/src/types.ts`：
```ts
export type Segment = { speaker: string; text: string };

export type TokenPayload = { speaker?: string; text?: string; reset?: boolean };
export type DicePayload = {
  actor: string; skill: string; skill_value: number; difficulty: string;
  roll: number; level: string; seed: number; success: boolean;
};
export type TurnPayload = {
  phase: "resolving" | "collecting" | "ended" | "paused";
  turn_id?: number;
  ending_reached?: string | null;
};
export type ScenePayload = {
  scene_id: string; name: string; description: string; npcs: string[];
};
export type CluePayload = { clue_id: string; text: string };
export type StatePayload = {
  campaign_id: string; branch_id: string; turn_id: number;
  scene_id: string | null; characters: unknown[]; clues_revealed: CluePayload[];
  ending_reached: string | null; cost_usd: number;
  segments?: Segment[]; dice?: DicePayload[]; phase?: string;
};
export type NoticePayload = { message?: string; kind?: string; status?: string };
export type ErrorPayload = { message: string };

export type WsEvent =
  | { seq: number; type: "token"; visibility: string; payload: TokenPayload }
  | { seq: number; type: "dice"; visibility: string; payload: DicePayload }
  | { seq: number; type: "actor"; visibility: string;
      payload: { player_id: string; text: string } }
  | { seq: number; type: "scene"; visibility: string; payload: ScenePayload }
  | { seq: number; type: "turn"; visibility: string; payload: TurnPayload }
  | { seq: number; type: "state"; visibility: string; payload: StatePayload }
  | { seq: number; type: "clue"; visibility: string; payload: CluePayload }
  | { seq: number; type: "notice"; visibility: string; payload: NoticePayload }
  | { seq: number; type: "error"; visibility: string; payload: ErrorPayload };

export type ModuleInfo = { id: string; title: string; version: string; path: string };
export type CampaignInfo = {
  id: string; title: string; module_id: string; active_branch_id: string;
  created_at: string;
};
export type CreateResult = {
  campaign_id: string; branch_id: string; player_id: string; character_id: string;
};
export type CampaignDetail = {
  id: string; title: string; module_id: string; module_title: string;
  active_branch_id: string; scene_id: string | null; turn_id: number;
  cost_usd: number; players: { id: string; display_name: string }[];
  characters: unknown[]; clues_revealed: CluePayload[];
};
export type BranchInfo = {
  id: string; name: string; parent_branch_id: string | null;
  fork_turn_id: number | null; completed_turns: number; created_at: string;
};
export type Timeline = { active_branch_id: string; branches: BranchInfo[] };
```

`frontend/src/api/rest.ts`：
```ts
import type {
  CampaignDetail, CampaignInfo, CreateResult, ModuleInfo, Timeline,
} from "../types";

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    throw new Error(`${resp.status}: ${await resp.text()}`);
  }
  return (await resp.json()) as T;
}

function postJson<T>(url: string, body: unknown): Promise<T> {
  return jsonFetch<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  modules: () => jsonFetch<ModuleInfo[]>("/api/modules"),
  campaigns: () => jsonFetch<CampaignInfo[]>("/api/campaigns"),
  createCampaign: (moduleId: string, title: string, playerName: string) =>
    postJson<CreateResult>("/api/campaigns", {
      module_id: moduleId, title, player_name: playerName,
    }),
  campaign: (id: string) => jsonFetch<CampaignDetail>(`/api/campaigns/${id}`),
  timeline: (id: string) => jsonFetch<Timeline>(`/api/campaigns/${id}/timeline`),
  switchBranch: (id: string, branchId: string) =>
    postJson<{ active_branch_id: string }>(`/api/campaigns/${id}/switch`, {
      branch_id: branchId,
    }),
  restore: (id: string, turnId: number) =>
    postJson<{ branch_id: string; name: string }>(`/api/campaigns/${id}/restore`, {
      turn_id: turnId,
    }),
};
```

`frontend/src/api/ws.ts`：
```ts
import type { WsEvent } from "../types";

export type WsHandlers = {
  onEvent: (evt: WsEvent) => void;
  onStatus: (status: "connecting" | "open" | "closed") => void;
};

/** 断线自动重连（指数退避），resume_from 定位到已收到的最大 seq（重放补齐）。 */
export class WsClient {
  private ws: WebSocket | null = null;
  private lastSeq = 0;
  private retry = 0;
  private closedByUser = false;

  constructor(
    private campaignId: string,
    private playerId: string,
    private handlers: WsHandlers,
  ) {}

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  private open(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/campaign/${this.campaignId}` +
      `?player_id=${this.playerId}&resume_from=${this.lastSeq}`;
    this.handlers.onStatus("connecting");
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.handlers.onStatus("open");
    };
    ws.onmessage = (msg: { data: string }) => {
      const evt = JSON.parse(msg.data) as WsEvent;
      if (evt.seq > this.lastSeq) this.lastSeq = evt.seq;
      this.handlers.onEvent(evt);
    };
    ws.onclose = () => {
      this.handlers.onStatus("closed");
      if (!this.closedByUser) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = Math.min(1000 * 2 ** this.retry, 15000);
    this.retry += 1;
    setTimeout(() => this.open(), delay);
  }

  sendInput(text: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "input", text }));
    }
  }

  close(): void {
    this.closedByUser = true;
    this.ws?.close();
  }
}
```

- [ ] **Step 5: 验证通过**

Run: `cd frontend; npm run test; npm run build`
Expected: PASS（6 passed）；build 成功（tsc 无类型错误）

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): vite scaffold with typed rest client and reconnecting ws client"
```

---

### Task M3-13: 前端状态层（reducer + zustand store）

**Files:**
- Create: `frontend/src/stores/game.ts`
- Test: `frontend/src/stores/__tests__/game.test.ts`

**Interfaces:**
- Consumes: `WsEvent` 判别联合（M3-12）
- Produces：
  - `GameState` 字段（**全前端固定命名**）：`phase`（`idle|resolving|collecting|paused|ended`）、`turnId`、`segments`（权威分段）、`live`（流式增量，与上一段同 speaker 自动拼接）、`scene`（详情）、`sceneId`、`characters`、`clues`（按 `clue_id` 去重）、`diceLog`（最近 20）、`diceQueue`（待播动画）、`actors`（最近 20）、`notice`、`errorMessage`、`endingReached`、`costUsd`
  - `reduceEvent(state, evt) -> GameState`（**纯函数**，全部 UI 状态变化的唯一入口）
  - `useGame`（zustand store）：`apply(evt)` / `dicePlayed()`（动画出队）/ `setConnected(v)` / `connected` / `reset()`
  - 关键规则：
    - `token.reset` → 清空 `live`；`token` 文本按 `speaker` 与上一段合并
    - `turn.resolving` → 清空 `live`、清 `errorMessage`（新回合开始）
    - `state` 事件：`segments` 非空时**整体替换**（权威分段覆盖增量近似）；`dice` 存在（resync）时重置 `diceLog`（历史不重播动画）
    - `clue` 去重；`turn.ended.ending_reached` 与 `state.ending_reached` 均更新结局

- [ ] **Step 1: 写失败测试**

`frontend/src/stores/__tests__/game.test.ts`：
```ts
import { describe, expect, it } from "vitest";

import { initialState, reduceEvent } from "../game";
import type { WsEvent } from "../../types";

function evt(type: WsEvent["type"], payload: unknown, seq = 1): WsEvent {
  return { seq, type, visibility: "all", payload } as WsEvent;
}

describe("reduceEvent", () => {
  it("accumulates token deltas by speaker and resets on reset", () => {
    let s = reduceEvent(initialState, evt("token", { speaker: "gm", text: "雾" }));
    s = reduceEvent(s, evt("token", { speaker: "gm", text: "气" }));
    s = reduceEvent(s, evt("token", { speaker: "npc:elder", text: "来" }));
    expect(s.live).toEqual([
      { speaker: "gm", text: "雾气" },
      { speaker: "npc:elder", text: "来" },
    ]);
    s = reduceEvent(s, evt("token", { reset: true }));
    expect(s.live).toEqual([]);
  });

  it("replaces segments with authoritative state snapshot and clears live", () => {
    let s = reduceEvent(initialState, evt("token", { speaker: "gm", text: "增量" }));
    s = reduceEvent(s, evt("state", {
      campaign_id: "c", branch_id: "b", turn_id: 1, scene_id: "square",
      characters: [], clues_revealed: [], ending_reached: null, cost_usd: 0.01,
      segments: [{ speaker: "gm", text: "权威分段" }],
    }));
    expect(s.segments).toEqual([{ speaker: "gm", text: "权威分段" }]);
    expect(s.live).toEqual([]);
    expect(s.costUsd).toBeCloseTo(0.01);
    expect(s.sceneId).toBe("square");
  });

  it("queues dice for animation and logs them", () => {
    const dice = { actor: "pc_p1", skill: "侦查", skill_value: 50,
                   difficulty: "regular", roll: 12, level: "hard",
                   seed: 1, success: true };
    const s = reduceEvent(initialState, evt("dice", dice));
    expect(s.diceQueue).toHaveLength(1);
    expect(s.diceLog).toHaveLength(1);
  });

  it("deduplicates clues and tracks ending phase", () => {
    const clue = { clue_id: "clue_diary", text: "一本日记" };
    let s = reduceEvent(initialState, evt("clue", clue));
    s = reduceEvent(s, evt("clue", clue));
    expect(s.clues).toHaveLength(1);
    s = reduceEvent(s, evt("turn", { phase: "ended", ending_reached: "ending_break" }));
    expect(s.endingReached).toBe("ending_break");
    expect(s.phase).toBe("ended");
  });

  it("resolving clears live and previous error", () => {
    let s = reduceEvent(initialState, evt("error", { message: "boom" }));
    s = reduceEvent(s, evt("turn", { phase: "resolving", turn_id: 2 }));
    expect(s.errorMessage).toBeNull();
    expect(s.phase).toBe("resolving");
  });

  it("captures notice message or submit status", () => {
    let s = reduceEvent(initialState, evt("notice", { message: "已提交" }));
    expect(s.notice).toBe("已提交");
    s = reduceEvent(initialState, evt("notice", { kind: "submit", status: "deferred" }));
    expect(s.notice).toBe("deferred");
  });
});
```

- [ ] **Step 2: 验证失败**

Run: `cd frontend; npm run test`
Expected: FAIL —— `Failed to resolve import "../game"`

- [ ] **Step 3: 实现 game.ts**

`frontend/src/stores/game.ts`：
```ts
import { create } from "zustand";

import type {
  CluePayload, DicePayload, ScenePayload, Segment, WsEvent,
} from "../types";

export type Phase = "idle" | "resolving" | "collecting" | "paused" | "ended";

export type GameState = {
  phase: Phase;
  turnId: number;
  segments: Segment[];
  live: Segment[];
  scene: ScenePayload | null;
  sceneId: string | null;
  characters: unknown[];
  clues: CluePayload[];
  diceLog: DicePayload[];
  diceQueue: DicePayload[];
  actors: { player_id: string; text: string }[];
  notice: string | null;
  errorMessage: string | null;
  endingReached: string | null;
  costUsd: number;
};

export const initialState: GameState = {
  phase: "idle",
  turnId: 0,
  segments: [],
  live: [],
  scene: null,
  sceneId: null,
  characters: [],
  clues: [],
  diceLog: [],
  diceQueue: [],
  actors: [],
  notice: null,
  errorMessage: null,
  endingReached: null,
  costUsd: 0,
};

export function reduceEvent(state: GameState, evt: WsEvent): GameState {
  switch (evt.type) {
    case "token": {
      const { speaker, text, reset } = evt.payload;
      if (reset) return { ...state, live: [] };
      if (!speaker || !text) return state;
      const live = [...state.live];
      const last = live[live.length - 1];
      if (last && last.speaker === speaker) {
        live[live.length - 1] = { speaker, text: last.text + text };
      } else {
        live.push({ speaker, text });
      }
      return { ...state, live };
    }
    case "turn": {
      const { phase, turn_id, ending_reached } = evt.payload;
      const base: GameState = {
        ...state,
        phase,
        turnId: turn_id ?? state.turnId,
      };
      if (phase === "resolving") {
        base.live = [];
        base.errorMessage = null;
      }
      if (ending_reached) base.endingReached = ending_reached;
      return base;
    }
    case "state": {
      const p = evt.payload;
      const next: GameState = {
        ...state,
        turnId: p.turn_id,
        sceneId: p.scene_id,
        characters: p.characters,
        clues: p.clues_revealed,
        costUsd: p.cost_usd,
        endingReached: p.ending_reached ?? state.endingReached,
      };
      if (p.segments && p.segments.length > 0) {
        next.segments = p.segments;
        next.live = [];
      }
      if (p.dice) next.diceLog = p.dice;
      if (p.phase && state.phase === "idle") next.phase = p.phase as Phase;
      return next;
    }
    case "scene":
      return { ...state, scene: evt.payload, sceneId: evt.payload.scene_id };
    case "clue": {
      if (state.clues.some((c) => c.clue_id === evt.payload.clue_id)) return state;
      return { ...state, clues: [...state.clues, evt.payload] };
    }
    case "dice":
      return {
        ...state,
        diceLog: [...state.diceLog, evt.payload].slice(-20),
        diceQueue: [...state.diceQueue, evt.payload],
      };
    case "actor":
      return { ...state, actors: [...state.actors, evt.payload].slice(-20) };
    case "notice":
      return {
        ...state,
        notice: evt.payload.message ?? evt.payload.status ?? "提示",
      };
    case "error":
      return { ...state, errorMessage: evt.payload.message };
    default:
      return state;
  }
}

type GameStore = GameState & {
  connected: boolean;
  apply: (evt: WsEvent) => void;
  dicePlayed: () => void;
  setConnected: (v: boolean) => void;
  reset: () => void;
};

export const useGame = create<GameStore>((set) => ({
  ...initialState,
  connected: false,
  apply: (evt) => set((s) => reduceEvent(s, evt)),
  dicePlayed: () => set((s) => ({ diceQueue: s.diceQueue.slice(1) })),
  setConnected: (v) => set({ connected: v }),
  reset: () => set({ ...initialState, connected: false }),
}));
```

- [ ] **Step 4: 验证通过**

Run: `cd frontend; npm run test; npm run build`
Expected: PASS（6 passed）；build 成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores
git commit -m "feat(frontend): pure event reducer and zustand game store"
```

---

### Task M3-14: Lobby 页与会话导航（Room 壳）

**Files:**
- Create: `frontend/src/session.ts`, `frontend/src/views/Lobby.tsx`, `frontend/src/views/Room.tsx`, `frontend/src/App.tsx`
- Test: `frontend/src/views/__tests__/Lobby.test.tsx`

**Interfaces:**
- Consumes: `api`（M3-12）、`Session`（localStorage 持久化：`{campaignId, playerId, title}`）
- Produces：
  - `session.ts`：`loadSession() / saveSession(s) / clearSession()`
  - `Lobby({ onEnter })`：模组下拉（`api.modules`）+ 新建（`api.createCampaign`）+ 存档列表（`api.campaigns` → 继续时 `api.campaign(id)` 取 `players[0].id`；**M3 单人假设，M4 改为邀请码/选择玩家**）
  - `Room({ session, onLeave })`（本任务为壳：标题 + 返回按钮；T15 接入 WS 与叙事流）
  - `App`：无 session → Lobby；有 → Room；退出时清除 localStorage

- [ ] **Step 1: 写失败测试**

`frontend/src/views/__tests__/Lobby.test.tsx`：
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Lobby from "../Lobby";
import { api } from "../../api/rest";

vi.mock("../../api/rest", () => ({
  api: {
    modules: vi.fn(),
    campaigns: vi.fn(),
    createCampaign: vi.fn(),
    campaign: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.modules.mockResolvedValue([
    { id: "misty_hollow", title: "迷雾幽谷", version: "0.1", path: "" },
  ]);
  mocked.campaigns.mockResolvedValue([]);
});

describe("Lobby", () => {
  it("creates a campaign and enters the room", async () => {
    mocked.createCampaign.mockResolvedValue({
      campaign_id: "c1", branch_id: "c1@main",
      player_id: "p1", character_id: "pc_p1",
    });
    const onEnter = vi.fn();
    render(<Lobby onEnter={onEnter} />);
    await screen.findByText("迷雾幽谷");
    await userEvent.click(screen.getByText("开始跑团"));
    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith({
        campaignId: "c1", playerId: "p1", title: "迷雾山谷",
      }),
    );
  });

  it("continues an existing campaign using its first player", async () => {
    mocked.campaigns.mockResolvedValue([
      { id: "c9", title: "旧档", module_id: "misty_hollow",
        active_branch_id: "c9@main", created_at: "" },
    ]);
    mocked.campaign.mockResolvedValue({
      id: "c9", title: "旧档", module_id: "misty_hollow", module_title: "迷雾幽谷",
      active_branch_id: "c9@main", scene_id: "square", turn_id: 2, cost_usd: 0.1,
      players: [{ id: "p9", display_name: "张三" }],
      characters: [], clues_revealed: [],
    } as never);
    const onEnter = vi.fn();
    render(<Lobby onEnter={onEnter} />);
    await userEvent.click(await screen.findByText("继续"));
    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith({
        campaignId: "c9", playerId: "p9", title: "旧档",
      }),
    );
  });
});
```

- [ ] **Step 2: 验证失败**

Run: `cd frontend; npm run test`
Expected: FAIL —— `Failed to resolve import "../Lobby"`

- [ ] **Step 3: 实现 session.ts / Lobby.tsx / Room.tsx / App.tsx**

`frontend/src/session.ts`：
```ts
export type Session = { campaignId: string; playerId: string; title: string };

const KEY = "ensemble.session";

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session): void {
  localStorage.setItem(KEY, JSON.stringify(s));
}

export function clearSession(): void {
  localStorage.removeItem(KEY);
}
```

`frontend/src/views/Lobby.tsx`：
```tsx
import { useEffect, useState } from "react";

import { api } from "../api/rest";
import type { Session } from "../session";
import type { CampaignInfo, ModuleInfo } from "../types";

export default function Lobby({ onEnter }: { onEnter: (s: Session) => void }) {
  const [modules, setModules] = useState<ModuleInfo[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignInfo[]>([]);
  const [moduleId, setModuleId] = useState("");
  const [title, setTitle] = useState("迷雾山谷");
  const [playerName, setPlayerName] = useState("调查员");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.modules()
      .then((ms) => {
        setModules(ms);
        setModuleId(ms[0]?.id ?? "");
      })
      .catch((e) => setError(String(e)));
    api.campaigns().then(setCampaigns).catch(() => {});
  }, []);

  async function create() {
    if (!moduleId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.createCampaign(moduleId, title, playerName);
      onEnter({ campaignId: r.campaign_id, playerId: r.player_id, title });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function continueCampaign(c: CampaignInfo) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const detail = await api.campaign(c.id);
      const player = detail.players[0]; // M3 单人；M4 改为邀请码/选择玩家
      if (!player) throw new Error("战役没有玩家记录");
      onEnter({ campaignId: c.id, playerId: player.id, title: c.title });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lobby">
      <h1>Ensemble · AI 跑团</h1>
      {error && <div className="error-banner">{error}</div>}
      <section>
        <h2>新建战役</h2>
        <label>
          模组
          <select value={moduleId} onChange={(e) => setModuleId(e.target.value)}>
            {modules.map((m) => (
              <option key={m.id} value={m.id}>{m.title}</option>
            ))}
          </select>
        </label>
        <label>
          战役名
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          玩家名
          <input value={playerName} onChange={(e) => setPlayerName(e.target.value)} />
        </label>
        <button onClick={create} disabled={busy || !moduleId}>开始跑团</button>
      </section>
      <section>
        <h2>存档</h2>
        {campaigns.length === 0 && <p>暂无存档</p>}
        <ul>
          {campaigns.map((c) => (
            <li key={c.id}>
              <span>{c.title}（{c.module_id}）</span>
              <button onClick={() => continueCampaign(c)} disabled={busy}>继续</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

`frontend/src/views/Room.tsx`（本任务为壳；T15 接入 WS/叙事流/输入栏）：
```tsx
import type { Session } from "../session";

export default function Room({ session, onLeave }: {
  session: Session;
  onLeave: () => void;
}) {
  return (
    <div className="room">
      <header className="room-header">
        <button onClick={onLeave}>← 回到大厅</button>
        <h2>{session.title}</h2>
      </header>
      <main className="room-main">
        <div className="room-story" />
      </main>
      <footer className="room-footer" />
    </div>
  );
}
```

`frontend/src/App.tsx`：
```tsx
import { useState } from "react";

import Lobby from "./views/Lobby";
import Room from "./views/Room";
import { clearSession, loadSession, saveSession, type Session } from "./session";

export default function App() {
  const [session, setSession] = useState<Session | null>(() => loadSession());

  if (!session) {
    return (
      <Lobby
        onEnter={(s) => {
          saveSession(s);
          setSession(s);
        }}
      />
    );
  }
  return (
    <Room
      session={session}
      onLeave={() => {
        clearSession();
        setSession(null);
      }}
    />
  );
}
```

- [ ] **Step 4: 验证通过**

Run: `cd frontend; npm run test; npm run build`
Expected: PASS（8 passed）；build 成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src/session.ts frontend/src/views frontend/src/App.tsx
git commit -m "feat(frontend): lobby with campaign create/continue and room shell navigation"
```

---

### Task M3-15: Room 页接入（WS 连接、流式叙事、输入栏）

**Files:**
- Modify: `backend/app/api/routes.py`（追加 `GET /campaigns/{id}/module`：NPC 名字、结局条件——纯展示信息）
- Modify: `frontend/src/types.ts`（`ModuleDetail`）、`frontend/src/api/rest.ts`（`api.module`）
- Create: `frontend/src/components/NarrationStream.tsx`、`frontend/src/components/InputBar.tsx`
- Modify: `frontend/src/views/Room.tsx`（完整实现）、`frontend/src/styles.css`（notice 样式）
- Test: `backend/tests/api/test_campaigns_api.py`（追加 1 用例）、`frontend/src/components/__tests__/NarrationStream.test.tsx`、`frontend/src/views/__tests__/Room.test.tsx`

**Interfaces:**
- Consumes: `WsClient`/`api`（M3-12）、`useGame`/`GameState`（M3-13）、`NarrationStream` 数据来自 store
- Produces：
  - 后端 `GET /api/campaigns/{id}/module` → `{id, title, npcs: [{id, name}], endings: [{id, condition}]}`
  - `NarrationStream({ segments, live, npcNames? })`：gm 段普通段落；`npc:<id>` 段显示 `【名字】`（无映射时显示 id）；`live` 最后一段带 `.cursor` 光标（_打字机效果由 token 真流式天然产生_，无需独立组件）
  - `InputBar({ phase, connected, onSubmit })`：仅 `connected && phase === "collecting"` 可输入；回车提交；占位提示随相位变化（resolving/paused/ended 各有文案）
  - `Room` 完整实现：挂载时 `reset()` store → `WsClient.connect()`（事件进 `apply`，状态进 `setConnected`）→ 拉 `api.module` 得到 `npcNames`；卸载时 `client.close()`

- [ ] **Step 1: 后端 /module 端点（含测试）**

`backend/tests/api/test_campaigns_api.py` 追加：
```python
def test_campaign_module_exposes_npc_names(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "x"}).json()["campaign_id"]
    d = c.get(f"/api/campaigns/{cid}/module").json()
    assert d["id"] == "misty_hollow"
    names = {n["id"]: n["name"] for n in d["npcs"]}
    assert names.get("elder")                       # 名字非空
    assert all(e["id"] and e["condition"] for e in d["endings"])
```

`backend/app/api/routes.py` 追加：
```python
@router.get("/campaigns/{campaign_id}/module")
def campaign_module(campaign_id: str, request: Request):
    deps = _deps(request)
    try:
        campaign = deps.repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    from app.content.loader import load_module
    from app.content.registry import find_module_path
    module = load_module(find_module_path(deps.settings.modules_dir,
                                          campaign.module_id))
    return {"id": module.meta.id, "title": module.meta.title,
            "npcs": [{"id": n.id, "name": n.name} for n in module.npcs],
            "endings": [{"id": e.id, "condition": e.condition}
                        for e in module.endings]}
```

- [ ] **Step 2: 前端测试先写（失败）**

`frontend/src/components/__tests__/NarrationStream.test.tsx`：
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NarrationStream from "../NarrationStream";

describe("NarrationStream", () => {
  it("renders gm and npc segments with names", () => {
    render(
      <NarrationStream
        segments={[{ speaker: "gm", text: "雾来了。" },
                   { speaker: "npc:elder", text: "别去磨坊。" }]}
        live={[]}
        npcNames={{ elder: "村长" }}
      />,
    );
    expect(screen.getByText("雾来了。")).toBeInTheDocument();
    expect(screen.getByText("【村长】")).toBeInTheDocument();
    expect(screen.getByText("别去磨坊。")).toBeInTheDocument();
  });

  it("falls back to npc id and marks the last live segment with a cursor", () => {
    render(<NarrationStream segments={[]}
                             live={[{ speaker: "npc:ghost", text: "……" }]} />);
    expect(screen.getByText("【ghost】")).toBeInTheDocument();
    expect(screen.getByText("……").closest("p")).toHaveClass("cursor");
  });
});
```

`frontend/src/views/__tests__/Room.test.tsx`：
```tsx
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Room from "../Room";
import { useGame } from "../../stores/game";

const handlers: { onEvent?: (e: unknown) => void; onStatus?: (s: string) => void } = {};
const clientMock = { connect: vi.fn(), close: vi.fn(), sendInput: vi.fn() };

vi.mock("../../api/ws", () => ({
  WsClient: vi.fn().mockImplementation((_c: string, _p: string, h: typeof handlers) => {
    handlers.onEvent = h.onEvent as never;
    handlers.onStatus = h.onStatus as never;
    return clientMock;
  }),
}));
vi.mock("../../api/rest", () => ({
  api: {
    module: vi.fn().mockResolvedValue({
      id: "misty_hollow", title: "迷雾幽谷",
      npcs: [{ id: "elder", name: "村长" }], endings: [],
    }),
  },
}));

const SESSION = { campaignId: "c1", playerId: "p1", title: "测试局" };

beforeEach(() => {
  vi.clearAllMocks();
  useGame.getState().reset();
});

describe("Room", () => {
  it("renders streamed narration resolving npc names", async () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => {
      handlers.onStatus!("open");
      handlers.onEvent!({ seq: 1, type: "token", visibility: "all",
                          payload: { speaker: "gm", text: "雾气涌来。" } });
      handlers.onEvent!({ seq: 2, type: "token", visibility: "all",
                          payload: { speaker: "npc:elder", text: "别去磨坊。" } });
    });
    expect(await screen.findByText("雾气涌来。")).toBeInTheDocument();
    expect(await screen.findByText("【村长】")).toBeInTheDocument();
    expect(clientMock.connect).toHaveBeenCalled();
  });

  it("disables input until collecting phase", () => {
    render(<Room session={SESSION} onLeave={() => {}} />);
    act(() => handlers.onStatus!("open"));
    expect(screen.getByPlaceholderText("GM 正在处理本回合…")).toBeDisabled();
    act(() => handlers.onEvent!({ seq: 1, type: "turn", visibility: "all",
                                  payload: { phase: "collecting", turn_id: 1 } }));
    expect(screen.getByPlaceholderText("输入你的行动（回车提交）")).toBeEnabled();
  });
});
```

- [ ] **Step 3: 验证失败**

Run: `cd frontend; npm run test`
Expected: FAIL —— `Failed to resolve import "../NarrationStream"` / `../api/rest` 无 `module` 方法

- [ ] **Step 4: 前端实现**

`frontend/src/types.ts` 追加：
```ts
export type ModuleDetail = {
  id: string; title: string;
  npcs: { id: string; name: string }[];
  endings: { id: string; condition: string }[];
};
```

`frontend/src/api/rest.ts` 的 `api` 追加：
```ts
  module: (id: string) => jsonFetch<ModuleDetail>(`/api/campaigns/${id}/module`),
```
（import 行同步加入 `ModuleDetail`。）

`frontend/src/components/NarrationStream.tsx`：
```tsx
import type { Segment } from "../types";

export default function NarrationStream({ segments, live, npcNames }: {
  segments: Segment[];
  live: Segment[];
  npcNames?: Record<string, string>;
}) {
  function render(seg: Segment, key: string, cursor = false) {
    const isNpc = seg.speaker.startsWith("npc:");
    const id = isNpc ? seg.speaker.slice(4) : "";
    return (
      <p key={key} className={`${isNpc ? "seg-npc" : "seg-gm"}${cursor ? " cursor" : ""}`}>
        {isNpc && <span className="npc-name">【{npcNames?.[id] ?? id}】</span>}
        {seg.text}
      </p>
    );
  }
  return (
    <div className="room-story">
      {segments.map((s, i) => render(s, `s-${i}`))}
      {live.map((s, i) => render(s, `l-${i}`, i === live.length - 1))}
    </div>
  );
}
```

`frontend/src/components/InputBar.tsx`：
```tsx
import { useState } from "react";

import type { Phase } from "../stores/game";

export default function InputBar({ phase, connected, onSubmit }: {
  phase: Phase;
  connected: boolean;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const disabled = !connected || phase !== "collecting";
  const hint = !connected ? "连接中…"
    : phase === "collecting" ? "输入你的行动（回车提交）"
    : phase === "paused" ? "预算已熔断，暂停中"
    : phase === "ended" ? "故事已结束"
    : "GM 正在处理本回合…";

  function send() {
    const t = text.trim();
    if (!t || disabled) return;
    onSubmit(t);
    setText("");
  }

  return (
    <>
      <input value={text} placeholder={hint} disabled={disabled}
             onChange={(e) => setText(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
      <button onClick={send} disabled={disabled}>提交</button>
    </>
  );
}
```

`frontend/src/views/Room.tsx` 替换为：
```tsx
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/rest";
import { WsClient } from "../api/ws";
import InputBar from "../components/InputBar";
import NarrationStream from "../components/NarrationStream";
import type { Session } from "../session";
import { useGame } from "../stores/game";
import type { ModuleDetail } from "../types";

export default function Room({ session, onLeave }: {
  session: Session;
  onLeave: () => void;
}) {
  const state = useGame();
  const [moduleInfo, setModuleInfo] = useState<ModuleDetail | null>(null);
  const clientRef = useRef<WsClient | null>(null);

  useEffect(() => {
    useGame.getState().reset();
    const client = new WsClient(session.campaignId, session.playerId, {
      onEvent: (evt) => useGame.getState().apply(evt),
      onStatus: (s) => useGame.getState().setConnected(s === "open"),
    });
    clientRef.current = client;
    client.connect();
    api.module(session.campaignId).then(setModuleInfo).catch(() => {});
    return () => client.close();
  }, [session.campaignId, session.playerId]);

  const npcNames = useMemo(() => {
    const map: Record<string, string> = {};
    moduleInfo?.npcs.forEach((n) => { map[n.id] = n.name; });
    return map;
  }, [moduleInfo]);

  return (
    <div className="room">
      <header className="room-header">
        <button onClick={onLeave}>← 回到大厅</button>
        <h2>{session.title}</h2>
        <span className={`conn-badge ${state.connected ? "open" : ""}`}>
          {state.connected ? "已连接" : "连接中…"}
        </span>
        <span className="turn-badge">
          回合 {state.turnId} · ${state.costUsd.toFixed(3)}
        </span>
      </header>
      {state.errorMessage && (
        <div className="error-banner">{state.errorMessage}</div>
      )}
      {state.notice && <div className="notice-banner">{state.notice}</div>}
      <main className="room-main">
        <NarrationStream segments={state.segments} live={state.live}
                         npcNames={npcNames} />
      </main>
      <footer className="room-footer">
        <InputBar phase={state.phase} connected={state.connected}
                  onSubmit={(text) => clientRef.current?.sendInput(text)} />
      </footer>
    </div>
  );
}
```

`frontend/src/styles.css` 追加：
```css
.notice-banner { background: #21303d; border: 1px solid #3b5a72;
  padding: 6px 12px; border-radius: 6px; margin: 8px 16px 0; }
```

- [ ] **Step 5: 验证通过（前后端）**

Run: `cd backend; uv run pytest tests/api/test_campaigns_api.py -q`
Run: `cd frontend; npm run test; npm run build`
Expected: PASS（前端 13 passed）；build 成功

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/api/test_campaigns_api.py frontend/src
git commit -m "feat(frontend): room with live narration stream, input bar and module npc names"
```

---

### Task M3-16: 骰子动画与侧栏面板（角色/NPC/线索/记录/结局）

**Files:**
- Create: `frontend/src/components/DiceOverlay.tsx`、`CharacterPanel.tsx`、`NpcPanel.tsx`、`CluePanel.tsx`、`DiceLogPanel.tsx`、`EndingOverlay.tsx`
- Modify: `frontend/src/views/Room.tsx`（接入侧栏与覆盖层）、`frontend/src/styles.css`（骰子/面板/结局样式）
- Test: `frontend/src/components/__tests__/DiceOverlay.test.tsx`、`frontend/src/components/__tests__/EndingOverlay.test.tsx`

**Interfaces:**
- Consumes: `GameState`（M3-13）：`diceQueue/diceLog/clues/characters/scene/endingReached`；store actions `dicePlayed()`
- Produces：
  - `DiceOverlay({ dice, onDone })`：`dice === null` 不渲染；数字 scramble 动画 ~1.2s 后定格 `roll`，再 0.6s 调 `onDone`（Room 中接 `dicePlayed()` 出队，逐个播放）；成功绿色/失败红色；等级中文标签（critical→大成功…fumble→大失败）
  - `CharacterPanel({ characters })`：角色卡（name/hp、attributes 与 skills chips）
  - `NpcPanel({ sceneNpcs, npcNames })`：在场 NPC 列表（来自 scene 事件）
  - `CluePanel({ clues })`：已获线索列表（空态提示）
  - `DiceLogPanel({ diceLog })`：最近 5 条检定记录（倒序）
  - `EndingOverlay({ endingReached, condition, onLeave })`：结局达成覆盖层（条件文案 + 回大厅）
  - `Room` 侧栏 `aside.room-side` 挂四个面板；主区底部挂 `DiceOverlay` 与 `EndingOverlay`

- [ ] **Step 1: 写失败测试**

`frontend/src/components/__tests__/DiceOverlay.test.tsx`：
```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DiceOverlay from "../DiceOverlay";

const DICE = { actor: "pc_p1", skill: "侦查", skill_value: 50,
               difficulty: "regular", roll: 12, level: "hard",
               seed: 1, success: true };

afterEach(() => vi.useRealTimers());

describe("DiceOverlay", () => {
  it("does not render without a dice", () => {
    const { container } = render(<DiceOverlay dice={null} onDone={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("scrambles then settles on the final roll and calls onDone", () => {
    vi.useFakeTimers();
    const onDone = vi.fn();
    render(<DiceOverlay dice={DICE} onDone={onDone} />);
    expect(screen.getByText(/侦查（50）/)).toBeInTheDocument();
    vi.advanceTimersByTime(2000);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("困难成功")).toBeInTheDocument();
    vi.advanceTimersByTime(700);
    expect(onDone).toHaveBeenCalled();
  });
});
```

`frontend/src/components/__tests__/EndingOverlay.test.tsx`：
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import EndingOverlay from "../EndingOverlay";

describe("EndingOverlay", () => {
  it("renders nothing without ending", () => {
    const { container } = render(
      <EndingOverlay endingReached={null} condition={undefined}
                     onLeave={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the ending condition and leave button", async () => {
    const onLeave = vi.fn();
    render(<EndingOverlay endingReached="ending_break" condition="你找到了真相"
                          onLeave={onLeave} />);
    expect(screen.getByText("你找到了真相")).toBeInTheDocument();
    await userEvent.click(screen.getByText("回到大厅"));
    expect(onLeave).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 验证失败**

Run: `cd frontend; npm run test`
Expected: FAIL —— `Failed to resolve import "../DiceOverlay"`

- [ ] **Step 3: 实现组件**

`frontend/src/components/DiceOverlay.tsx`：
```tsx
import { useEffect, useState } from "react";

import type { DicePayload } from "../types";

const LEVEL_LABEL: Record<string, string> = {
  critical: "大成功", extreme: "极难成功", hard: "困难成功",
  regular: "成功", fail: "失败", fumble: "大失败",
};

export default function DiceOverlay({ dice, onDone }: {
  dice: DicePayload | null;
  onDone: () => void;
}) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!dice) return;
    setDisplay(0);
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started >= 1200) {
        setDisplay(dice.roll);
        clearInterval(timer);
        setTimeout(onDone, 600);
      } else {
        setDisplay(1 + Math.floor(Math.random() * 100));
      }
    }, 60);
    return () => clearInterval(timer);
  }, [dice, onDone]);

  if (!dice) return null;
  return (
    <div className="dice-overlay">
      <div className="dice-card">
        <div className="dice-who">
          {dice.actor} · {dice.skill}（{dice.skill_value}）
        </div>
        <div className={`dice-roll ${dice.success ? "ok" : "bad"}`}>{display}</div>
        <div className="dice-level">{LEVEL_LABEL[dice.level] ?? dice.level}</div>
      </div>
    </div>
  );
}
```

`frontend/src/components/CharacterPanel.tsx`：
```tsx
type CharacterDto = {
  id: string; name: string; player_id: string;
  attributes: Record<string, number>; skills: Record<string, number>;
  hp: number; max_hp: number;
};

export default function CharacterPanel({ characters }: {
  characters: CharacterDto[];
}) {
  return (
    <section className="panel">
      <h3>角色</h3>
      {characters.length === 0 && <p className="muted">加载中…</p>}
      {characters.map((c) => (
        <div key={c.id} className="char-card">
          <div className="char-name">
            {c.name}<span className="hp">{c.hp}/{c.max_hp}</span>
          </div>
          <div>
            {Object.entries(c.attributes).map(([k, v]) => (
              <span key={k} className="chip">{k} {v}</span>
            ))}
          </div>
          <div>
            {Object.entries(c.skills).map(([k, v]) => (
              <span key={k} className="chip">{k} {v}</span>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
```

`frontend/src/components/NpcPanel.tsx`：
```tsx
export default function NpcPanel({ sceneNpcs, npcNames }: {
  sceneNpcs: string[];
  npcNames: Record<string, string>;
}) {
  if (sceneNpcs.length === 0) return null;
  return (
    <section className="panel">
      <h3>在场 NPC</h3>
      <ul>
        {sceneNpcs.map((id) => <li key={id}>{npcNames[id] ?? id}</li>)}
      </ul>
    </section>
  );
}
```

`frontend/src/components/CluePanel.tsx`：
```tsx
import type { CluePayload } from "../types";

export default function CluePanel({ clues }: { clues: CluePayload[] }) {
  return (
    <section className="panel">
      <h3>线索（{clues.length}）</h3>
      {clues.length === 0
        ? <p className="muted">尚未发现线索</p>
        : (
          <ul>
            {clues.map((c) => (
              <li key={c.clue_id}>{c.text || c.clue_id}</li>
            ))}
          </ul>
        )}
    </section>
  );
}
```

`frontend/src/components/DiceLogPanel.tsx`：
```tsx
import type { DicePayload } from "../types";

export default function DiceLogPanel({ diceLog }: { diceLog: DicePayload[] }) {
  const rows = [...diceLog].reverse().slice(0, 5);
  return (
    <section className="panel">
      <h3>检定记录</h3>
      {rows.length === 0
        ? <p className="muted">尚无检定</p>
        : (
          <ul>
            {rows.map((d, i) => (
              <li key={i} className={d.success ? "ok" : "bad"}>
                {d.skill} d100={d.roll} · {d.level}
              </li>
            ))}
          </ul>
        )}
    </section>
  );
}
```

`frontend/src/components/EndingOverlay.tsx`：
```tsx
export default function EndingOverlay({ endingReached, condition, onLeave }: {
  endingReached: string | null;
  condition: string | undefined;
  onLeave: () => void;
}) {
  if (!endingReached) return null;
  return (
    <div className="ending-overlay">
      <div className="ending-card">
        <h2>故事已抵达结局</h2>
        <p>{condition ?? endingReached}</p>
        <button onClick={onLeave}>回到大厅</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Room.tsx 接入（替换对应片段）**

`frontend/src/views/Room.tsx`：
1. import 区追加：
```tsx
import { useCallback } from "react";

import CharacterPanel from "../components/CharacterPanel";
import CluePanel from "../components/CluePanel";
import DiceLogPanel from "../components/DiceLogPanel";
import DiceOverlay from "../components/DiceOverlay";
import EndingOverlay from "../components/EndingOverlay";
import NpcPanel from "../components/NpcPanel";
```
（`useCallback` 合入现有的 react import 行。）

2. 组件体内（`npcNames` 之后）追加：
```tsx
  const handleDicePlayed = useCallback(() => {
    useGame.getState().dicePlayed();
  }, []);
  const endingCondition = useMemo(
    () => moduleInfo?.endings.find((e) => e.id === state.endingReached)?.condition,
    [moduleInfo, state.endingReached],
  );
```

3. `<main className="room-main">` 块替换为：
```tsx
      <main className="room-main">
        <NarrationStream segments={state.segments} live={state.live}
                         npcNames={npcNames} />
        <aside className="room-side">
          <CharacterPanel characters={state.characters as never[]} />
          <NpcPanel sceneNpcs={state.scene?.npcs ?? []} npcNames={npcNames} />
          <CluePanel clues={state.clues} />
          <DiceLogPanel diceLog={state.diceLog} />
        </aside>
      </main>
```

4. `</div>`（最外层 room 关闭前）追加覆盖层：
```tsx
      <DiceOverlay dice={state.diceQueue[0] ?? null} onDone={handleDicePlayed} />
      <EndingOverlay endingReached={state.endingReached} condition={endingCondition}
                     onLeave={onLeave} />
```

- [ ] **Step 5: styles.css 追加**

```css
.room-side .panel { margin-bottom: 18px; }
.panel h3 { margin: 6px 0 8px; font-size: 14px; color: #9aa7b8; }
.panel ul { margin: 0; padding-left: 18px; }
.chip { display: inline-block; margin: 2px 4px 2px 0; padding: 1px 8px;
  border-radius: 10px; background: #232a35; font-size: 12px; }
.char-card { padding: 8px 0; border-bottom: 1px solid #262c36; }
.char-name { font-weight: 600; }
.char-name .hp { color: #8fd18f; font-weight: 400; margin-left: 8px; }
.muted { color: #6b7686; font-size: 13px; }
.panel li.ok { color: #8fd18f; }
.panel li.bad { color: #e08f8f; }
.dice-overlay { position: fixed; inset: 0; display: flex; align-items: center;
  justify-content: center; background: rgba(10, 12, 16, 0.55); z-index: 50; }
.dice-card { background: #1d222b; border: 1px solid #3d4757; border-radius: 12px;
  padding: 20px 36px; text-align: center; min-width: 220px; }
.dice-who { color: #9aa7b8; font-size: 13px; margin-bottom: 8px; }
.dice-roll { font-size: 44px; font-weight: 700; font-variant-numeric: tabular-nums; }
.dice-roll.ok { color: #8fd18f; }
.dice-roll.bad { color: #e08f8f; }
.dice-level { margin-top: 6px; }
.ending-overlay { position: fixed; inset: 0; display: flex; align-items: center;
  justify-content: center; background: rgba(8, 10, 14, 0.85); z-index: 60; }
.ending-card { max-width: 460px; background: #1d222b; border: 1px solid #4a5568;
  border-radius: 12px; padding: 28px 32px; text-align: center; }
.turn-badge { margin-left: auto; color: #9aa7b8; font-size: 13px; }
```

- [ ] **Step 6: 验证通过**

Run: `cd frontend; npm run test; npm run build`
Expected: PASS（17 passed）；build 成功

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): dice scramble animation, side panels and ending overlay"
```

---
### Task M3-17: 端到端验收（serve 入口 + 全流程 E2E + README）

**Files:**
- Create: `backend/app/serve.py`
- Create: `backend/tests/api/test_serve_app.py`
- Create: `backend/tests/api/test_ws_ending_e2e.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `create_app`/`AppDeps`（M3-11）、`load_settings`/`make_engine`/`init_db`（M2）、`make_default_character`（M2）、`FakeLLM`（M2）、misty_hollow 模组（M2 Task 23 已创建于 `modules/misty_hollow.yaml`）
- Produces：
  - `backend/app/serve.py`：`build_app() -> FastAPI`（load_settings → make_engine → init_db → SqliteRepository → create_app）；模块级 `app = build_app()`（`uvicorn app.serve:app` 即可启动）
  - E2E 验收测试：真实 WS 协议走通 misty_hollow 三回合（开场 → 检定+线索 → 结局），验证断线重连的**全量回放**与继续游玩，以及场景移动回合的 `scene` 事件推送（`apply_transition` → `scene_changed` → WS）
  - `README.md`：环境准备、后端/前端启动步骤、浏览器手测验收清单、测试命令

- [ ] **Step 1: 写 serve 入口测试**

`backend/tests/api/test_serve_app.py`：
```python
"""serve.py 生产入口冒烟：工厂可构建、健康检查与模组注册表可用。"""
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]


def test_serve_app_is_built_from_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ENSEMBLE_SQLITE_PATH", str(tmp_path / "serve.db"))
    monkeypatch.setenv("ENSEMBLE_MODULES_DIR", str(ROOT / "modules"))
    monkeypatch.setenv("ENSEMBLE_PRICING_PATH", str(ROOT / "config" / "pricing.yaml"))

    from app.serve import app, build_app     # 模块级实例（uvicorn app.serve:app 的入口）

    assert build_app().title == "Ensemble"
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        ids = [m["id"] for m in client.get("/api/modules").json()]
        assert "misty_hollow" in ids
```

- [ ] **Step 2: 验证失败**

Run: `cd backend; uv run pytest tests/api/test_serve_app.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.serve'`

- [ ] **Step 3: 实现 serve.py**

`backend/app/serve.py`：
```python
"""生产入口：`uvicorn app.serve:app --port 8000`（在 backend/ 目录运行）。

本地默认库为 backend/ensemble.db；可用环境变量覆盖：
ENSEMBLE_SQLITE_PATH / ENSEMBLE_MODULES_DIR / ENSEMBLE_PRICING_PATH /
DASHSCOPE_API_KEY / DEEPSEEK_API_KEY（详见 README）。
"""
from fastapi import FastAPI

from app.api.app import AppDeps, create_app
from app.config import load_settings
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository


def build_app() -> FastAPI:
    settings = load_settings()
    engine = make_engine(settings.sqlite_path)
    init_db(engine)
    repo = SqliteRepository(engine)
    return create_app(AppDeps(settings=settings, repo=repo))


app = build_app()
```

- [ ] **Step 4: 验证通过**

Run: `cd backend; uv run pytest tests/api/test_serve_app.py -q`
Expected: PASS

- [ ] **Step 5: 写端到端验收测试**

`backend/tests/api/test_ws_ending_e2e.py`：
```python
"""端到端验收：misty_hollow 三回合全流程（开场 → 检定/线索 → 结局）+ 重连回放。

用真实 WS 协议 + FakeLLM 脚本，验证 M3 各组件在装配后的集成行为；
若本文件失败，优先怀疑是集成缝隙而非单元缺陷——这正是本任务的价值。
"""
import json
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
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


def make_script(char_id: str) -> list[str]:
    """六条 qwen3.8-flash 脚本：回合0 decide/narrate → 回合1 decide（检定+线索）/narrate
    → 回合2 decide（结局）/narrate。检定 actor 用动态角色 id。"""
    open_decide = json.dumps({"intent_summary": "开场", "checks": [],
                              "proactive_npc_triggers": [], "scene_transition": None,
                              "memory_queries": []})
    turn1_decide = json.dumps({"intent_summary": "查看公告栏",
                               "checks": [{"actor": char_id, "skill": "侦查",
                                           "difficulty": "regular"}],
                               "proactive_npc_triggers": [], "scene_transition": None,
                               "memory_queries": [],
                               "clues_revealed": ["clue_missing"]})
    ending_decide = json.dumps({"intent_summary": "终结旧约", "checks": [],
                                "proactive_npc_triggers": [], "scene_transition": None,
                                "memory_queries": [], "ending_reached": "ending_break"})
    return [open_decide, "暮色把雾霭镇压得很低，无面的神像俯视着广场。",
            turn1_decide, "公告栏上贴着泛黄的寻人启事：学徒小满，三个月前失踪。",
            ending_decide, "石台在轰鸣中崩塌，缠绕镇子的低语骤然停止。"]


def build_env(tmp_path, script=None):
    engine = make_engine(str(tmp_path / "e2e.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "e2e.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=10.0)
    campaign = repo.create_campaign("misty_hollow", "端到端")
    player = repo.add_player(campaign.id, "张三")
    char = make_default_character(player.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    deps = AppDeps(settings=settings, repo=repo,
                   model_factory=script_factory(script if script is not None
                                                else make_script(char.id)))
    return create_app(deps), repo, campaign, player, char


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
    def check(evts):
        return any(e["type"] == "turn" and e["payload"].get("phase") == "collecting"
                   and e["payload"].get("turn_id") == turn_id for e in evts)
    return check


def test_full_campaign_playthrough_to_ending(tmp_path):
    app, repo, campaign, player, char = build_env(tmp_path)
    events: list[dict] = []
    with TestClient(app) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            pump_until(ws, events, _collecting(1))          # 回合 0：开场驱动后开窗
            assert any(e["type"] == "token" for e in events)
            assert any(e["type"] == "scene" and e["payload"]["scene_id"] == "square"
                       for e in events)
            assert any(e["type"] == "state" for e in events)

            ws.send_text(json.dumps({"type": "input", "text": "我凑近公告栏查看启事"}))
            pump_until(ws, events, _collecting(2))          # 回合 1：检定与线索推送
            assert any(e["type"] == "dice" and e["payload"]["actor"] == char.id
                       for e in events)
            assert any(e["type"] == "clue"
                       and e["payload"]["clue_id"] == "clue_missing" for e in events)

            ws.send_text(json.dumps({"type": "input", "text": "我推倒石台，终结旧约"}))
            pump_until(ws, events, lambda evts: any(     # 回合 2：结局收束，图终止
                e["type"] == "turn" and e["payload"].get("phase") == "ended"
                for e in evts))
            ended = [e for e in events if e["type"] == "turn"
                     and e["payload"].get("phase") == "ended"]
            assert ended[-1]["payload"]["ending_reached"] == "ending_break"

        detail = client.get(f"/api/campaigns/{campaign.id}").json()   # REST 回查落库
        assert [c["clue_id"] for c in detail["clues_revealed"]] == ["clue_missing"]
        assert detail["scene_id"] == "square"


def test_reconnect_replays_full_history_and_can_continue(tmp_path):
    app, repo, campaign, player, char = build_env(tmp_path)
    url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
    with TestClient(app) as client:
        with client.websocket_connect(url) as ws:           # 首次连接：走完回合 0/1
            events: list[dict] = []
            pump_until(ws, events, _collecting(1))
            ws.send_text(json.dumps({"type": "input", "text": "我凑近公告栏查看启事"}))
            pump_until(ws, events, _collecting(2))

        replayed: list[dict] = []                           # F5 刷新：resume_from=0 全量回放
        with client.websocket_connect(url + "&resume_from=0") as ws2:
            pump_until(ws2, replayed, lambda evts: any(
                e["type"] == "clue" and e["payload"]["clue_id"] == "clue_missing"
                for e in evts))
            assert replayed[0]["seq"] == 1 and replayed[0]["type"] == "turn"
            types = {e["type"] for e in replayed}
            assert {"token", "dice", "clue", "state", "turn"} <= types

            ws2.send_text(json.dumps({"type": "input", "text": "我推倒石台"}))   # 重连后继续玩
            pump_until(ws2, replayed, lambda evts: any(
                e["type"] == "turn" and e["payload"].get("phase") == "ended"
                for e in evts))
            ended = [e for e in replayed if e["type"] == "turn"
                     and e["payload"].get("phase") == "ended"]
            assert ended[-1]["payload"]["ending_reached"] == "ending_break"


MOVE_SCRIPT = [
    json.dumps({"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],
                "scene_transition": None, "memory_queries": []}),
    "暮色把雾霭镇压得很低，无面的神像俯视着广场。",
    json.dumps({"intent_summary": "前往白鹭旅店", "checks": [],
                "proactive_npc_triggers": [],
                "scene_transition": {"to_scene": "inn", "reason": "推门而入"},
                "memory_queries": []}),
    "你推门走进白鹭旅店，壁炉的暖意扑面而来。",
]


def test_scene_move_pushes_scene_event(tmp_path):
    """移动回合：apply_transition → post_turn 落 scene_changed → WS 推 scene（含 reason）。"""
    app, repo, campaign, player, char = build_env(tmp_path, script=MOVE_SCRIPT)
    events: list[dict] = []
    with TestClient(app) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            pump_until(ws, events, _collecting(1))             # 回合 0：开场（广场首推）
            assert any(e["type"] == "scene" and e["payload"]["scene_id"] == "square"
                       for e in events)
            ws.send_text(json.dumps({"type": "input", "text": "我推门走进白鹭旅店"}))
            pump_until(ws, events, lambda evts: any(     # 回合 1：场景切换推送新场景
                e["type"] == "scene" and e["payload"].get("scene_id") == "inn"
                for e in evts))
            moved = [e for e in events if e["type"] == "scene"
                     and e["payload"].get("scene_id") == "inn"]
            assert moved[-1]["payload"]["reason"] == "推门而入"
        detail = client.get(f"/api/campaigns/{campaign.id}").json()   # REST 回查落库
        assert detail["scene_id"] == "inn"
```

- [ ] **Step 6: 运行 E2E（与后端全量回归）**

Run: `cd backend; uv run pytest tests/api/test_ws_ending_e2e.py -q`
Expected: PASS —— 预期通过（T1-16 已分别验证）；**若失败，即捕获到集成缺陷，当场修复后重跑，不允许绕过**

Run: `cd backend; uv run pytest -q`
Expected: PASS —— 后端全量测试全绿

- [ ] **Step 7: 写 README.md**

`README.md`（仓库根）：
````markdown
# Ensemble —— AI 跑团（TRPG）引擎

LLM 担任 GM 主持人，子 agent 扮演 NPC，LangGraph 编排全场流程。
支持流式叙事（打字机效果）、d100 检定与骰子动画、线索与结局机制、
SQLite 断点续玩与时间线分叉、Web 实时游玩。

## 目录结构

```
├── modules/                  # 模组（YAML）：misty_hollow 示例冒险
├── config/pricing.yaml       # 模型价格（成本估算用）
├── backend/                  # FastAPI + LangGraph + SQLite（uv 管理）
│   ├── app/
│   └── tests/
└── frontend/                 # React + Vite + zustand（npm 管理）
```

## 环境准备

- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- API keys：
  - `DASHSCOPE_API_KEY`（阿里云百炼，用于 GM：qwen3.8-flash）
  - `DEEPSEEK_API_KEY`（用于 NPC：deepseek-flash）

## 启动后端（端口 8000）

```bash
cd backend
uv sync
# PowerShell:
$env:DASHSCOPE_API_KEY = "sk-..."
$env:DEEPSEEK_API_KEY = "sk-..."
uv run uvicorn app.serve:app --host 127.0.0.1 --port 8000
```

## 启动前端（端口 5173）

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。前端已配置 `/api` 与 `/ws` 代理到 8000 端口。

## 浏览器验收清单（手测）

- [ ] 大厅：模组下拉列出「雾霭镇的低语」；输入桌名，新建战役后进入房间
- [ ] 开场叙事以打字机效果流式出现；镜头徽标显示「第 1 回合 · 等待行动」
- [ ] 输入行动并提交：徽标变为「裁定中…」→ 叙事流式返回 → 新回合窗口打开
- [ ] 检定回合出现骰子翻牌动画；骰子记录面板新增该检定
- [ ] 线索回合：右侧线索面板出现「寻人启事…」条目
- [ ] 结束后（GM 判定触发结局时）出现全屏结局覆盖层；点「回到大厅」可再开一局
- [ ] F5 刷新页面：叙事历史完整回放（WS `resume_from=0` 全量重放）
- [ ] 大厅存档列表可见历史战役，点「继续」恢复同一局（挂起输入窗口仍在）

> 提示：结局由 GM 判定触发，试试围绕线索深入调查并做出决定性行动
> （如掌握地窖祭坛真相后表态要摧毁石台）。

## 测试

```bash
cd backend; uv run pytest -q          # 后端全量（含端到端验收）
cd frontend; npm run test             # 前端组件/状态层测试
```

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ENSEMBLE_SQLITE_PATH` | `backend/ensemble.db`（相对运行目录） | 数据库路径 |
| `ENSEMBLE_MODULES_DIR` | `../modules`（相对运行目录） | 模组目录 |
| `ENSEMBLE_PRICING_PATH` | `config/pricing.yaml`（相对运行目录） | 价格表 |
| `DASHSCOPE_API_KEY` / `DEEPSEEK_API_KEY` | 无 | 模型密钥 |
````

- [ ] **Step 8: Commit**

```bash
git add backend/app/serve.py backend/tests/api/test_serve_app.py backend/tests/api/test_ws_ending_e2e.py README.md
git commit -m "feat(serve): production entrypoint, full playthrough e2e and readme"
```

---

## 计划自审（M3）

**规格覆盖表**（对照 `docs/superpowers/specs/2026-09-24-ensemble-design.md`）：

| 规格章节 | 覆盖任务 |
| --- | --- |
| §3 系统架构（FastAPI 装配、会话驱动） | M3-5（AppDeps/create_app）、M3-10（SessionManager）、M3-11（装配扩展） |
| §4.1 流式叙事 | M3-1（chat_stream）、M3-2（IncrementalSegmenter）、M3-3（narrate 流式化） |
| §4.2 回合输入窗口 | M3-9（TurnBuffer）、M3-10（开窗/收口/防抖） |
| §4.3 挂起与恢复 | M3-10（interrupt/resume 收口、Command(update=branch)）、M3-7（fork 恢复） |
| §5.3 WS 协议与事件类型 | M3-8（EventBus / WsEvent / 九类事件）、M3-11（端点、重放、resync） |
| §6.3 断线重连 | M3-8（replay 缓冲与 gap）、M3-11（gap→state resync）、M3-17（E2E 回放验收） |
| §6.4 前端信息架构 | M3-14（Lobby）、M3-15（Room/叙事流/输入栏）、M3-16（面板与覆盖层） |
| §7 时间线与分叉恢复 | M3-6（timeline/switch）、M3-7（restore）、M3-10（on_branch_switch） |
| §8 降级与重试 | M3-3（narrate repair 流式 reset）、M3-4（validate 引用校验）、M3-10（error/budget_paused 相位） |
| §9 成本与预算 | M3-10（state.cost_usd 推送）、M3-16（HUD 展示） |
| §13-M3 验收标准 | M3-17（全流程 E2E + README 手测清单） |

**已知边界（有意为之，M4/M5 处理）**：
- `state` 事件每回合重推全部叙事分段（按落库分段对齐的权威拷贝），规模大了以后改为增量游标（M4 优化）。
- 分支切换后前端时间线不自动刷新（M3 时间线只读展示；M4 多人版补 UI）。
- `TurnInput.submitted_at` 为 UTC 字符串（展示层不解析时区）。
- 单人假设：M3 的 Lobby 继续游戏取 `players[0]`，邀请码与多角色在 M4。

**类型一致性抽查**：`TurnInputs`（turn_buffer.close 输出）→ `Command(resume=...)`（session）→ `wait_input` payload 解析（M2）；`WsEvent.seq` 从 1 自增与前端 `lastSeq+1` 对齐；`_dice_payload` 字段与 `DiceRow`、前端 `DicePayload` 三处一致；`state` payload 键与前端 `StatePayload` 一致。

---

## 执行交接（M3）

本计划 17 个任务按依赖序排列（1-4 后端引擎 → 5-7 REST → 8-11 WS 驱动 → 12-16 前端 → 17 E2E 验收），每个任务自包含、可独立测试与提交。

执行方式二选一：
1. **Subagent 逐任务执行（推荐）**：每个任务派发新的子代理实现，任务间人工审查把关；
2. **本会话内批量执行**：按 executing-plans 流水线推进，在检查点停顿复核。

交接前确认：仓库根已存在 `modules/misty_hollow.yaml`（M2 Task 23 产物）；后端 venv 已 `uv sync`（M3-5 会新增 fastapi/uvicorn/httpx/pytest-asyncio 依赖）。

---
