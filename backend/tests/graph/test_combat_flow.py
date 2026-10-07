import json

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.content.schema import Module
from app.graph.main import build_game_graph
from app.graph.nodes.gm import build_narrate_node, build_validate_node
from app.graph.nodes.turn import build_combat_resolve_node, build_resolve_checks_node
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.check import CheckDifficulty, CheckResult, SuccessLevel
from app.rules.combat import CombatOutcome

MODULE_WITH_COMBAT = {
    "meta": {"id": "combat_mod", "title": "战斗模组"},
    "opening": {"narration": "开场叙述", "scene_id": "yard"},
    "scenes": [{"id": "yard", "name": "后院", "npcs": ["thug", "kid"], "exits": []}],
    "npcs": [
        {"id": "thug", "name": "流氓", "persona": "凶悍的打手", "initial_attitude": 30,
         "combat": {"defense": 40, "damage": "1d4", "hp": 8}},
        {"id": "kid", "name": "小孩", "persona": "好奇的孩子", "initial_attitude": 60},
    ],
    "clues": [],
    "endings": [],
}


def make_client(script):
    settings = Settings()
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    built: dict = {}

    def factory(model, base_url, api_key):
        built[model] = FakeLLM(list(script))
        return built[model]

    return LLMClient(settings, pricing, model_factory=factory), built


def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "scene_id": "yard", "is_opening": False,
            "characters": {"pc_1": {"id": "pc_1", "skills": {"格斗": 70, "侦查": 50}}},
            "npc_hp": {},
            "player_inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我挥拳打过去"}],
            "check_results": [], "npc_reactions": {}, "memory_context": "",
            "budget_level": "ok", "decision": {"checks": []}, **extra}


def fake_outcome(hit=True, damage=4):
    attack = CheckResult("pc_1", "格斗", 70, CheckDifficulty.REGULAR, 22, 777,
                         SuccessLevel.HARD, True)
    defense = CheckResult("thug", "闪避", 40, CheckDifficulty.REGULAR, 80, 778,
                          SuccessLevel.FAIL, False)
    return CombatOutcome(attack=attack, defense=defense, hit=hit,
                         damage=damage if hit else 0)


@pytest.fixture
def resolve_node(repo, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: 123)
    return build_resolve_checks_node(repo)


def test_combat_resolve_applies_damage_and_records(repo, campaign, monkeypatch):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    seen: dict = {}

    def fake_resolve_attack(actor, skill, attack_value, defender, defense_value, damage_dice,
                            seed, difficulty=CheckDifficulty.REGULAR, bonus=0, penalty=0):
        seen.update(actor=actor, skill=skill, attack_value=attack_value, defender=defender,
                    defense_value=defense_value, damage_dice=damage_dice)
        return fake_outcome()

    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack", fake_resolve_attack)
    upd = build_combat_resolve_node(repo, module)(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "difficulty": "regular", "target": "thug"}]}))
    assert seen["attack_value"] == 70 and seen["defender"] == "thug"
    assert seen["defense_value"] == 40 and seen["damage_dice"] == "1d4"
    assert upd["npc_hp"] == {"thug": 4}
    entry = upd["combat_log"][0]
    assert entry["npc_id"] == "thug" and entry["name"] == "流氓" and entry["hit"] is True
    assert entry["hp_before"] == 8 and entry["hp_after"] == 4 and entry["damage"] == 4
    assert entry["attack"]["level"] == "hard" and entry["defense"]["success"] is False
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert [r.skill for r in rows] == ["格斗", "闪避"]     # 攻击 + 防御各落一条骰子记录
    assert rows[0].seed == 777 and rows[1].seed == 778
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["combat"])
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload["npc_id"] == "thug" and payload["hp_after"] == 4
    assert "HP 8→4" in payload["text"]


def test_combat_miss_keeps_hp(repo, campaign, monkeypatch):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack",
                        lambda *a, **kw: fake_outcome(hit=False))
    upd = build_combat_resolve_node(repo, module)(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "target": "thug"}]}))
    assert upd["npc_hp"]["thug"] == 8 and upd["combat_log"][0]["hit"] is False
    assert upd["combat_log"][0]["damage"] == 0


def test_combat_hp_floor_at_zero(repo, campaign, monkeypatch):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack",
                        lambda *a, **kw: fake_outcome(damage=99))
    upd = build_combat_resolve_node(repo, module)(base_state(
        campaign, npc_hp={"thug": 3}, decision={"checks": [
            {"actor": "pc_1", "skill": "格斗", "target": "thug"}]}))
    assert upd["npc_hp"]["thug"] == 0 and upd["combat_log"][0]["hp_before"] == 3


