"""录制回放：默认零网络零 key；--record 时用真实模型重录基线。

fixture 格式（tests/fixtures/{module}/{scenario}/turn_{n}.json）：
{"responses": [{"model": "qwen3.8-flash", "text": "..."}, ...],  # 按请求时间顺序
 "seeds": [123, ...]}                                         # 本回合骰子 seed（可选）
"""
import json
from pathlib import Path

from app.llm.client import ChatResponse, LLMClient, OpenAICompatModel


class ReplayModels:
    """ChatModel 工厂 + 回放器：按录制顺序返回响应，顺序错位即断言失败。"""

    def __init__(self, entries: list[dict]):
        self.entries = list(entries)
        self.index = 0
        self.calls: list[dict] = []
        self._current_model = ""

    def factory(self, model: str, base_url: str | None, api_key: str | None):
        self._current_model = model
        return self

    def chat(self, messages):
        if self.index >= len(self.entries):
            raise IndexError("replay entries exhausted")
        entry = self.entries[self.index]
        self.index += 1
        assert entry["model"] == self._current_model, (
            f"回放顺序错位：录制为 {entry['model']}，本次请求路由到 {self._current_model}")
        self.calls.append({"model": self._current_model,
                           "messages": [m.model_dump() for m in messages]})
        return ChatResponse(text=entry["text"], tokens_in=10, tokens_out=20)

    def chat_stream(self, messages, usage):
        if self.index >= len(self.entries):
            raise IndexError("replay entries exhausted")
        entry = self.entries[self.index]
        self.index += 1
        assert entry["model"] == self._current_model, (
            f"回放顺序错位：录制为 {entry['model']}，本次请求路由到 {self._current_model}")
        self.calls.append({"model": self._current_model,
                           "messages": [m.model_dump() for m in messages]})
        usage.tokens_in, usage.tokens_out = 10, 20
        text = entry["text"]
        for i in range(0, len(text), 8):
            yield text[i:i + 8]


def load_turn(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_turn(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_replay_client(settings, pricing, fixture_paths, usage_sink=None):
    paths = fixture_paths if isinstance(fixture_paths, list) else [fixture_paths]
    entries: list[dict] = []
    for p in paths:
        entries.extend(load_turn(p)["responses"])
    replay = ReplayModels(entries)
    client = LLMClient(settings, pricing, usage_sink=usage_sink,
                       model_factory=replay.factory)
    return client, replay


def make_recording_factory(inner_factory, collected: list[dict]):
    """把真实模型的每次响应记入 collected（供 --record 落盘）。"""

    def factory(model: str, base_url: str | None, api_key: str | None):
        inner = inner_factory(model, base_url, api_key)

        class _RecordingModel:
            def chat(self, messages):
                resp = inner.chat(messages)
                collected.append({"model": model, "text": resp.text})
                return resp

            def chat_stream(self, messages, usage):
                text = ""
                for delta in inner.chat_stream(messages, usage):
                    text += delta
                    yield delta
                collected.append({"model": model, "text": text})

        return _RecordingModel()

    return factory


def build_recording_client(settings, pricing, usage_sink=None, real_factory=None):
    """--record 模式：真实调用 + 录制响应。"""
    collected: list[dict] = []
    inner_factory = real_factory or (
        lambda model, base_url, api_key: OpenAICompatModel(
            api_key=api_key, base_url=base_url, model=model,
            timeout_seconds=settings.request_timeout_seconds,
            enable_thinking=settings.enable_thinking))
    client = LLMClient(settings, pricing, usage_sink=usage_sink,
                       model_factory=make_recording_factory(inner_factory, collected))
    return client, collected
