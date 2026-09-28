"""LLM 摘要器：把 JournalMemory 的 summarizer 钩子接到 LLMClient（extractor 角色 + 记账）。"""
from app.llm.client import ChatMessage, LLMClient, LlmContext


class LLMSummarizer:
    def __init__(self, client: LLMClient):
        self._client = client

    def __call__(self, campaign_id: str, branch_id: str, turn_id: int,
                 messages: list[ChatMessage]) -> str:
        return self._client.chat(
            "extractor", messages,
            LlmContext(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id))
