import pytest
from app.config import Pricing, PricingEntry, Settings
from app.llm.client import (BudgetPausedError, ChatMessage, LLMClient, LlmContext,
                            _request_kwargs, compute_cost)
from app.llm.fakes import FakeLLM

MSGS = [ChatMessage(role="user", content="你好")]
CTX = LlmContext(campaign_id="c1", branch_id="c1@main", turn_id=1)

class RecordingSink:
    def __init__(self):
        self.rows = []
    def record_usage(self, campaign_id, branch_id, turn_id, role, model,
                     tokens_in, tokens_out, cost_usd, latency_ms) -> None:
        self.rows.append({
            "campaign_id": campaign_id, "branch_id": branch_id, "turn_id": turn_id,
            "role": role, "model": model, "tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost_usd": cost_usd, "latency_ms": latency_ms,
        })

def make_client(script_texts, settings=None, budget_probe=None):
    if settings is None:
        settings = Settings()
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.000113, output_per_1k=0.00038),
        "deepseek-flash": PricingEntry(input_per_1k=0.00028, output_per_1k=0.00113),
    })
    sink = RecordingSink()
    built: dict[str, FakeLLM] = {}

    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script_texts))
        return built[model]

    return LLMClient(settings, pricing, usage_sink=sink, model_factory=factory,
                     budget_probe=budget_probe), sink, built

def test_routes_role_to_configured_model_and_records_usage():
    client, sink, built = make_client(["GM 的回复"])
    text = client.chat("gm", MSGS, CTX)
    assert text == "GM 的回复"
    assert "qwen3.8-flash" in built
    row = sink.rows[0]
    assert row["role"] == "gm" and row["model"] == "qwen3.8-flash"
    assert row["tokens_in"] == 10 and row["tokens_out"] == 20 and row["cost_usd"] > 0

def test_cheap_switch_uses_cheap_model():
    client, sink, built = make_client(["兜底回复"], settings=Settings(cheap_model="alt-cheap-model"))
    client.chat("gm", MSGS, CTX, cheap=True)
    assert "alt-cheap-model" in built and sink.rows[0]["model"] == "alt-cheap-model"

def test_npc_role_uses_deepseek():
    client, sink, built = make_client(["NPC 的话"])
    client.chat("npc", MSGS, CTX)
    assert "deepseek-flash" in built

def test_cost_computation_and_unknown_model():
    pricing = Pricing(models={"a": PricingEntry(input_per_1k=0.001, output_per_1k=0.002)})
    assert compute_cost(pricing, "a", 1000, 500) == 0.002
    assert compute_cost(pricing, "unknown", 1000, 500) == 0.0

def test_fake_llm_exhaustion():
    f = FakeLLM([])
    with pytest.raises(IndexError):
        f.chat(MSGS)

def test_budget_probe_exceeded_switches_gm_to_cheap():
    """检查点②：调用前探针报 exceeded → 本次 GM 调用自动走 cheap 档。"""
    client, sink, built = make_client(
        ["兜底回复"], settings=Settings(cheap_model="alt-cheap-model"),
        budget_probe=lambda ctx: "exceeded")
    client.chat("gm", MSGS, CTX)
    assert sink.rows[0]["model"] == "alt-cheap-model"

def test_budget_probe_ok_keeps_normal_model():
    client, sink, built = make_client(["正常回复"], budget_probe=lambda ctx: "ok")
    client.chat("gm", MSGS, CTX)
    assert sink.rows[0]["model"] == "qwen3.8-flash"

def test_budget_probe_paused_blocks_call_without_usage():
    """战役成本触顶：调用被拒绝（抛 BudgetPausedError），不触发模型也不记账。"""
    client, sink, built = make_client(["从未被调用"], budget_probe=lambda ctx: "paused")
    with pytest.raises(BudgetPausedError):
        client.chat("gm", MSGS, CTX)
    assert sink.rows == [] and "qwen3.8-flash" not in built

def test_budget_probe_skipped_when_cheap_explicit():
    probed = []
    client, sink, built = make_client(
        ["x"], budget_probe=lambda ctx: probed.append(ctx) or "ok")
    client.chat("gm", MSGS, CTX, cheap=True)   # 已显式 cheap → 无需探测
    assert probed == []

def test_request_kwargs_disables_thinking_for_qwen_by_default():
    """qwen 系默认关闭思考模式（extra_body.enable_thinking=False，省 token）。"""
    kw = _request_kwargs("qwen3.8-flash", False, MSGS)
    assert kw["extra_body"] == {"enable_thinking": False}
    assert kw["messages"] == [{"role": "user", "content": "你好"}]

def test_request_kwargs_keeps_thinking_when_enabled():
    assert "extra_body" not in _request_kwargs("qwen3.8-flash", True, MSGS)

def test_request_kwargs_never_sends_extra_body_to_deepseek():
    assert "extra_body" not in _request_kwargs("deepseek-flash", False, MSGS)

def test_default_factory_reuses_model_instances():
    """默认工厂按 (model, base_url, api_key) 缓存实例（避免每次调用重建连接池）。"""
    client = LLMClient(Settings(), Pricing(models={}))
    m1 = client._factory("qwen3.8-flash", "http://localhost", "k")
    m2 = client._factory("qwen3.8-flash", "http://localhost", "k")
    assert m1 is m2
    assert client._factory("deepseek-flash", None, None) is not m1
