"""主图装配集成测试：开场 / 完整回合（含检定）/ 失败回退 / 场景移动 / 熔断 / NPC 扇出。"""
import json

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.content.schema import Module
from app.graph.main import build_game_graph
from app.llm.client import LLMClient, make_repo_budget_probe
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
OPENING_NARR = "雾气贴着地面爬行。村口的老树在风里摇晃。"


def make_env(repo, mini_module, scripts_by_model, tokens_per_call=(10, 20), **settings_overrides):
    # 模型名显式对齐脚本队列：gm/cheap → qwen3.8-flash，npc → deepseek-flash
    defaults = {"gm_model": "qwen3.8-flash", "cheap_model": "qwen3.8-flash",
                "npc_model": "deepseek-flash", "extractor_model": "qwen3.8-flash"}
    settings = Settings(**{**defaults, **settings_overrides})
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.000113, output_per_1k=0.00038),
        "deepseek-flash": PricingEntry(input_per_1k=0.00028, output_per_1k=0.00113),
    })
    queues = {m: list(v) for m, v in scripts_by_model.items()}
    model_calls: list[str] = []

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        model_calls.append(model)
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [],
                       tokens_in=tokens_per_call[0], tokens_out=tokens_per_call[1])

    client = LLMClient(settings, pricing, usage_sink=repo, model_factory=factory,
                       budget_probe=make_repo_budget_probe(repo, BudgetGuard(settings)))
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    return graph, model_calls


def config_for(repo, campaign):
    branch = repo.get_branch(campaign.active_branch_id)
    return {"configurable": {"thread_id": repo.thread_id_for(branch)}}


def init_state(campaign):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 0, "player_inputs": []}


