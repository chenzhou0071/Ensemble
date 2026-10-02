import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.graph.main import build_game_graph
from app.graph.nodes.turn import build_post_turn_node
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
OPENING_NARR = "雾气贴着地面爬行。"
THREATEN_DECIDE = ('{"intent_summary": "威胁守卫", "checks": [], "proactive_npc_triggers": [],'
                   ' "scene_transition": null, "memory_queries": [],'
                   ' "attitude_deltas": [{"npc_id": "guard", "delta": -10, "reason": "出言威胁"},'
                   ' {"npc_id": "barkeep", "delta": 5, "reason": "不在场应被丢弃"}]}')


class SpyMemory:
    def update_summaries(self, *args): ...


def test_post_turn_applies_present_delta_only(repo, campaign, mini_module):
    upd = build_post_turn_node(repo, SpyMemory(), mini_module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id, "turn_id": 2,
        "scene_id": "gate", "npc_attitudes": {"guard": 40, "barkeep": 60},
        "narration": "叙事", "narration_segments": [],
        "decision": {"attitude_deltas": [{"npc_id": "guard", "delta": -10, "reason": "出言威胁"},
                                         {"npc_id": "barkeep", "delta": 5, "reason": "不在场"}],
                     "clues_revealed": [], "ending_reached": None},
    })
    assert upd["npc_attitudes"] == {"guard": 30, "barkeep": 60}   # 仅在场者变化，返回值携带新表
    assert upd["turn_id"] == 3
    rows = repo.list_events(campaign.id, campaign.active_branch_id, types=["attitude"])
    assert len(rows) == 1 and rows[0].visibility == "all"
    assert json.loads(rows[0].payload_json) == {"npc_id": "guard", "old": 40, "new": 30,
                                                "delta": -10, "reason": "出言威胁"}
    snap = repo.get_state_at(campaign.id, campaign.active_branch_id, 2)
    assert snap["npc_attitudes"] == {"guard": 30, "barkeep": 60}  # 快照自动持久化


def test_post_turn_invalid_deltas_do_not_break_turn(repo, campaign, mini_module):
    upd = build_post_turn_node(repo, SpyMemory(), mini_module)({
        "campaign_id": campaign.id, "branch_id": campaign.active_branch_id, "turn_id": 2,
        "scene_id": "gate", "npc_attitudes": {"guard": 40},
        "narration": "", "narration_segments": [],
        "decision": {"attitude_deltas": [{"npc_id": "ghost", "delta": 5, "reason": "幻觉"},
                                         {"npc_id": "guard", "delta": "大", "reason": "类型错"}],
                     "clues_revealed": [], "ending_reached": None},
    })
    assert upd["turn_id"] == 3 and "npc_attitudes" not in upd   # 无变更：不携带、无事件、不异常
    assert repo.list_events(campaign.id, campaign.active_branch_id, types=["attitude"]) == []
    snap = repo.get_state_at(campaign.id, campaign.active_branch_id, 2)
    assert snap["npc_attitudes"] == {"guard": 40}


def _env(repo, mini_module, script):
    settings = Settings(gm_model="qwen3.8-flash", cheap_model="qwen3.8-flash",
                        npc_model="deepseek-flash", extractor_model="qwen3.8-flash")
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.000113, output_per_1k=0.00038),
        "deepseek-flash": PricingEntry(input_per_1k=0.00028, output_per_1k=0.00113)})
    queues = {m: list(v) for m, v in script.items()}
    built: list[FakeLLM] = []

    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        llm = FakeLLM([items.pop(0)] if items else [])
        built.append(llm)
        return llm

    client = LLMClient(settings, pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    return graph, built


def test_attitude_change_reaches_next_turn_prompt(repo, campaign, mini_module):
    graph, built = _env(repo, mini_module, {"qwen3.8-flash": [
        OPENING_DECIDE, OPENING_NARR, THREATEN_DECIDE, "守卫冷冷地侧过身。",
        OPENING_DECIDE, "你看见他攥紧了枪带。"]})
    branch = repo.get_branch(campaign.active_branch_id)
    cfg = {"configurable": {"thread_id": repo.thread_id_for(branch)}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1, "inputs": [
        {"player_id": "p1", "character_id": "pc_1", "text": "我压低声音威胁守卫放行"}],
        "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["npc_attitudes"]["guard"] == 30
    rows = repo.list_events(campaign.id, campaign.active_branch_id, types=["attitude"])
    assert len(rows) == 1 and json.loads(rows[0].payload_json)["delta"] == -10

    graph.invoke(Command(resume={"turn_id": 2, "inputs": [
        {"player_id": "p1", "character_id": "pc_1", "text": "我径直朝酒馆走去"}],
        "skipped": []}), cfg)
    assert graph.get_state(cfg).next == ("wait_input",)
    prompt = built[4].calls[0][1].content        # 第 5 次 qwen 调用 = 回合 2 的 decide
    assert "当前态度 30" in prompt               # 变化自下一回合起生效
