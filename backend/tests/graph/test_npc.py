import copy

from app.config import Pricing, PricingEntry, Settings
from app.content.schema import Module
from app.graph.npc import (assemble_persona, build_npc_dispatch, build_npc_subgraph,
                           build_npc_worker)
from app.llm.client import LLMClient


def make_client(script):
    settings = Settings(npc_model="deepseek-chat")
    pricing = Pricing(models={
        "deepseek-chat": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    built: dict = {}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        if model not in built:
            built[model] = FakeLLM(list(script))
        return built[model]

    return LLMClient(settings, pricing, model_factory=factory), built


def task_dict(**extra):
    base = {"npc_id": "guard", "trigger": "玩家翻墙被巡逻队看到", "campaign_id": "c1",
            "branch_id": "c1@main", "turn_id": 1, "scene_name": "村口",
            "scene_description": "雾很重", "npc_name": "王守卫", "npc_persona": "多疑的老兵",
            "npc_attitude": 40, "memory_context": "玩家曾被警告过",
            "player_inputs": [{"player_id": "p1", "text": "我想进城"}],
            "check_results": [{"skill": "潜行", "roll": 30, "skill_value": 50, "success": True}]}
    return {**base, **extra}


def state_dict(**extra):
    return {"campaign_id": "c1", "branch_id": "c1@main", "turn_id": 1,
            "scene_id": "gate", "npc_attitudes": {"guard": 40, "barkeep": 60},
            "player_inputs": [], "check_results": [], "memory_context": "",
            "budget_level": "ok", **extra}


def test_assemble_persona_contains_context():
    out = assemble_persona(task_dict())
    system, user = out["messages"][0]["content"], out["messages"][1]["content"]
    assert '"speech"' in system and '"action"' in system  # 格式约束（NPC_SYSTEM）必须接入
    assert "王守卫" in system and "多疑的老兵" in system and "40" in system
    assert "潜行" in system and "玩家曾被警告过" in system
    assert "我想进城" in user and "玩家翻墙被巡逻队看到" in user


def test_subgraph_parses_fenced_reaction():
    client, built = make_client(['```json\n{"speech": "站住！", "action": "伸手拦路"}\n```'])
    final = build_npc_subgraph(client).invoke(task_dict())
    assert final["reaction"] == {"npc_id": "guard", "speech": "站住！", "action": "伸手拦路"}
    assert "deepseek-chat" in built


def test_worker_silent_when_parse_fails():
    client, _ = make_client(["这里没有 JSON"])
    worker = build_npc_worker(build_npc_subgraph(client))
    out = worker(task_dict())
    assert out["npc_reactions"]["guard"]["speech"] == ""


def test_worker_silent_when_llm_raises():
    client, _ = make_client([])  # FakeLLM 脚本耗尽 → IndexError
    worker = build_npc_worker(build_npc_subgraph(client))
    out = worker(task_dict())
    assert out["npc_reactions"] == {"guard": {"npc_id": "guard", "speech": "", "action": None}}


def test_dispatch_dedups_and_filters_out_of_scene(mini_module):
    d = build_npc_dispatch(mini_module)
    state = state_dict(decision={"proactive_npc_triggers": [
        {"npc_id": "guard", "trigger": "t1"}, {"npc_id": "guard"}, {"npc_id": "ghost"},
        {"npc_id": "barkeep", "trigger": "t2"}]})
    sends = d(state)  # guard 在村口保留；ghost 未知、barkeep 在酒馆 → 都被过滤
    assert [s.arg["npc_id"] for s in sends] == ["guard"]
    assert sends[0].arg["npc_name"] == "王守卫" and sends[0].arg["trigger"] == "t1"


def test_dispatch_both_npcs_in_scene_two_sends(mini_module):
    data = copy.deepcopy(mini_module.model_dump())
    data["scenes"][0]["npcs"] = ["guard", "barkeep"]  # 同场景两人
    mod = Module.model_validate(data)
    d = build_npc_dispatch(mod)
    state = state_dict(decision={"proactive_npc_triggers": [
        {"npc_id": "guard", "trigger": "t1"}, {"npc_id": "barkeep", "trigger": "t2"}]})
    assert [s.arg["npc_id"] for s in d(state)] == ["guard", "barkeep"]


def test_dispatch_tight_keeps_first_only(mini_module):
    d = build_npc_dispatch(mini_module)
    state = state_dict(budget_level="tight", decision={"proactive_npc_triggers": [
        {"npc_id": "guard"}, {"npc_id": "barkeep"}]})
    assert [s.arg["npc_id"] for s in d(state)] == ["guard"]


def test_dispatch_name_mention_fallback(mini_module):
    d = build_npc_dispatch(mini_module)
    state = state_dict(decision={},
                       player_inputs=[{"player_id": "p1", "text": "我问王守卫，到底发生了什么"}])
    assert [s.arg["npc_id"] for s in d(state)] == ["guard"]


def test_dispatch_no_candidates_returns_narrate(mini_module):
    d = build_npc_dispatch(mini_module)
    assert d(state_dict(decision={})) == "gm_narrate"