def test_combat_skips_dead_noncombat_and_outsiders(repo, campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    node = build_combat_resolve_node(repo, module)     # 全部跳过：resolve_attack 不会被调用
    upd = node(base_state(campaign, npc_hp={"thug": 0}, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "target": "thug"},     # 已败亡
        {"actor": "pc_1", "skill": "格斗", "target": "kid"},      # 无 combat 块
        {"actor": "pc_1", "skill": "格斗", "target": "ghost"},    # 场景外
        {"actor": "pc_1", "skill": "格斗"}]}))                    # 无 target：不归它管
    assert upd["combat_log"] == [] and upd["npc_hp"] == {"thug": 0}
    assert repo.list_dice_records(campaign.id, campaign.active_branch_id) == []


def test_resolve_checks_skips_combat_targets(resolve_node, repo, campaign):
    upd = resolve_node(base_state(campaign, decision={"checks": [
        {"actor": "pc_1", "skill": "格斗", "target": "thug"},
        {"actor": "pc_1", "skill": "侦查", "difficulty": "regular"}]}))
    assert [r["skill"] for r in upd["check_results"]] == ["侦查"]
    assert len(repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)) == 1


def test_validate_normalizes_targets(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client([])
    raw = ('{"intent_summary": "打", "checks": ['
           '{"actor": "pc_1", "skill": "格斗", "target": "thug"},'
           '{"actor": "pc_1", "skill": "格斗", "target": "kid"},'
           '{"actor": "pc_1", "skill": "格斗", "target": "ghost"}]}')
    upd = build_validate_node(client, module)({
        "decision_raw": raw, "scene_id": "yard", "budget_level": "ok",
        "campaign_id": "c", "branch_id": "c@main", "turn_id": 1})
    assert upd["error"] is None
    checks = upd["decision"]["checks"]
    assert checks[0]["target"] == "thug"          # 场景内且有 combat：保留
    assert checks[1]["target"] is None            # 无 combat：降级为普通检定
    assert checks[2]["target"] is None            # 场景外：降级为普通检定
    assert built == {}                            # 合法输入不触发 repair 调用


def test_validate_degrades_dead_target(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client([])
    raw = '{"intent_summary": "打", "checks": [{"actor": "pc_1", "skill": "格斗", "target": "thug"}]}'
    upd = build_validate_node(client, module)({
        "decision_raw": raw, "scene_id": "yard", "npc_hp": {"thug": 0},
        "budget_level": "ok", "campaign_id": "c", "branch_id": "c@main", "turn_id": 1})
    assert upd["decision"]["checks"][0]["target"] is None   # 已败亡：不可再被攻击


def test_narrate_includes_combat_line(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client(["打斗叙事。"])
    build_narrate_node(client, module)(base_state(campaign, combat_log=[
        {"npc_id": "thug", "name": "流氓", "hit": True, "damage": 4,
         "hp_before": 8, "hp_after": 4,
         "attack": {"roll": 22, "skill_value": 70, "level": "hard", "success": True},
         "defense": {"roll": 80, "skill_value": 40, "level": "fail", "success": False}},
        {"npc_id": "thug", "name": "流氓", "hit": True, "damage": 4,
         "hp_before": 4, "hp_after": 0,
         "attack": {"roll": 10, "skill_value": 70, "level": "extreme", "success": True},
         "defense": {"roll": 90, "skill_value": 40, "level": "fail", "success": False}}]))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "战斗结算" in prompt and "流氓" in prompt and "8→4" in prompt
    assert "倒下" in prompt                       # HP 归零：败亡提示


def test_narrate_prompt_unchanged_without_combat(campaign):
    module = Module.model_validate(MODULE_WITH_COMBAT)
    client, built = make_client(["叙事。"])
    build_narrate_node(client, module)(base_state(campaign))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "战斗结算" not in prompt and "NPC 反应" in prompt


def test_graph_routes_combat_and_persists_hp(repo, campaign, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.resolve_attack",
                        lambda *a, **kw: fake_outcome())
    module = Module.model_validate(MODULE_WITH_COMBAT)
    opening_decide = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                      ' "scene_transition": null, "memory_queries": []}')
    attack_decide = ('{"intent_summary": "攻击", "checks": [{"actor": "pc_1", "skill": "格斗",'
                     ' "difficulty": "regular", "target": "thug"}],'
                     ' "proactive_npc_triggers": [], "scene_transition": null,'
                     ' "memory_queries": []}')
    script = {"qwen3.8-flash": [opening_decide, "开场叙事。", attack_decide, "你一拳把流氓打退半步。"]}
    queues = {m: list(v) for m, v in script.items()}

    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    client = LLMClient(Settings(), pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, module, JournalMemory(repo), client,
                             BudgetGuard(Settings()), MemorySaver())
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1,
                                 "inputs": [{"player_id": "p1", "character_id": "pc_1",
                                             "text": "我挥拳打过去"}],
                                 "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["turn_id"] == 2
    snapshot = repo.get_state_at(campaign.id, campaign.active_branch_id, 1)
    assert snapshot["npc_hp"] == {"thug": 4}     # 战斗结果已随 post_turn 落 L2 快照
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["combat"])
    assert len(events) == 1
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert [r.skill for r in rows] == ["格斗", "闪避"]
