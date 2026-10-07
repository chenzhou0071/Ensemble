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
        "qwen3.8-flash": PricingEntry(input_per_1k=0.001, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.0005, output_per_1k=0.001),
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
    reset_counters()                       # 自包含：不依赖前置文件的全局计数残留
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

    def stream(self, inp, config, stream_mode=None):    # 同步流：_drive 在 executor 线程消费
        yield {"text": "……"}


class _FakeSession:
    def __init__(self):
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
