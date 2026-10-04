from app.config import Pricing, PricingEntry, Settings
from app.content.schema import Module
from app.graph.nodes.gm import DECIDE_SYSTEM, build_decide_node, build_validate_node
from app.llm.client import LLMClient, LlmContext

CTX_KEYS = ("campaign_id", "branch_id", "turn_id")

def make_client(script):
    # gm 用真名；cheap 用虚构名以区分"超限切换"路由（生产两档同名，见 config.py）
    settings = Settings(gm_model="qwen3.8-flash", cheap_model="alt-cheap-model")
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "alt-cheap-model": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    sink_rows = []
    built: dict = {}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        built[model] = FakeLLM(list(script))
        return built[model]

    class Sink:
        def record_usage(self, campaign_id, branch_id, turn_id, role, model,
                         tokens_in, tokens_out, cost_usd, latency_ms):
            sink_rows.append({"campaign_id": campaign_id, "branch_id": branch_id,
                              "turn_id": turn_id, "role": role, "model": model,
                              "tokens_in": tokens_in, "tokens_out": tokens_out,
                              "cost_usd": cost_usd, "latency_ms": latency_ms})

    return LLMClient(settings, pricing, usage_sink=Sink(), model_factory=factory), built, sink_rows

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "scene_id": "gate", "npc_attitudes": {"guard": 40},
            "characters": {"pc_1": {"id": "pc_1", "name": "调查员",
                                    "skills": {"侦查": 50}, "attributes": {"力量": 60}}},
            "player_inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我想进城"}],
            "memory_context": "前情摘要：村庄不安宁", "budget_level": "ok", **extra}

def test_decide_builds_context_and_returns_raw(campaign, mini_module):
    client, built, _ = make_client(['{"intent_summary": "进城"}'])
    upd = build_decide_node(client, mini_module)(base_state(campaign))
    assert upd["decision_raw"] == '{"intent_summary": "进城"}'
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "村口" in prompt and "我想进城" in prompt and "王守卫" in prompt and "前情摘要" in prompt
    assert "pc_1" in prompt and "侦查" in prompt  # 角色 id 与技能表进上下文
    assert "tavern" in prompt  # 可去场景出口

def test_decide_switches_to_cheap_model_when_exceeded(campaign, mini_module):
    client, built, rows = make_client(['{"intent_summary": "x"}'])
    build_decide_node(client, mini_module)(base_state(campaign, budget_level="exceeded"))
    assert "alt-cheap-model" in built and rows[0]["model"] == "alt-cheap-model"

def test_validate_parses_fenced_output(campaign):
    client, _, _ = make_client([])
    raw = '```json\n{"intent_summary": "潜入", "checks": [{"actor": "pc_1", "skill": "潜行", "difficulty": "hard"}]}\n```'
    upd = build_validate_node(client)({"decision_raw": raw, "budget_level": "ok"})
    assert upd["decision"]["checks"][0]["skill"] == "潜行" and upd["error"] is None

def test_validate_repairs_once_then_succeeds(campaign):
    client, built, _ = make_client(['{"intent_summary": "修复后的合法输出"}'])
    state = {"decision_raw": "这不是 JSON", "budget_level": "ok",
             "campaign_id": "c", "branch_id": "c@main", "turn_id": 1}
    upd = build_validate_node(client)(state)
    assert upd["decision"]["intent_summary"] == "修复后的合法输出"
    assert len(built["qwen3.8-flash"].calls) == 1
    msgs = built["qwen3.8-flash"].calls[0]
    assert msgs[0].role == "system" and msgs[0].content == DECIDE_SYSTEM  # repair 随行字段要求

def test_validate_gives_up_after_one_repair(campaign):
    client, built, _ = make_client(["还是不是 JSON"])
    state = {"decision_raw": "不是 JSON", "budget_level": "ok",
             "campaign_id": "c", "branch_id": "c@main", "turn_id": 1}
    upd = build_validate_node(client)(state)
    assert upd["error"] == "decision_invalid" and upd["decision"] is None
    assert upd["degraded"] == {"decision_invalid": True}

