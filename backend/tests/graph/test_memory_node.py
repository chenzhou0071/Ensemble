from app.graph.nodes.memory import build_memory_query_node
from app.memory.base import MemoryEvent
from app.memory.journal import JournalMemory


class SpyMemory:
    """记录调用参数、委托真实实现。"""

    def __init__(self, inner):
        self.inner = inner
        self.context_budgets: list[int] = []
        self.search_queries: list[str] = []

    def get_context(self, campaign_id, branch_id, budget_chars=1200):
        self.context_budgets.append(budget_chars)
        return self.inner.get_context(campaign_id, branch_id, budget_chars)

    def search(self, campaign_id, branch_id, query, limit=5):
        self.search_queries.append(query)
        return self.inner.search(campaign_id, branch_id, query, limit)

    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.inner.update_summaries(campaign_id, branch_id, turn_id)


def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "decision": {"memory_queries": ["磨坊"]},
            "budget_level": "ok", **extra}


def test_ok_path_appends_search_hits(repo, campaign):
    journal = JournalMemory(repo)
    journal.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=1))
    spy = SpyMemory(journal)
    upd = build_memory_query_node(spy)(base_state(campaign))
    assert "【检索命中】" in upd["memory_context"]
    assert "磨坊夜里传出哭声" in upd["memory_context"]
    assert spy.context_budgets == [1200]
    assert spy.search_queries == ["磨坊"]


def test_tight_downgrades_to_summary_only(repo, campaign):
    journal = JournalMemory(repo)
    journal.write_event(campaign.id, campaign.active_branch_id,
                        MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=1))
    spy = SpyMemory(journal)
    upd = build_memory_query_node(spy)(base_state(campaign, budget_level="tight"))
    assert spy.context_budgets == [600]      # 阶梯①：budget_chars 降档
    assert spy.search_queries == []          # 不做检索
    assert "【检索命中】" not in upd["memory_context"]


def test_failure_degrades_to_empty_but_continues(repo, campaign):
    class BrokenMemory:
        def get_context(self, *a, **kw):
            raise RuntimeError("memory down")

        def search(self, *a, **kw):
            raise RuntimeError("memory down")

        def update_summaries(self, *a, **kw):
            pass

    upd = build_memory_query_node(BrokenMemory())(base_state(campaign))
    assert upd["memory_context"] == ""
    assert upd["degraded"] == {"memory_query": True}
