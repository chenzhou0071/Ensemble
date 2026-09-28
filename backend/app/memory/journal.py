"""JournalMemory：事件日志 + 滚动摘要 + 简单检索（MVP 记忆实现）。"""
import json
import re
from typing import Callable

from app.llm.client import ChatMessage
from app.memory.base import MemoryEvent, MemoryHit

SUMMARY_TRIGGER_EVENTS = 12
_SUMMARY_PROMPT = (
    "你是跑团记录员。把给定事件压缩成不超过 300 字的前情摘要，"
    "保留关键人物、地点、线索与未解决的悬念。只输出摘要正文。"
)


class JournalMemory:
    def __init__(self, repo, summarizer: Callable[[list[ChatMessage]], str] | None = None):
        self._repo = repo
        self._summarizer = summarizer

    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None:
        self._repo.add_event(campaign_id, branch_id, event.turn_id,
                             type=f"memory:{event.type}", payload={"text": event.text},
                             visibility=event.visibility)

    def search(self, campaign_id: str, branch_id: str, query: str,
               limit: int = 5) -> list[MemoryHit]:
        keywords = [k for k in re.split(r"[\s，。！？、,.!?]+", query) if len(k) >= 2][:4]
        if not keywords:
            keywords = [query]
        scored = []
        for row in self._repo.list_events(campaign_id, branch_id):
            text = json.loads(row.payload_json).get("text", "")
            score = sum(1 for k in keywords if k in text)
            if score > 0:
                scored.append((score, row.turn_id, row.seq, text))
        scored.sort(key=lambda t: (-t[0], -t[1], -t[2]))
        return [MemoryHit(text=t[3], turn_id=t[1]) for t in scored[:limit]]

    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str:
        parts: list[str] = []
        summary = self._repo.latest_summary(campaign_id, branch_id)
        if summary:
            parts.append(f"【前情摘要】{summary.content}")
        events = self._repo.list_events(campaign_id, branch_id)[-8:]
        recent = [json.loads(e.payload_json).get("text", "") for e in events]
        if recent:
            parts.append("【近期事件】\n" + "\n".join(f"- {t}" for t in recent))
        return "\n".join(parts)[:budget_chars]

    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None:
        last = self._repo.latest_summary(campaign_id, branch_id)
        start = (last.upto_turn + 1) if last else 0
        events = [e for e in self._repo.list_events(campaign_id, branch_id, upto_turn=turn_id)
                  if e.turn_id >= start]
        if not events:
            return
        if last is not None and len(events) < SUMMARY_TRIGGER_EVENTS:
            return
        texts = [json.loads(e.payload_json).get("text", "") for e in events]
        body = "\n".join(t for t in texts if t)
        if self._summarizer is not None:
            prior = f"已有摘要：{last.content}\n" if last else ""
            content = self._summarizer([
                ChatMessage(role="system", content=_SUMMARY_PROMPT),
                ChatMessage(role="user", content=f"{prior}新事件：\n{body}"),
            ])
        else:
            content = (f"{last.content} " if last else "") + body
            content = content.strip()[:300]
        self._repo.append_summary(campaign_id, branch_id, upto_turn=turn_id, content=content)
