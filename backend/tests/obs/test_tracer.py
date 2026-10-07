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
        "qwen3.8-flash": PricingEntry(input_per_1k=0.001, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.0005, output_per_1k=0.001),
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
    assert rows[0]["inputs"]["model"] == "qwen3.8-flash"
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

    def stream(self, inp, config, stream_mode=None):    # 同步流：_drive 在 executor 线程消费
        yield {"text": "……"}


class _FakeSession:
    def __init__(self, tracer):
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
