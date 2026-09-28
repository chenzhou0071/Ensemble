"""记忆服务契约：M2 用事件日志 + 滚动摘要；二阶段 Graphiti 适配器实现同一协议。"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MemoryEvent:
    type: str
    text: str
    turn_id: int
    visibility: str = "all"


@dataclass(frozen=True)
class MemoryHit:
    text: str
    turn_id: int


class MemoryService(Protocol):
    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None: ...
    def search(self, campaign_id: str, branch_id: str, query: str,
               limit: int = 5) -> list[MemoryHit]: ...
    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str: ...
    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None: ...
