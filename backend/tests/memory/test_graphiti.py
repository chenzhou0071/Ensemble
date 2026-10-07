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
