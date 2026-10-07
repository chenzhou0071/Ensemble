"""GraphitiMemory：图谱增强 + 优雅回退；全部用假 GraphClient，零网络。"""
import re

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
    assert ep["group_id"] == f"{campaign.id}_{campaign.id}_main"   # branch_id 的 @ 需净化为 _
    assert re.fullmatch(r"[A-Za-z0-9_-]+", ep["group_id"])   # graphiti 组名约束：字母数字/连字符/下划线
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
    assert graph.queries == [("磨坊", f"{campaign.id}_{campaign.id}_main", 2)]


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


def test_update_summaries_repeat_call_without_new_summary(repo, campaign):
    """无新摘要时重复调用不炸：曾误用不存在的 SummaryRow.turn_id 触发 AttributeError。"""
    graph = FakeGraphClient()
    mem = GraphitiMemory(repo, graph_client=graph)
    for i in range(12):
        mem.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="note", text=f"事件{i}", turn_id=i // 3))
    graph.episodes.clear()
    mem.update_summaries(campaign.id, campaign.active_branch_id, turn_id=3)
    assert len(graph.episodes) == 1              # 首次生成摘要并镜像
    mem.update_summaries(campaign.id, campaign.active_branch_id, turn_id=4)
    assert len(graph.episodes) == 1              # 无新摘要 → 跳过镜像（不抛 AttributeError）


def test_write_event_async_when_mirror_started(repo, campaign):
    """start 后镜像走后台线程：write_event 不阻塞主链，最终保序写入。"""
    import threading
    import time

    class SlowGraphClient(FakeGraphClient):
        def __init__(self):
            super().__init__()
            self.gate = threading.Event()

        def add_episode(self, name, body, group_id, reference_time):
            self.gate.wait(2)                    # 阻塞 worker，证明主线程没等它
            super().add_episode(name, body, group_id, reference_time)

    graph = SlowGraphClient()
    mem = GraphitiMemory(repo, graph_client=graph)
    mem.start()

    t0 = time.monotonic()
    for i in (1, 2):
        mem.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="clue", text=f"事件{i}", turn_id=i))
    assert time.monotonic() - t0 < 0.5       # 慢镜像未阻塞调用方

    graph.gate.set()
    mem.drain()
    assert [e["name"] for e in graph.episodes] == ["clue:t1", "clue:t2"]


def test_mirror_failure_logged_not_raised(repo, campaign, caplog):
    mem = GraphitiMemory(repo, graph_client=FakeGraphClient(fail=True))
    mem.start()
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="clue", text="图挂了也不抛", turn_id=1))
    mem.drain()
    assert any("mirror failed" in r.getMessage() for r in caplog.records)


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


def _install_fake_graphiti(monkeypatch):
    """注入假 graphiti_core 模块树：零安装验证 DashScope 兼容接线。"""
    import asyncio
    import sys
    import types
    from abc import ABC, abstractmethod

    calls: dict = {}

    class FakeCrossEncoderClient(ABC):
        """模拟 graphiti 的 CrossEncoderClient：GraphitiClients 构造时的实例校验。"""

        @abstractmethod
        async def rank(self, query: str, passages: list[str]): ...

    class FakeGraphiti:
        def __init__(self, uri, user, password, **kwargs):
            assert isinstance(kwargs.get("cross_encoder"), FakeCrossEncoderClient), \
                "cross_encoder 必须是 CrossEncoderClient 实例（pydantic 校验）"
            try:
                # 记录构造时是否处于事件循环内（真 graphiti 会把建索引任务调度到该 loop）
                self.created_loop = asyncio.get_running_loop()
            except RuntimeError:
                self.created_loop = None
            calls["graphiti"] = {"uri": uri, "user": user, "password": password, **kwargs}

        async def build_indices_and_constraints(self):
            calls["indices"] = True

        async def close(self):
            calls["closed"] = True

    class FakeLLMConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeGenericClient:
        def __init__(self, config, structured_output_mode="json_schema"):
            calls["llm"] = {"config": config.kwargs, "mode": structured_output_mode}

    class FakeEmbedderConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeEmbedder:
        def __init__(self, config):
            calls["embedder"] = config.kwargs

    def mod(name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        return module

    for name, module in {
        "graphiti_core": mod("graphiti_core", Graphiti=FakeGraphiti),
        "graphiti_core.llm_client": mod("graphiti_core.llm_client"),
        "graphiti_core.llm_client.config":
            mod("graphiti_core.llm_client.config", LLMConfig=FakeLLMConfig),
        "graphiti_core.llm_client.openai_generic_client":
            mod("graphiti_core.llm_client.openai_generic_client",
                OpenAIGenericClient=FakeGenericClient),
        "graphiti_core.embedder": mod("graphiti_core.embedder"),
        "graphiti_core.embedder.openai":
            mod("graphiti_core.embedder.openai", OpenAIEmbedder=FakeEmbedder,
                OpenAIEmbedderConfig=FakeEmbedderConfig),
        "graphiti_core.cross_encoder": mod("graphiti_core.cross_encoder"),
        "graphiti_core.cross_encoder.client":
            mod("graphiti_core.cross_encoder.client", CrossEncoderClient=FakeCrossEncoderClient),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def test_make_graphiti_client_wires_dashscope_compatible_clients(monkeypatch):
    from app.memory.graphiti import NoopCrossEncoder, make_graphiti_client

    calls = _install_fake_graphiti(monkeypatch)
    settings = Settings(neo4j_password="pw-12345678", qwen_api_key="sk-dashscope",
                        neo4j_uri="bolt://neo4j:7687")
    client = make_graphiti_client(settings)

    assert (calls["graphiti"]["uri"], calls["graphiti"]["user"],
            calls["graphiti"]["password"]) == ("bolt://neo4j:7687", "neo4j", "pw-12345678")
    assert calls["llm"]["mode"] == "json_schema"          # DashScope 支持约束解码（$defs/$ref 实测通过）
    assert calls["llm"]["config"] == {
        "api_key": "sk-dashscope", "base_url": settings.qwen_base_url,
        "model": settings.gm_model, "small_model": settings.cheap_model}
    assert calls["embedder"] == {
        "api_key": "sk-dashscope", "base_url": settings.qwen_base_url,
        "embedding_model": "text-embedding-v4"}
    assert isinstance(calls["graphiti"]["cross_encoder"], NoopCrossEncoder)
    assert calls["indices"] is True                       # 首次连库幂等初始化索引

    client.close()
    assert calls["closed"] is True


def test_graphiti_constructed_inside_bridge_loop(monkeypatch):
    """Graphiti 必须在专用桥接循环内构造：其驱动会把建索引任务调度到构造时的 running loop，
    若在外部循环（如 uvicorn 主循环）构造，driver 会被两个事件循环混用。"""
    from app.memory.graphiti import make_graphiti_client

    _install_fake_graphiti(monkeypatch)
    settings = Settings(neo4j_password="pw-12345678", qwen_api_key="sk-dashscope",
                        neo4j_uri="bolt://neo4j:7687")
    client = make_graphiti_client(settings)
    assert client._graphiti.created_loop is client._loop
    client.close()


def test_make_graphiti_client_requires_neo4j_password():
    from app.memory.graphiti import make_graphiti_client

    with pytest.raises(RuntimeError, match="NEO4J_PASSWORD"):
        make_graphiti_client(Settings(neo4j_password=None))
