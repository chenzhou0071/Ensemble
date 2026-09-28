"""摘要异步化适配器：update_summaries 变为 watermark 追赶任务；其余方法透传。"""
from typing import TYPE_CHECKING

from app.memory.base import MemoryEvent
from app.tasks import BackgroundQueue

if TYPE_CHECKING:
    from app.memory.journal import JournalMemory


class BackgroundSummaries:
    def __init__(self, inner: "JournalMemory", queue: BackgroundQueue):
        self._inner = inner
        self._queue = queue

    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None:
        self._queue.submit(f"{campaign_id}@{branch_id}", (campaign_id, branch_id, turn_id))

    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None:
        return self._inner.write_event(campaign_id, branch_id, event)

    def search(self, campaign_id: str, branch_id: str, query: str, limit: int = 5):
        return self._inner.search(campaign_id, branch_id, query, limit=limit)

    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str:
        return self._inner.get_context(campaign_id, branch_id, budget_chars=budget_chars)
