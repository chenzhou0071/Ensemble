"""降级路径 → 计数器挂钩：五类 fallback kind 各计一次（节点返回值保持既有语义）。"""
from app.config import Pricing, PricingEntry, Settings
from app.graph.nodes.gm import build_narrate_node, build_validate_node
from app.graph.nodes.memory import build_memory_query_node
from app.graph.npc import build_npc_worker
from app.graph.nodes.turn import build_intake_node
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.obs.counters import get_counters, reset_counters


def make_client(script: list[str]):
    built: dict[str, FakeLLM] = {}

    def factory(model, base_url, api_key):
        if model not in built:                     # 同一 model 复用同一脚本队列
            built[model] = FakeLLM(list(script))
        return built[model]

    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.001, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.0005, output_per_1k=0.001),
    })
    return LLMClient(Settings(), pricing, model_factory=factory)


def fallbacks() -> dict:
    return get_counters().snapshot()["fallbacks"]


def test_memory_failure_counts(campaign):
    reset_counters()

    class BrokenMemory:
        def get_context(self, *a, **kw):
            raise RuntimeError("memory down")

        def search(self, *a, **kw):
            raise RuntimeError("memory down")

        def update_summaries(self, *a, **kw):
            pass

    build_memory_query_node(BrokenMemory())({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
        "turn_id": 1, "decision": {"memory_queries": ["磨坊"]},
        "budget_level": "ok"})
    assert fallbacks() == {"memory_query": 1}


def test_npc_failure_counts_silent():
    reset_counters()

    class BrokenSubgraph:
        def invoke(self, task):
            raise RuntimeError("npc down")

    out = build_npc_worker(BrokenSubgraph())({"npc_id": "guard"})
    assert out["npc_reactions"]["guard"]["speech"] == ""   # 沉默占位照常返回
    assert fallbacks() == {"npc_silent": 1}


def test_decision_invalid_counts():
    reset_counters()
    client = make_client(["还不是 JSON"])
    upd = build_validate_node(client)({
        "decision_raw": "不是 JSON", "budget_level": "ok",
        "campaign_id": "c", "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] == "decision_invalid"
    assert fallbacks() == {"decision_invalid": 1}


def test_narrate_failed_counts(campaign, mini_module):
    reset_counters()
    client = make_client(["", "   "])
    upd = build_narrate_node(client, mini_module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
        "turn_id": 1, "scene_id": "gate", "is_opening": False,
        "player_inputs": [{"player_id": "p1", "character_id": "pc_1",
                           "text": "我想进城"}],
        "check_results": [], "npc_reactions": {},
        "memory_context": "", "budget_level": "ok"})
    assert upd["error"] == "narrate_failed"
    assert fallbacks() == {"narrate_failed": 1}


def test_budget_paused_counts(repo, campaign, mini_module):
    reset_counters()
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen3.8-flash",
                      1, 1, 5.0, 100)
    guard = BudgetGuard(Settings(campaign_cost_cap_usd=1.0))
    upd = build_intake_node(repo, mini_module, guard)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
        "turn_id": 0, "player_inputs": []})
    assert upd["budget_level"] == "paused" and upd["error"] == "budget_paused"
    assert fallbacks() == {"budget_paused": 1}
