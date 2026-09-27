"""LLM 客户端：按角色分级路由、统一记账；对测试完全可注入。"""
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from pydantic import BaseModel

from app.config import Pricing, Settings

Role = Literal["gm", "npc", "extractor"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResponse(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class ChatModel(Protocol):
    def chat(self, messages: list[ChatMessage]) -> ChatResponse: ...


@dataclass(frozen=True)
class LlmContext:
    campaign_id: str
    branch_id: str
    turn_id: int


class UsageSink(Protocol):
    def record_usage(self, campaign_id: str, branch_id: str, turn_id: int, role: str,
                     model: str, tokens_in: int, tokens_out: int, cost_usd: float,
                     latency_ms: int) -> None: ...


def compute_cost(pricing: Pricing, model: str, tokens_in: int, tokens_out: int) -> float:
    entry = pricing.models.get(model)
    if entry is None:
        return 0.0
    return round(tokens_in / 1000 * entry.input_per_1k + tokens_out / 1000 * entry.output_per_1k, 8)


class OpenAICompatModel:
    """OpenAI 兼容客户端（qwen / deepseek 均走此实现）。"""

    def __init__(self, api_key: str | None, base_url: str | None, model: str,
                 timeout_seconds: int = 60):
        from openai import OpenAI
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)

    def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[m.model_dump() for m in messages],
        )
        usage = resp.usage
        return ChatResponse(
            text=resp.choices[0].message.content or "",
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
        )


ModelFactory = Callable[[str, "str | None", "str | None"], ChatModel]


def _default_factory(model: str, base_url: str | None, api_key: str | None) -> ChatModel:
    return OpenAICompatModel(api_key=api_key, base_url=base_url, model=model)


class LLMClient:
    def __init__(self, settings: Settings, pricing: Pricing,
                 usage_sink: UsageSink | None = None, model_factory: ModelFactory | None = None):
        self._settings = settings
        self._pricing = pricing
        self._usage_sink = usage_sink
        self._factory: ModelFactory = model_factory or _default_factory

    def chat(self, role: Role, messages: list[ChatMessage], ctx: LlmContext,
             cheap: bool = False) -> str:
        model, base_url, api_key = self._resolve(role, cheap)
        model_obj = self._factory(model, base_url, api_key)
        start = time.perf_counter()
        resp = model_obj.chat(messages)
        latency_ms = int((time.perf_counter() - start) * 1000)
        cost = compute_cost(self._pricing, model, resp.tokens_in, resp.tokens_out)
        if self._usage_sink is not None:
            self._usage_sink.record_usage(ctx.campaign_id, ctx.branch_id, ctx.turn_id,
                                          role, model, resp.tokens_in, resp.tokens_out,
                                          cost, latency_ms)
        return resp.text

    def _resolve(self, role: Role, cheap: bool) -> tuple[str, str | None, str | None]:
        if role == "gm":
            model = self._settings.cheap_model if cheap else self._settings.gm_model
        elif role == "npc":
            model = self._settings.npc_model
        else:
            model = self._settings.extractor_model
        if model.startswith("deepseek"):
            return model, self._settings.deepseek_base_url, self._settings.deepseek_api_key
        return model, self._settings.qwen_base_url, self._settings.qwen_api_key
