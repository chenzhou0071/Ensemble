import pytest
from app.config import Pricing, PricingEntry, Settings
from app.llm.client import ChatMessage, LLMClient, LlmContext, compute_cost
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

def make_client(script_texts, settings=None):
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

    return LLMClient(settings, pricing, usage_sink=sink, model_factory=factory), sink, built

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
