from dataclasses import asdict

from langgraph.checkpoint.memory import MemorySaver

from app.cli import AppContext, play_loop, render_narration, run_play
from app.config import Pricing, PricingEntry, Settings
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient, make_repo_budget_probe
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.character import make_default_character

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
OPENING_NARR = "雾气贴着地面爬行。村口的老树在风里摇晃。"
PLAIN_DECIDE = ('{"intent_summary": "继续", "checks": [], "proactive_npc_triggers": [],'
                ' "scene_transition": null, "memory_queries": []}')


def make_pricing():
    return Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.000113, output_per_1k=0.00038),
        "deepseek-flash": PricingEntry(input_per_1k=0.00028, output_per_1k=0.00113)})


def make_env(repo, mini_module, scripts_by_model, checkpointer=None, settings=None):
    settings = settings or Settings()
    queues = {m: list(v) for m, v in scripts_by_model.items()}
    model_calls: list[str] = []

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        model_calls.append(model)
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    client = LLMClient(settings, make_pricing(), usage_sink=repo, model_factory=factory,
                       budget_probe=make_repo_budget_probe(repo, BudgetGuard(settings)))
    graph = build_game_graph(repo, mini_module, JournalMemory(repo), client,
                             BudgetGuard(settings), checkpointer or MemorySaver())
    return graph, model_calls


def config_for(repo, campaign):
    branch = repo.get_branch(campaign.active_branch_id)
    return {"configurable": {"thread_id": repo.thread_id_for(branch)}}


def test_render_narration_marks_speakers(mini_module):
    segments = [{"speaker": "gm", "text": "风起了。"},
                {"speaker": "npc:guard", "text": "站住！"}]
    assert render_narration(segments, mini_module) == ["风起了。", "【王守卫】站住！"]


def test_play_loop_runs_turn_then_quits(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module, {"qwen3.8-flash": [
        OPENING_DECIDE, OPENING_NARR, PLAIN_DECIDE, "你推门进去，灯影摇晃。"]})
    cfg = config_for(repo, campaign)
    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    turn_id = graph.get_state(cfg).tasks[0].interrupts[0].value["turn_id"]

    inputs = iter(["我推门进去", "退出"])
    lines: list[str] = []
    code = play_loop(graph, cfg, mini_module, turn_id, lambda _: next(inputs), lines.append)
    assert code == "quit"
    assert any("灯影摇晃" in line for line in lines)      # 第二回合叙事已渲染
    assert graph.get_state(cfg).values["turn_id"] == 2


def test_run_play_reports_paused(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen3.8-flash",
                      1, 1, 5.0, 100)                     # 成本 5.0 > 显式上限 2.0 → 战役熔断
    graph, calls = make_env(repo, mini_module, {},
                            settings=Settings(campaign_cost_cap_usd=2.0))        # 不应发生任何 LLM 调用
    lines: list[str] = []
    ctx = AppContext(settings=Settings(), repo=repo, module=mini_module, client=None,
                     guard=None, memory=None, graph=graph)
    code = run_play(ctx, campaign.id, input_fn=lambda _: "x", print_fn=lines.append)
    assert code == "paused"
    assert any("预算" in line for line in lines)
    assert calls == []


