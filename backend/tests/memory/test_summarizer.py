from app.config import Pricing, PricingEntry, Settings
from app.llm.client import ChatMessage, LLMClient
from app.llm.fakes import FakeLLM
from app.memory.summarizer import LLMSummarizer


class Sink:
    def __init__(self):
        self.rows = []

    def record_usage(self, campaign_id, branch_id, turn_id, role, model, tokens_in,
                     tokens_out, cost_usd, latency_ms):
        self.rows.append((campaign_id, branch_id, turn_id, role, model))


def test_uses_extractor_role_and_records_usage():
    settings = Settings(extractor_model="qwen-turbo")
    pricing = Pricing(models={"qwen-turbo": PricingEntry(input_per_1k=0.1, output_per_1k=0.2)})
    built = {}

    def factory(model, base_url, api_key):
        if model not in built:
            built[model] = FakeLLM(["压缩后的摘要"])
        return built[model]

    sink = Sink()
    client = LLMClient(settings, pricing, usage_sink=sink, model_factory=factory)
    result = LLMSummarizer(client)("c1", "c1@main", 7,
                                   [ChatMessage(role="user", content="事件")])
    assert result == "压缩后的摘要"
    assert "qwen-turbo" in built                        # extractor 路由
    assert built["qwen-turbo"].calls[0][0].content == "事件"
    assert sink.rows == [("c1", "c1@main", 7, "extractor", "qwen-turbo")]
