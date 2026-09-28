from app.config import Settings
from app.graph.nodes.turn import build_intake_node
from app.llm.usage import BudgetGuard

def make_node(repo, module, **overrides):
    guard = BudgetGuard(Settings(**overrides))
    return build_intake_node(repo, module, guard)

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 0, "player_inputs": [], **extra}

def test_opening_uses_module_defaults(repo, campaign, mini_module):
    upd = make_node(repo, mini_module)(base_state(campaign))
    assert upd["is_opening"] is True
    assert upd["scene_id"] == "gate"
    assert upd["npc_attitudes"]["guard"] == 40
    assert upd["budget_level"] == "ok" and upd["error"] is None

def test_uses_latest_l2_snapshot(repo, campaign, mini_module):
    b = campaign.active_branch_id
    repo.append_state(campaign.id, b, 2, {"scene_id": "tavern", "npc_attitudes": {"guard": 10}})
    upd = make_node(repo, mini_module)(base_state(campaign, turn_id=3, player_inputs=[{"text": "继续"}]))
    assert upd["scene_id"] == "tavern" and upd["npc_attitudes"]["guard"] == 10

def test_writes_turn_start_event(repo, campaign, mini_module):
    make_node(repo, mini_module)(base_state(campaign))
    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert "turn_start" in types

def test_paused_when_campaign_cost_cap_reached(repo, campaign, mini_module):
    repo.record_usage(campaign.id, campaign.active_branch_id, 0, "gm", "qwen-plus", 1, 1, 5.0, 100)
    upd = make_node(repo, mini_module, campaign_cost_cap_usd=1.0)(base_state(campaign))
    assert upd["budget_level"] == "paused" and upd["error"] == "budget_paused"