def test_decide_llm_error_returns_degraded(campaign, mini_module):
    """decide 的 LLM 调用抛异常 → 标记 decide_failed 交由 fallback（规格 §8 统一原则）。"""
    client, _, _ = make_client([])  # 脚本耗尽 → IndexError
    upd = build_decide_node(client, mini_module)(base_state(campaign))
    assert upd["error"] == "decide_failed"
    assert upd["degraded"] == {"decide_failed": True}
    assert upd["decision_raw"] == ""


def test_decide_system_has_fail_forward_rule():
    """社交失败不得让场面停滞（失败前进：可冷淡/回避/暗示，但不能写成拒绝交流）。"""
    assert "不得让场面停滞" in DECIDE_SYSTEM


def test_decide_prompt_lists_ending_conditions(campaign, mini_module):
    """结局清单进 decide 提示词：GM 需知道可收束的结局 id 与条件才能提名。"""
    client, built, _ = make_client(['{"intent_summary": "x"}'])
    build_decide_node(client, mini_module)(base_state(campaign))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "e1" in prompt and "揭开真相" in prompt   # mini_module 结局 id 与条件
    assert "ending_reached" in prompt                 # 与字段说明呼应


def test_decide_prompt_requires_conclusion_on_ending_match(campaign, mini_module):
    """结局硬规则进提示词：命中即须收束，不得新增设定使条件落空（防 LLM 拦回终结动作）。"""
    client, built, _ = make_client(['{"intent_summary": "x"}'])
    build_decide_node(client, mini_module)(base_state(campaign))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "命中即须收束" in prompt
    assert "不得新增设定使条件落空" in prompt
    assert "仍须照填 ending_reached" in prompt   # 带检定的结局动作也要填（按结果由系统裁决）


def test_decide_system_documents_attitude_deltas():
    """好感度契约：LLM 只说方向与理由，数值由代码截断（设计 2026-09-26）。"""
    assert "attitude_deltas" in DECIDE_SYSTEM


CLUE_MODULE = {
    "meta": {"id": "clue_mod", "title": "线索模组"},
    "opening": {"narration": "开场", "scene_id": "gate"},
    "scenes": [{"id": "gate", "name": "村口", "npcs": ["guard"], "exits": ["tavern"],
                "clues": ["c1", "c2"]},
               {"id": "tavern", "name": "酒馆", "npcs": [], "exits": []}],
    "npcs": [{"id": "guard", "name": "王守卫", "persona": "多疑的老兵",
              "initial_attitude": 40}],
    "clues": [{"id": "c1", "content": "壁炉灰里藏着一页烧焦的账册", "unlocks": []},
              {"id": "c2", "content": "门缝里卡着一枚旧铜扣", "unlocks": []}],
    "endings": [],
}


def test_decide_prompt_lists_scene_clues(campaign):
    """线索清单进 decide 提示词：GM 需知道本场景可发现线索的 id 与内容才能提名揭示。"""
    client, built, _ = make_client(['{"intent_summary": "x"}'])
    module = Module.model_validate(CLUE_MODULE)
    build_decide_node(client, module)(base_state(campaign))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "c1" in prompt and "烧焦的账册" in prompt   # 线索 id 与内容
    assert "clues_revealed" in prompt                  # 与字段说明呼应


def test_decide_prompt_separates_revealed_clues(repo, campaign):
    """已揭示线索进「已掌握」块供核对结局前置，不进「可发现」清单（防重复提名）。"""
    client, built, _ = make_client(['{"intent_summary": "x"}'])
    module = Module.model_validate(CLUE_MODULE)
    repo.add_event(campaign.id, campaign.active_branch_id, 1, type="clue",
                   payload={"clue_id": "c1", "text": "…"})
    build_decide_node(client, module, repo)(base_state(campaign))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    known, _, pending = prompt.partition("本场景可发现的线索")
    assert "玩家已掌握的线索" in known and "烧焦的账册" in known
    assert "烧焦的账册" not in pending and "旧铜扣" in pending
