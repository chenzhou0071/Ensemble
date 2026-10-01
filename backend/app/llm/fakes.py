"""测试与开发用的假模型。"""
from typing import Iterator

from app.llm.client import ChatMessage, ChatResponse, StreamUsage


class FakeLLM:
    """脚本化假模型：按顺序吐响应，记录收到的消息。"""

    def __init__(self, script: list[str | ChatResponse], tokens_in: int = 10,
                 tokens_out: int = 20, chunk_size: int = 8):
        self.script = list(script)
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.chunk_size = chunk_size
        self.index = 0
        self.calls: list[list[ChatMessage]] = []

    def _next(self) -> str | ChatResponse:
        if self.index >= len(self.script):
            raise IndexError("FakeLLM script exhausted")
        item = self.script[self.index]
        self.index += 1
        return item

    def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        self.calls.append(messages)
        item = self._next()
        if isinstance(item, ChatResponse):
            return item
        return ChatResponse(text=item, tokens_in=self.tokens_in, tokens_out=self.tokens_out)

    def chat_stream(self, messages: list[ChatMessage], usage: StreamUsage) -> Iterator[str]:
        """与 chat 共用脚本消耗逻辑；按 chunk_size 切块 yield（模拟流式增量）。"""
        self.calls.append(messages)
        item = self._next()
        if isinstance(item, ChatResponse):
            usage.tokens_in, usage.tokens_out = item.tokens_in, item.tokens_out
            text = item.text
        else:
            usage.tokens_in, usage.tokens_out = self.tokens_in, self.tokens_out
            text = item
        for i in range(0, len(text), self.chunk_size):
            yield text[i:i + self.chunk_size]
