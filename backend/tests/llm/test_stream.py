import pytest

from app.config import Pricing, PricingEntry, Settings
from app.llm.client import (BudgetPausedError, ChatMessage, ChatResponse, LLMClient,
                            LlmContext)
from app.llm.fakes import FakeLLM

MSGS = [ChatMessage(role="user", content="你好")]
CTX = LlmContext(campaign_id="c1", branch_id="c1@main", turn_id=1)


class Sink:
    def __init__(self):
        self.rows = []

    def record_usage(self, campaign_id, branch_id, turn_id, role, model,
                     tokens_in, tokens_out, cost_usd, latency_ms) -> None:
        self.rows.append({"campaign_id": campaign_id, "branch_id": branch_id,
                          "turn_id": turn_id, "role": role, "model": model,
                          "tokens_in": tokens_in, "tokens_out": tokens_out,
                          "cost_usd": cost_usd, "latency_ms": latency_ms})


def make_pricing():
    return Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "alt-cheap-model": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })


def make_client(script, budget_probe=None):
    # gm 用真名；cheap 用虚构名以区分"超限切换"路由（生产两档同名，见 config.py）
    settings = Settings(gm_model="qwen3.8-flash", cheap_model="alt-cheap-model")
    sink = Sink()
    built: dict = {}

    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script))
        return built[model]

    return (LLMClient(settings, make_pricing(), usage_sink=sink, model_factory=factory,
                      budget_probe=budget_probe), built, sink.rows)


def test_stream_joins_to_full_text_and_records_once():
    client, _, rows = make_client(["你好，世界！"])
    text = "".join(client.chat_stream("gm", MSGS, CTX))
    assert text == "你好，世界！"
    assert len(rows) == 1
    assert rows[0]["model"] == "qwen3.8-flash"
    assert rows[0]["tokens_in"] == 10 and rows[0]["tokens_out"] == 20


def test_stream_cheap_routing():
    client, built, rows = make_client(["x"])
    text = "".join(client.chat_stream("gm", MSGS, CTX, cheap=True))
    assert text == "x" and "alt-cheap-model" in built
    assert rows[0]["model"] == "alt-cheap-model"


def test_stream_usage_estimate_when_provider_silent():
    class SilentModel:
        def chat(self, messages):
            return ChatResponse(text="")

        def chat_stream(self, messages, usage):
            yield "abcd"
            yield "ef"

    sink = Sink()
    client = LLMClient(Settings(), make_pricing(), usage_sink=sink,
                       model_factory=lambda *_: SilentModel())
    text = "".join(client.chat_stream("gm", MSGS, CTX))
    assert text == "abcdef"
    assert sink.rows[0]["tokens_out"] == 3          # 6 字符 // 2
    assert sink.rows[0]["tokens_in"] >= 1           # 估算兜底


def test_stream_chunks_respect_text():
    client, _, _ = make_client([ChatResponse(text="0123456789", tokens_in=1, tokens_out=2)])
    chunks = list(client.chat_stream("gm", MSGS, CTX))
    assert "".join(chunks) == "0123456789" and len(chunks) == 2   # chunk_size=8


def test_stream_budget_probe_exceeded_switches_to_cheap():
    """检查点②对流式同样生效：exceeded → 本次流式调用走 cheap 档。"""
    client, _, rows = make_client(["兜底"], budget_probe=lambda ctx: "exceeded")
    assert "".join(client.chat_stream("gm", MSGS, CTX)) == "兜底"
    assert rows[0]["model"] == "alt-cheap-model"


def test_stream_budget_probe_paused_blocks_call():
    """战役成本触顶：流式调用在开始前被拒绝（不触发模型、不记账）。"""
    client, built, rows = make_client(["从未被调用"], budget_probe=lambda ctx: "paused")
    with pytest.raises(BudgetPausedError):
        list(client.chat_stream("gm", MSGS, CTX))
    assert rows == [] and "qwen3.8-flash" not in built