def test_resume_after_budget_pause(repo, campaign, mini_module):
    """熔断暂停后调高上限，重跑同一战役可续（规格 §9：手动恢复或调高预算）。"""
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen3.8-flash",
                      1, 1, 5.0, 100)                     # 成本 5.0 > 上限 2.0 → 熔断
    saver = MemorySaver()
    graph1, calls1 = make_env(repo, mini_module, {}, checkpointer=saver,
                              settings=Settings(campaign_cost_cap_usd=2.0))
    lines1: list[str] = []
    ctx1 = AppContext(settings=Settings(campaign_cost_cap_usd=2.0), repo=repo,
                      module=mini_module, client=None, guard=None, memory=None,
                      graph=graph1)
    assert run_play(ctx1, campaign.id, input_fn=lambda _: "x", print_fn=lines1.append) == "paused"
    assert any("预算" in line for line in lines1) and calls1 == []

    # 调高上限重建（模拟改配置后的新进程；同一存档）
    graph2, calls2 = make_env(repo, mini_module, {"qwen3.8-flash": [
        OPENING_DECIDE, OPENING_NARR, PLAIN_DECIDE, "灯影摇晃，走廊尽头传来脚步声。"]},
        checkpointer=saver, settings=Settings(campaign_cost_cap_usd=10.0))
    lines2: list[str] = []
    inputs = iter(["我推门进去", "退出"])
    ctx2 = AppContext(settings=Settings(campaign_cost_cap_usd=10.0), repo=repo,
                      module=mini_module, client=None, guard=None, memory=None,
                      graph=graph2)
    code = run_play(ctx2, campaign.id, input_fn=lambda _: next(inputs), print_fn=lines2.append)
    assert code == "quit"
    assert any("暂停" in line for line in lines2)         # 识别出暂停存档并恢复
    assert any("雾气" in line for line in lines2)         # 挂起的开场补跑并渲染
    assert graph2.get_state(config_for(repo, campaign)).values["turn_id"] == 2


def test_resume_after_process_restart(tmp_path, mini_module):
    """M2 出口标准：模拟进程重启（新连接 + 新图），断点续玩成立。"""
    from app.storage.db import init_db, make_engine
    from app.storage.repo import SqliteRepository

    db = str(tmp_path / "ensemble.db")
    settings = Settings(sqlite_path=db)
    scripts = {"qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR, PLAIN_DECIDE,
                             "灯影摇晃，走廊尽头传来脚步声。"]}
    queues = {m: list(v) for m, v in scripts.items()}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        items = queues.get(model, [])
        return FakeLLM([items.pop(0)] if items else [])

    # ---- 第一次“进程”：建局 + 跑开场，随后模拟退出 ----
    engine1 = make_engine(db)
    init_db(engine1)
    repo1 = SqliteRepository(engine1)
    campaign = repo1.create_campaign(mini_module.meta.id, "续玩测试")
    char = make_default_character("p1", "调查员")
    repo1.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    client1 = LLMClient(settings, make_pricing(), usage_sink=repo1, model_factory=factory,
                        budget_probe=make_repo_budget_probe(repo1, BudgetGuard(settings)))
    graph1 = build_game_graph(repo1, mini_module, JournalMemory(repo1), client1,
                              BudgetGuard(settings), build_checkpointer(db))
    cfg = {"configurable": {
        "thread_id": repo1.thread_id_for(repo1.get_branch(campaign.active_branch_id))}}
    graph1.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                   "turn_id": 0, "player_inputs": []}, cfg)
    assert graph1.get_state(cfg).next == ("wait_input",)

    # ---- 第二次“进程”：全新连接与图，续玩 ----
    engine2 = make_engine(db)
    init_db(engine2)
    repo2 = SqliteRepository(engine2)
    client2 = LLMClient(settings, make_pricing(), usage_sink=repo2, model_factory=factory,
                        budget_probe=make_repo_budget_probe(repo2, BudgetGuard(settings)))
    graph2 = build_game_graph(repo2, mini_module, JournalMemory(repo2), client2,
                              BudgetGuard(settings), build_checkpointer(db))
    snap = graph2.get_state(cfg)
    assert snap.next == ("wait_input",)                   # 挂起状态被恢复
    ctx2 = AppContext(settings=settings, repo=repo2, module=mini_module, client=client2,
                      guard=BudgetGuard(settings), memory=JournalMemory(repo2), graph=graph2)
    inputs = iter(["我推门进去", "退出"])
    lines: list[str] = []
    code = run_play(ctx2, campaign.id, input_fn=lambda _: next(inputs), print_fn=lines.append)
    assert code == "quit"
    assert any("读取存档" in line for line in lines)       # 走了断点续玩分支
    assert graph2.get_state(cfg).values["turn_id"] == 2   # 新进程成功推进了一个回合
