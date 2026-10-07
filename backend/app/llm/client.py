"""LLM 客户端：按角色分级路由、统一记账；对测试完全可注入。"""
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Literal, Protocol

from pydantic import BaseModel

from app.config import Pricing, Settings
from app.llm.usage import BudgetGuard, BudgetLevel
from app.obs.counters import get_counters
from app.obs.tracer import Tracer

Role = Literal["gm", "npc", "extractor"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResponse(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class StreamUsage:
    """流式调用的用量累加器：模型实现就地累写，未回 usage 时由 LLMClient 估算。"""
    tokens_in: int = 0
    tokens_out: int = 0


class ChatModel(Protocol):
    def chat(self, messages: list[ChatMessage]) -> ChatResponse: ...
    def chat_stream(self, messages: list[ChatMessage], usage: StreamUsage) -> Iterator[str]: ...


@dataclass(frozen=True)
class LlmContext:
    campaign_id: str
    branch_id: str
    turn_id: int


class UsageSink(Protocol):
    def record_usage(self, campaign_id: str, branch_id: str, turn_id: int, role: str,
                     model: str, tokens_in: int, tokens_out: int, cost_usd: float,
                     latency_ms: int) -> None: ...


class BudgetPausedError(RuntimeError):
    """战役成本触顶：LLM 调用被拒绝（规格 §9 ④；节点侧按失败不推进兜底）。"""


def compute_cost(pricing: Pricing, model: str, tokens_in: int, tokens_out: int) -> float:
    entry = pricing.models.get(model)
    if entry is None:
        return 0.0
    return round(tokens_in / 1000 * entry.input_per_1k + tokens_out / 1000 * entry.output_per_1k, 8)


class OpenAICompatModel:
    """OpenAI 兼容客户端（qwen / deepseek 均走此实现）。"""

    def __init__(self, api_key: str | None, base_url: str | None, model: str,
                 timeout_seconds: int = 60, enable_thinking: bool = False):
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._enable_thinking = enable_thinking
        self._client = None          # 懒加载并复用（连接池）

    def _openai_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url,
                                  timeout=self._timeout_seconds)
        return self._client

    def chat(self, messages: list[ChatMessage]) -> ChatResponse:
        resp = self._openai_client().chat.completions.create(
            **_request_kwargs(self.model, self._enable_thinking, messages))
        usage = resp.usage
        return ChatResponse(
            text=resp.choices[0].message.content or "",
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
        )

    def chat_stream(self, messages: list[ChatMessage], usage: StreamUsage) -> Iterator[str]:
        kwargs = _request_kwargs(self.model, self._enable_thinking, messages)
        try:
            stream = self._openai_client().chat.completions.create(
                **kwargs, stream=True, stream_options={"include_usage": True})
        except Exception:
            # 部分兼容端点不认 stream_options：退化为无 usage 流（由 LLMClient 估算）
            stream = self._openai_client().chat.completions.create(**kwargs, stream=True)
        for chunk in stream:
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage.tokens_in = getattr(u, "prompt_tokens", 0) or 0
                usage.tokens_out = getattr(u, "completion_tokens", 0) or 0
            if getattr(chunk, "choices", None):
                text = getattr(chunk.choices[0].delta, "content", None)
                if text:
                    yield text


def _request_kwargs(model: str, enable_thinking: bool,
                    messages: list[ChatMessage]) -> dict:
    """请求体组装：qwen 系默认关闭思考模式（省 token）；deepseek 不传该字段。"""
    kwargs: dict = {"model": model, "messages": [m.model_dump() for m in messages]}
    if model.startswith("qwen") and not enable_thinking:
        kwargs["extra_body"] = {"enable_thinking": False}
    return kwargs


ModelFactory = Callable[[str, "str | None", "str | None"], ChatModel]


def _make_cached_factory(settings: Settings) -> ModelFactory:
    """默认工厂：按 (model, base_url, api_key) 缓存实例（连接池复用 + 透传超时与思考开关）。"""
    cache: dict[tuple[str, str | None, str | None], ChatModel] = {}

    def factory(model: str, base_url: str | None, api_key: str | None) -> ChatModel:
        key = (model, base_url, api_key)
        if key not in cache:
            cache[key] = OpenAICompatModel(api_key=api_key, base_url=base_url, model=model,
                                           timeout_seconds=settings.request_timeout_seconds,
                                           enable_thinking=settings.enable_thinking)
        return cache[key]

    return factory


def make_repo_budget_probe(repo, guard: BudgetGuard) -> Callable[[LlmContext], str]:
    """检查点②探针（规格 §9）：每次 LLM 调用前读该回合与战役的实时累计。"""

    def probe(ctx: LlmContext) -> str:
        return str(guard.check(
            repo.turn_token_total(ctx.campaign_id, ctx.branch_id, ctx.turn_id),
            repo.campaign_cost_total(ctx.campaign_id)))

    return probe


class LLMClient:
    def __init__(self, settings: Settings, pricing: Pricing,
                 usage_sink: UsageSink | None = None, model_factory: ModelFactory | None = None,
                 budget_probe: Callable[[LlmContext], str] | None = None,
                 tracer: Tracer | None = None):
        self._settings = settings
        self._pricing = pricing
        self._usage_sink = usage_sink
        self._factory: ModelFactory = model_factory or _make_cached_factory(settings)
        self._budget_probe = budget_probe
        self._tracer = tracer

    def _start_llm_run(self, role: Role, messages: list[ChatMessage], model: str,
                       cheap: bool) -> str | None:
        if self._tracer is None:
            return None
        return self._tracer.start_run(
            name=f"llm:{role}", run_type="llm",
            inputs={"role": role, "model": model, "cheap": cheap,
                    "messages": [{"role": m.role, "content": m.content}
                                 for m in messages]},
            parent_run_id=self._tracer.current_turn_run_id)

    def _finish_llm_run(self, run_id: str | None, outputs: dict | None = None,
                        error: str | None = None) -> None:
        if self._tracer is not None and run_id is not None:
            self._tracer.finish_run(run_id, outputs=outputs, error=error)

    def chat(self, role: Role, messages: list[ChatMessage], ctx: LlmContext,
             cheap: bool = False) -> str:
        # 检查点②（规格 §9）：每次调用前读实时累计——exceeded 自动降档，paused 拒绝调用
        if not cheap and self._budget_probe is not None:
            level = str(self._budget_probe(ctx))
            if level == BudgetLevel.PAUSED:
                raise BudgetPausedError("campaign cost cap reached")
            if level == BudgetLevel.EXCEEDED:
                cheap = True
        model, base_url, api_key = self._resolve(role, cheap)
        model_obj = self._factory(model, base_url, api_key)
        run_id = self._start_llm_run(role, messages, model, cheap)
        start = time.perf_counter()
        try:
            resp = model_obj.chat(messages)
        except Exception as exc:
            get_counters().record_llm(ok=False)
            self._finish_llm_run(run_id, error=str(exc))
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        cost = compute_cost(self._pricing, model, resp.tokens_in, resp.tokens_out)
        if self._usage_sink is not None:
            self._usage_sink.record_usage(ctx.campaign_id, ctx.branch_id, ctx.turn_id,
                                          role, model, resp.tokens_in, resp.tokens_out,
                                          cost, latency_ms)
        self._finish_llm_run(run_id, outputs={"text": resp.text,
                                              "tokens_in": resp.tokens_in,
                                              "tokens_out": resp.tokens_out,
                                              "latency_ms": latency_ms,
                                              "cost_usd": cost})
        get_counters().record_llm(ok=True)
        return resp.text

    def chat_stream(self, role: Role, messages: list[ChatMessage], ctx: LlmContext,
                    cheap: bool = False) -> Iterator[str]:
        """流式输出；流正常结束后记一次账（消费方中途放弃则不记账、不落 trace）。

        与 chat 同规则：调用前经检查点②探针（exceeded 自动降档、paused 拒绝）。
        """
        if not cheap and self._budget_probe is not None:
            level = str(self._budget_probe(ctx))
            if level == BudgetLevel.PAUSED:
                raise BudgetPausedError("campaign cost cap reached")
            if level == BudgetLevel.EXCEEDED:
                cheap = True
        model, base_url, api_key = self._resolve(role, cheap)
        model_obj = self._factory(model, base_url, api_key)
        usage = StreamUsage()
        chars = 0
        parts: list[str] = []
        run_id = self._start_llm_run(role, messages, model, cheap)
        start = time.perf_counter()
        try:
            for delta in model_obj.chat_stream(messages, usage):
                chars += len(delta)
                parts.append(delta)
                yield delta
        except Exception as exc:
            get_counters().record_llm(ok=False)
            self._finish_llm_run(run_id, error=str(exc))
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        if usage.tokens_in == 0:
            usage.tokens_in = max(1, sum(len(m.content) for m in messages) // 2)
        if usage.tokens_out == 0:
            usage.tokens_out = max(1, chars // 2)
        cost = compute_cost(self._pricing, model, usage.tokens_in, usage.tokens_out)
        if self._usage_sink is not None:
            self._usage_sink.record_usage(ctx.campaign_id, ctx.branch_id, ctx.turn_id,
                                          role, model, usage.tokens_in, usage.tokens_out,
                                          cost, latency_ms)
        self._finish_llm_run(run_id, outputs={"text": "".join(parts),
                                              "tokens_in": usage.tokens_in,
                                              "tokens_out": usage.tokens_out,
                                              "latency_ms": latency_ms,
                                              "cost_usd": cost})
        get_counters().record_llm(ok=True)

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
