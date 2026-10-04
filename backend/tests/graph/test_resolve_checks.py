import pytest
from app.graph.nodes.turn import build_resolve_checks_node

@pytest.fixture
def node(repo, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: 123)
    return build_resolve_checks_node(repo)

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 1, "characters": {"pc_1": {"id": "pc_1", "skills": {"侦查": 50},
                                                  "attributes": {"力量": 60}}},
            "decision": {"checks": [{"actor": "pc_1", "skill": "侦查", "difficulty": "regular"},
                                    {"actor": "pc_1", "skill": "力量", "difficulty": "hard"}]},
            **extra}

def test_rolls_each_check_persists_dice_and_events(node, repo, campaign):
    upd = node(base_state(campaign))
    results = upd["check_results"]
    assert len(results) == 2
    assert results[0]["actor"] == "pc_1" and 1 <= results[0]["roll"] <= 100
    assert all(r["seed"] == 123 for r in results)
    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 2 and rows[0].seed == 123
    assert len(repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])) == 2

def test_no_checks_returns_empty(node, campaign):
    upd = node(base_state(campaign, decision={"checks": []}))
    assert upd["check_results"] == []

def test_missing_character_yields_zero_skill(node, repo, campaign):
    upd = node(base_state(campaign, decision={"checks": [{"actor": "ghost", "skill": "侦查"}]},
                          characters={}))
    assert upd["check_results"][0]["skill_value"] == 0


def test_ending_cleared_when_check_fails(repo, campaign, monkeypatch):
    """结局动作的检定失败 → 本回合不收束（清掉结局标记，随失败叙事继续）。"""
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: 42)  # roll=82 必失败
    node = build_resolve_checks_node(repo)
    upd = node(base_state(campaign, decision={
        "checks": [{"actor": "pc_1", "skill": "侦查", "difficulty": "regular"}],
        "ending_reached": "ed"}))
    assert upd["check_results"][0]["success"] is False
    assert upd["decision"]["ending_reached"] is None
    assert upd["decision"]["checks"]        # 其余裁决字段保留


def test_ending_kept_when_checks_succeed(node, campaign):
    """检定成功 → 结局标记保留（收束交由后续路由，不被清除）。"""
    state = base_state(campaign, decision={
        "checks": [{"actor": "pc_1", "skill": "侦查", "difficulty": "regular"}],
        "ending_reached": "ed"})
    upd = node(state)
    assert upd["check_results"][0]["success"] is True
    decision = upd.get("decision", state["decision"])   # 未改写即沿用原裁决
    assert decision["ending_reached"] == "ed"
