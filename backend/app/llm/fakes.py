"""测试与开发用的假模型。"""
from app.llm.client import ChatMessage, ChatResponse


class FakeLLM:
    """脚本化假模型：按顺序吐响应，记录收到的消息。"""

    def __init__(self, script: list[str | ChatResponse], tokens_in: int = 10,
                 tokens_out: int = 20):
        self.script = list(script)
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.index = 0
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        self.calls.append(messages)
        if self.index >= len(self.script):
            raise IndexError("FakeLLM script exhausted")
        item = self.script[self.index]
        self.index += 1
        if isinstance(item, ChatResponse):
            return item
        return ChatResponse(text=item, tokens_in=self.tokens_in, tokens_out=self.tokens_out)
