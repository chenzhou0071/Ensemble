import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.content.schema import Module
from app.graph.main import build_game_graph
from app.graph.nodes.gm import build_validate_node
from app.graph.nodes.turn import build_post_turn_node, fallback
from app.graph.schemas import parse_decision_json
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.memory.base import MemoryEvent
from app.memory.journal import JournalMemory

MODULE_WITH_CLUE = {
    "meta": {"id": "clue_mod", "title": "线索模组"},
    "opening": {"narration": "开场", "scene_id": "a"},
    "scenes": [{"id": "a", "name": "A", "npcs": [], "exits": [], "clues": ["c1"]}],
    "npcs": [],
    "clues": [{"id": "c1", "content": "壁炉灰里有烧焦的纸片", "unlocks": []}],
    "endings": [{"id": "ed", "scene": "a", "condition": "烧掉契约"}],
}


def test_decision_defaults_include_new_fields():
    d = parse_decision_json('{"intent_summary": "x"}')
    assert d.clues_revealed == [] and d.ending_reached is None


def make_client(script):
    rows, built = [], {}

    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script))
        return built[model]

    class Sink:
        def record_usage(self, *a, **kw):
            rows.append(kw)

    settings = Settings(gm_model="qwen3.8-flash", cheap_model="alt-cheap-model")
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "alt-cheap-model": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    return LLMClient(settings, pricing, usage_sink=Sink(), model_factory=factory), built


def test_validate_repairs_unknown_clue(campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    bad = '{"intent_summary": "x", "clues_revealed": ["ghost_clue"]}'
    good = '{"intent_summary": "x", "clues_revealed": ["c1"]}'
    client, built = make_client([good])
    upd = build_validate_node(client, module)(
        {"decision_raw": bad, "budget_level": "ok", "campaign_id": "c",
         "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] is None and upd["decision"]["clues_revealed"] == ["c1"]
    assert "ghost_clue" in built["qwen3.8-flash"].calls[0][1].content   # repair 反馈包含非法引用


def test_validate_gives_up_on_unknown_ending(campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    bad = '{"intent_summary": "x", "ending_reached": "nope"}'
    client, built = make_client([bad])
    upd = build_validate_node(client, module)(
        {"decision_raw": bad, "budget_level": "ok", "campaign_id": "c",
         "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] == "decision_invalid"
    assert built["qwen3.8-flash"].calls[0][1].role == "user"


def test_post_turn_writes_clue_event_and_ending(repo, campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    written: list[MemoryEvent] = []

    class SpyMemory:
        def update_summaries(self, *a): ...
        def write_event(self, campaign_id, branch_id, event):
            written.append(event)

    upd = build_post_turn_node(repo, SpyMemory(), module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id, "turn_id": 2,
        "scene_id": "a", "npc_attitudes": {}, "narration": "叙事",
        "narration_segments": [{"speaker": "gm", "text": "叙事"}],
        "decision": {"clues_revealed": ["c1"], "ending_reached": "ed",
                     "checks": [], "proactive_npc_triggers": [],
                     "scene_transition": None, "memory_queries": []},
    })
    assert upd["ending_reached"] == "ed" and upd["turn_id"] == 3
    clues = repo.list_events(campaign.id, campaign.active_branch_id, types=["clue"])
    assert len(clues) == 1
    payload = json.loads(clues[0].payload_json)
    assert payload["clue_id"] == "c1" and "烧焦的纸片" in payload["text"]
    assert written and written[0].type == "clue"


def test_fallback_clears_ending_reached():
    upd = fallback({"error": "x", "ending_reached": "ed"})
    assert upd["ending_reached"] is None


def test_graph_ends_on_ending(repo, campaign, mini_module):
    decide_ending = ('{"intent_summary": "终结", "checks": [], "proactive_npc_triggers": [],'
                     ' "scene_transition": null, "memory_queries": [],'
                     ' "clues_revealed": [], "ending_reached": "e1"}')
    script = {"qwen3.8-flash": [
        '{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
        ' "scene_transition": null, "memory_queries": []}',
        "开场叙事。", decide_ending, "尘埃落定，故事就此收束。"]}
    queues = {m: list(v) for m, v in script.items()}

    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    client = LLMClient(Settings(), pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(Settings()), MemorySaver())
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1,
                                 "inputs": [{"player_id": "p1", "character_id": "pc_p1",
                                             "text": "终结这一切"}],
                                 "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ()                       # 结局：图结束，不再开输入窗口
    assert snap.values["ending_reached"] == "e1"


def test_validate_keeps_target_without_scene(campaign):
    module = Module.model_validate(MODULE_WITH_CLUE)
    raw = '{"intent_summary": "x", "checks": [{"actor": "pc_1", "skill": "格斗", "target": "ghost"}]}'
    client, built = make_client([])
    upd = build_validate_node(client, module)({
        "decision_raw": raw, "budget_level": "ok", "campaign_id": "c",
        "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] is None
    assert upd["decision"]["checks"][0]["target"] == "ghost"   # 无 scene_id：target 原样保留
