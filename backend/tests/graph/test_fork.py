from dataclasses import asdict

from langgraph.types import Command

from app.config import Pricing, PricingEntry, Settings
from app.graph.fork import fork_thread
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient
from app.llm.fakes import FakeLLM
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

OPENING = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
           ' "scene_transition": null, "memory_queries": []}')
TRIGGER = ('{"intent_summary": "问守卫", "checks": [],'
           ' "proactive_npc_triggers": [{"npc_id": "guard", "trigger": "玩家搭话"}],'
           ' "scene_transition": null, "memory_queries": []}')
PLAIN = ('{"intent_summary": "继续", "checks": [], "proactive_npc_triggers": [],'
         ' "scene_transition": null, "memory_queries": []}')
GUARD_REPLY = '{"speech": "别乱走。", "action": "按着枪套"}'


def _env(tmp_path, script):
    db = str(tmp_path / "fork.db")
    engine = make_engine(db)
    init_db(engine)
    repo = SqliteRepository(engine)
    campaign = repo.create_campaign("mini", "分叉测试")
    char = make_default_character("p1", "调查员")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    queues = {m: list(v) for m, v in script.items()}

    def factory(model, base_url, api_key):
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "deepseek-flash": PricingEntry(input_per_1k=0.00027, output_per_1k=0.0011)})
    settings = Settings(sqlite_path=db)
    client = LLMClient(settings, pricing, usage_sink=repo, model_factory=factory)
    graph = build_game_graph(repo, _mini(), JournalMemory(repo), client,
                             BudgetGuard(settings), build_checkpointer(db))
    return db, repo, campaign, graph, settings


def _mini():
    from app.content.schema import Module
    return Module.model_validate({
        "meta": {"id": "mini", "title": "迷你"},
        "opening": {"narration": "开场叙述", "scene_id": "gate"},
        "scenes": [{"id": "gate", "name": "村口", "npcs": ["guard"], "exits": []}],
        "npcs": [{"id": "guard", "name": "王守卫", "persona": "多疑的老兵",
                  "initial_attitude": 40}],
        "clues": [],
        "endings": [{"id": "e1", "scene": "gate", "condition": "真相大白"}]})


def test_fork_copies_chain_and_strands_at_boundary(tmp_path):
    db, repo, campaign, graph, settings = _env(tmp_path, {
        "qwen3.8-flash": [OPENING, "开场叙事。", TRIGGER, "守卫的反应。",
                          PLAIN, "新分支叙事。"],
        "deepseek-flash": [GUARD_REPLY]})
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    graph.invoke(Command(resume={"turn_id": 1,
                                 "inputs": [{"player_id": "p1", "character_id": "pc_p1",
                                             "text": "跟守卫搭话"}], "skipped": []}), cfg)
    assert graph.get_state(cfg).values["turn_id"] == 2   # 已完成 turn 0 与 turn 1

    dst = f"{campaign.id}@rollback"
    fork_thread(db, campaign.active_branch_id, dst, upto_turn=1)

    snap = graph.get_state({"configurable": {"thread_id": dst}})
    assert snap.next == ("wait_input",)                  # 复制的挂起点生效
    assert snap.values["turn_id"] == 2                   # = upto_turn + 1
    # 目标 thread 可继续推进
    result = graph.invoke(Command(resume={"turn_id": 2,
                                          "inputs": [{"player_id": "p1",
                                                      "character_id": "pc_p1",
                                                      "text": "新分支行动"}],
                                          "skipped": []},
                                  update={"branch_id": dst}),
                          {"configurable": {"thread_id": dst}})
    assert result.get("__interrupt__"), "fork 后可继续回合"
    assert result["turn_id"] == 3                        # 新回合完整跑完


def test_fork_missing_boundary_raises(tmp_path):
    import pytest
    db, repo, campaign, graph, settings = _env(tmp_path, {"qwen3.8-flash": [OPENING, "开场。"]})
    cfg = {"configurable": {"thread_id": campaign.active_branch_id}}
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    with pytest.raises(ValueError):
        fork_thread(db, campaign.active_branch_id, f"{campaign.id}@x", upto_turn=5)