def test_opening_turn_reaches_interrupt(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module,
                            {"qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)          # 已挂起等待输入
    assert snap.values["turn_id"] == 1           # post_turn 已推进
    assert snap.values["narration_segments"][0]["speaker"] == "gm"
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "turn_start" in types and "narration" in types
    assert calls == ["qwen3.8-flash", "qwen3.8-flash"]   # decide + narrate


def test_resume_runs_full_turn_with_check(repo, campaign, mini_module, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: 42)
    turn1_decide = ('{"intent_summary": "推门", "checks": [{"actor": "pc_1", "skill": "侦查",'
                    ' "difficulty": "regular"}], "proactive_npc_triggers": [],'
                    ' "scene_transition": null, "memory_queries": []}')
    graph, calls = make_env(repo, mini_module, {"qwen3.8-flash": [
        OPENING_DECIDE, OPENING_NARR, turn1_decide, "你推开木门，霉味扑面而来。"]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(Command(resume={
        "turn_id": 1,
        "inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我推门进去"}],
        "skipped": [],
    }), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 1 and rows[0].seed == 42 and rows[0].skill == "侦查"
    assert 1 <= snap.values["check_results"][0]["roll"] <= 100
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert types.count("check") == 1
    assert types.count("narration") == 2


def test_validate_failure_falls_back_to_wait(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module,
                            {"qwen3.8-flash": ["这不是 JSON", "还是不是 JSON"]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)              # 失败不推进，回到输入等待
    assert snap.values["error"] == "decision_invalid"
    assert snap.values["narration"] == ""
    assert snap.values["turn_id"] == 0
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "narration" not in types and "check" not in types


def test_scene_transition_moves_player(repo, campaign, mini_module):
    move_decide = ('{"intent_summary": "进酒馆", "checks": [], "proactive_npc_triggers": [],'
                   ' "scene_transition": {"to_scene": "tavern", "reason": "玩家推门"},'
                   ' "memory_queries": []}')
    graph, calls = make_env(repo, mini_module, {"qwen3.8-flash": [
        OPENING_DECIDE, OPENING_NARR, move_decide, "你推门走进酒馆，壁炉的热气扑面。"]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(Command(resume={
        "turn_id": 1,
        "inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我走进酒馆"}],
        "skipped": [],
    }), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["scene_id"] == "tavern"       # apply_transition 已生效
    changed = repo.list_events(campaign.id, campaign.active_branch_id,
                               types=["scene_changed"])
    assert len(changed) == 1 and json.loads(changed[0].payload_json)["reason"] == "玩家推门"


def test_paused_halts_without_llm(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen3.8-flash",
                      1, 1, 5.0, 100)  # 成本 5.0 > 显式上限 2.0 → 战役熔断
    graph, calls = make_env(repo, mini_module, {}, campaign_cost_cap_usd=2.0)
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ()                           # 图结束（战役熔断，无挂起）
    assert snap.values["error"] == "budget_paused"
    assert calls == []                               # 没有任何 LLM 调用


TWIN_MODULE_DICT = {
    "meta": {"id": "twin", "title": "双人模组"},
    "opening": {"narration": "开场叙述", "scene_id": "gate"},
    "scenes": [
        {"id": "gate", "name": "村口", "npcs": ["guard", "barkeep"], "exits": ["tavern"]},
        {"id": "tavern", "name": "酒馆", "npcs": [], "exits": []},
    ],
    "npcs": [
        {"id": "guard", "name": "王守卫", "persona": "多疑的老兵", "initial_attitude": 40},
        {"id": "barkeep", "name": "刘老板", "persona": "健谈的酒馆老板", "initial_attitude": 60},
    ],
    "clues": [],
    "endings": [{"id": "e1", "scene": "tavern", "condition": "揭开真相"}],
}
FANOUT_DECIDE = ('{"intent_summary": "打量四周", "checks": [],'
                 ' "proactive_npc_triggers": [{"npc_id": "guard", "trigger": "玩家东张西望"},'
                 ' {"npc_id": "barkeep", "trigger": "玩家环顾四周"}],'
                 ' "scene_transition": null, "memory_queries": []}')
GUARD_REPLY = '{"speech": "别乱走，这里不太平。", "action": "把手按在枪套上"}'
BARKEEP_REPLY = '{"speech": "要来一杯吗？", "action": "擦着杯子"}'


def test_npc_fanout_merges_reactions(repo, campaign):
    """两名在场 NPC 同时被触发：Send 并行执行 → 反应合并回主图 → 汇合 narrate 收尾。"""
    twin = Module.model_validate(TWIN_MODULE_DICT)
    graph, calls = make_env(repo, twin, {
        "qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR, FANOUT_DECIDE,
                          "王守卫的手按在枪套上，刘老板擦着杯子看了你们一眼。"],
        "deepseek-flash": [GUARD_REPLY, BARKEEP_REPLY],
    })
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(Command(resume={
        "turn_id": 1,
        "inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我环顾四周"}],
        "skipped": [],
    }), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert set(snap.values["npc_reactions"].keys()) == {"guard", "barkeep"}
    assert all(r["speech"] for r in snap.values["npc_reactions"].values())
    assert calls.count("deepseek-flash") == 2        # 两名 NPC 各一次，Send 并行


def test_decide_llm_error_falls_back_to_wait(repo, campaign, mini_module):
    """decide 的 LLM 调用抛异常（网络/超时/预算熔断）→ 失败不推进，回到输入等待。"""
    graph, calls = make_env(repo, mini_module, {})   # 空脚本：decide 调用即 IndexError
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["error"] == "decide_failed"
    assert snap.values["turn_id"] == 0


def test_turn_over_cap_downgrades_followup_calls(repo, campaign, mini_module):
    """检查点②：回合内首次调用后即超 turn cap → 后续 GM 调用自动切 cheap；
    回合开始的采样读数仍为 0（ok）——证明回合内探针独立生效。"""
    graph, calls = make_env(repo, mini_module,
                            {"qwen3.8-flash": [OPENING_DECIDE],
                             "alt-cheap-model": [OPENING_NARR]},
                            tokens_per_call=(1000, 1000),
                            turn_token_cap=2000, cheap_model="alt-cheap-model")
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert calls == ["qwen3.8-flash", "alt-cheap-model"]   # 第二次调用被探针降级
    starts = repo.list_events(campaign.id, campaign.active_branch_id, types=["turn_start"])
    assert json.loads(starts[0].payload_json)["budget_level"] == "ok"  # 回合开始读数为 0
