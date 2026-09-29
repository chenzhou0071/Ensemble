"""降级路径图级集成测试：预算熔断阶梯 ①②③ 与规格 §8 降级矩阵端到端覆盖。

④（战役熔断）由 test_main_graph 的 test_paused_halts_without_llm 覆盖；
validate repair 失败由 test_validate_failure_falls_back_to_wait 覆盖；
NPC 沉默单元级由 test_npc 覆盖，此处补图级。
"""
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
PLAIN_DECIDE = ('{"intent_summary": "继续", "checks": [], "proactive_npc_triggers": [],'
                ' "scene_transition": null, "memory_queries": []}')
RESUME_TURN1 = Command(resume={"turn_id": 1, "inputs": [
    {"player_id": "p1", "character_id": "pc_1", "text": "我推门进去"}], "skipped": []})


class SpyMemory:
    def __init__(self, inner):
        self.inner = inner
        self.context_budgets: list[int] = []
        self.search_queries: list[str] = []

    def get_context(self, campaign_id, branch_id, budget_chars=1200):
        self.context_budgets.append(budget_chars)
        return self.inner.get_context(campaign_id, branch_id, budget_chars)

    def search(self, campaign_id, branch_id, query, limit=5):
        self.search_queries.append(query)
        return self.inner.search(campaign_id, branch_id, query, limit)

    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.inner.update_summaries(campaign_id, branch_id, turn_id)


def make_env(repo, mini_module, scripts_by_model, memory=None, tokens_per_call=(10, 20),
             **settings_overrides):
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
    graph = build_game_graph(repo, mini_module, memory or JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    return graph, model_calls


def config_for(repo, campaign):
    branch = repo.get_branch(campaign.active_branch_id)
    return {"configurable": {"thread_id": repo.thread_id_for(branch)}}


def init_state(campaign):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 0, "player_inputs": []}


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


def test_tight_downgrades_memory_and_shrinks_npc(repo, campaign):
    """TIGHT：阶梯①记忆降档（600）+ 阶梯②两个在场 trigger 收缩到首位；未到 ③ 不换档。"""
    twin = Module.model_validate(TWIN_MODULE_DICT)  # 同场景双 NPC，才能验证"收缩到首位"
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen3.8-flash",
                      10, 20, 0.8, 100)  # cap=1.0 → 0.8 ∈ [0.7, 1.0) → TIGHT
    tight_decide = ('{"intent_summary": "接近", "checks": [], "proactive_npc_triggers":'
                    ' [{"npc_id": "guard", "trigger": "玩家靠近"}, {"npc_id": "barkeep"}],'
                    ' "scene_transition": null, "memory_queries": ["磨坊"]}')
    spy = SpyMemory(JournalMemory(repo))
    graph, calls = make_env(repo, twin, {
        "qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR, tight_decide, "守卫的目光钉在你身上。"],
        "deepseek-flash": ['{"speech": "站住。", "action": "伸手拦路"}'],
    }, memory=spy, campaign_cost_cap_usd=1.0, cheap_model="alt-cheap-model")
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert spy.context_budgets == [600, 600]      # 阶梯①：记忆降档（开场 + 第 1 回合）
    assert spy.search_queries == []               # 降档后不做检索
    assert calls.count("deepseek-flash") == 1     # 阶梯②：两个 trigger 收缩到首位
    assert "alt-cheap-model" not in calls         # TIGHT 尚未到 ③（cheap 用虚构名可观测）


def test_exceeded_switches_gm_to_cheap_model(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 1, "gm", "qwen3.8-flash",
                      20000, 15000, 0.1, 100)  # 第 1 回合 35000 tokens ≥ 30000 → EXCEEDED
    spy = SpyMemory(JournalMemory(repo))
    graph, calls = make_env(repo, mini_module, {
        "qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR],
        "alt-cheap-model": [PLAIN_DECIDE, "风穿过空荡的街道。"],
    }, memory=spy, cheap_model="alt-cheap-model")
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    calls.clear()  # 只看第 1 回合的模型选择
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["turn_id"] == 2
    assert "qwen3.8-flash" not in calls           # 阶梯③：GM（decide+narrate）全换便宜档
    assert calls.count("alt-cheap-model") == 2    # cheap 用虚构名以验证切换（生产两档同名）
    assert spy.context_budgets == [1200, 600]     # 阶梯①逐级累积：开场 OK 档仍 1200，EXCEEDED 回合 600


def test_resolve_failure_falls_back(repo, campaign, mini_module, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("dice broken")

    monkeypatch.setattr("app.graph.nodes.turn.roll_check", boom)
    check_decide = ('{"intent_summary": "观察", "checks": [{"actor": "pc_1", "skill": "侦查"}],'
                    ' "proactive_npc_triggers": [], "scene_transition": null,'
                    ' "memory_queries": []}')
    graph, calls = make_env(repo, mini_module,
                            {"qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR, check_decide]})
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["error"] == "resolve_failed"   # 纯代码节点兜底（_guarded）
    assert snap.values["degraded"] == {}              # 失败不推进：本轮 pending（含标记）丢弃
    assert snap.values["turn_id"] == 1                # 失败不推进


class BrokenGetContextMemory:
    """get_context/search 故障但 update_summaries 正常：只应降级记忆查询。"""

    def get_context(self, *args, **kwargs):
        raise RuntimeError("memory down")

    def search(self, *args, **kwargs):
        raise RuntimeError("memory down")

    def update_summaries(self, campaign_id, branch_id, turn_id):
        pass


def test_memory_failure_continues_turn(repo, campaign, mini_module):
    graph, calls = make_env(repo, mini_module, {
        "qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR, PLAIN_DECIDE, "你环顾四周，一切如常。"],
    }, memory=BrokenGetContextMemory())
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2                # 回合推进（记忆是增强非阻塞）
    assert snap.values["degraded"]["memory_query"] is True
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "narration" in types


def test_silent_npc_still_narrates(repo, campaign, mini_module):
    trigger_decide = ('{"intent_summary": "与守卫交涉", "checks": [],'
                      ' "proactive_npc_triggers": [{"npc_id": "guard",'
                      ' "trigger": "玩家试图进城"}], "scene_transition": null,'
                      ' "memory_queries": []}')
    graph, calls = make_env(repo, mini_module, {
        "qwen3.8-flash": [OPENING_DECIDE, OPENING_NARR, trigger_decide, "守卫只是沉默地看着你。"],
        "deepseek-flash": [],   # 脚本耗尽 → NPC 调用抛异常 → 静默占位
    })
    cfg = config_for(repo, campaign)
    graph.invoke(init_state(campaign), cfg)
    graph.invoke(RESUME_TURN1, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2
    assert snap.values["npc_reactions"]["guard"]["speech"] == ""  # 沉默占位
    assert snap.values["error"] is None                           # 其余流程正常
