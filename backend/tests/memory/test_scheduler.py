from app.memory.scheduler import BackgroundSummaries
from app.tasks import BackgroundQueue


class FakeMemory:
    def __init__(self):
        self.updates = []

    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.updates.append((campaign_id, branch_id, turn_id))

    def write_event(self, campaign_id, branch_id, event):
        return ("write", campaign_id)

    def search(self, campaign_id, branch_id, query, limit=5):
        return [("search", query, limit)]

    def get_context(self, campaign_id, branch_id, budget_chars=1200):
        return f"ctx:{budget_chars}"


def test_update_summaries_deferred_and_coalesced():
    inner = FakeMemory()
    q = BackgroundQueue(lambda key, payload: inner.update_summaries(*payload))
    bg = BackgroundSummaries(inner, q)
    bg.update_summaries("c", "c@main", 3)
    bg.update_summaries("c", "c@main", 5)
    assert inner.updates == []                     # 主线程零执行
    q.run_pending()
    assert inner.updates == [("c", "c@main", 5)]   # 合并为最大 watermark


def test_other_methods_delegate_to_inner():
    inner = FakeMemory()
    bg = BackgroundSummaries(inner, BackgroundQueue(lambda k, p: None))
    assert bg.get_context("c", "b") == "ctx:1200"
    assert bg.search("c", "b", "磨坊") == [("search", "磨坊", 5)]
    assert bg.write_event("c", "b", object()) == ("write", "c")
