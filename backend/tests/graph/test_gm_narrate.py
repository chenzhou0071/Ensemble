from app.config import Pricing, PricingEntry, Settings
from app.graph.nodes.gm import build_narrate_node
from app.llm.client import LLMClient

def make_client(script):
    # gm 用真名；cheap 用虚构名以区分"超限切换"路由（生产两档同名，见 config.py）
    settings = Settings(gm_model="qwen3.8-flash", cheap_model="alt-cheap-model")
    pricing = Pricing(models={
        "qwen3.8-flash": PricingEntry(input_per_1k=0.0008, output_per_1k=0.002),
        "alt-cheap-model": PricingEntry(input_per_1k=0.0003, output_per_1k=0.0006),
    })
    built: dict = {}

    def factory(model, base_url, api_key):
        from app.llm.fakes import FakeLLM
        if model not in built:  # 同一模型复用同一实例，保证多轮调用按剧本推进
            built[model] = FakeLLM(list(script))
        return built[model]

    return LLMClient(settings, pricing, model_factory=factory), built

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "scene_id": "gate", "is_opening": False,
            "characters": {"pc_1": {"id": "pc_1", "name": "调查员",
                                    "skills": {"侦查": 50}, "attributes": {"力量": 60}}},
            "player_inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我想进城"}],
            "check_results": [{"actor": "pc_1", "skill": "侦查", "roll": 73,
                               "skill_value": 50, "level": "fail", "success": False, "seed": 1}],
            "npc_reactions": {"guard": {"npc_id": "guard", "speech": "站住！", "action": "伸手拦路"},
                              "barkeep": {"npc_id": "barkeep", "speech": "", "action": None}},
            "memory_context": "", "budget_level": "ok", **extra}

def test_narrate_returns_ordered_segments(campaign, mini_module):
    client, built = make_client(["你推开门。[[npc:guard]]站住！[[/npc]]他警惕地盯着你。"])
    upd = build_narrate_node(client, mini_module)(base_state(campaign))
    assert [s["speaker"] for s in upd["narration_segments"]] == ["gm", "npc:guard", "gm"]
    assert upd["error"] is None

def test_prompt_contains_material_and_filters_silent_npc(campaign, mini_module):
    client, built = make_client(["有效叙事。"])
    build_narrate_node(client, mini_module)(base_state(campaign))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "村口" in prompt and "侦查" in prompt and "73/50" in prompt
    assert "站住！" in prompt and "王守卫" in prompt
    assert "调查员" in prompt and "pc_1" not in prompt  # 用角色名，不泄漏内部 id
    assert "barkeep" not in prompt  # 沉默占位被过滤

def test_empty_output_retries_once(campaign, mini_module):
    client, built = make_client(["", "补上的有效叙事。"])
    upd = build_narrate_node(client, mini_module)(base_state(campaign))
    assert upd["narration"] == "补上的有效叙事。" and upd["error"] is None
    assert len(built["qwen3.8-flash"].calls) == 2

def test_gives_up_after_one_repair(campaign, mini_module):
    client, built = make_client(["", "   "])
    upd = build_narrate_node(client, mini_module)(base_state(campaign))
    assert upd["error"] == "narrate_failed"
    assert upd["degraded"] == {"narrate_failed": True}
    assert upd["narration"] == "" and upd["narration_segments"] == []
    assert len(built["qwen3.8-flash"].calls) == 2

def test_opening_embeds_opening_narration(campaign, mini_module):
    client, built = make_client(["开场叙事。"])
    build_narrate_node(client, mini_module)(base_state(campaign, is_opening=True, player_inputs=[]))
    prompt = built["qwen3.8-flash"].calls[0][1].content
    assert "开场叙述" in prompt  # mini_module.opening.narration

def test_cheap_model_when_exceeded(campaign, mini_module):
    client, built = make_client(["开场叙事。"])
    build_narrate_node(client, mini_module)(base_state(campaign, budget_level="exceeded"))
    assert "alt-cheap-model" in built and "qwen3.8-flash" not in built
