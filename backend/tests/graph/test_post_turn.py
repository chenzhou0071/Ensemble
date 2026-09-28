import json
from app.graph.nodes.turn import build_post_turn_node, fallback

class SpyMemory:
    def __init__(self):
        self.calls = []
    def update_summaries(self, campaign_id, branch_id, turn_id):
        self.calls.append((campaign_id, branch_id, turn_id))

def base_state(campaign, **extra):
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "turn_id": 2, "scene_id": "tavern", "npc_attitudes": {"guard": 35},
            "narration": "你走进酒馆。[[npc:barkeep]]欢迎光临！[[/npc]]",
            "narration_segments": [{"speaker": "gm", "text": "你走进酒馆。"},
                                   {"speaker": "npc:barkeep", "text": "欢迎光临！"}],
            **extra}

def test_post_turn_persists_and_advances(repo, campaign):
    mem = SpyMemory()
    upd = build_post_turn_node(repo, mem)(base_state(campaign))
    assert upd["turn_id"] == 3 and upd["decision"] is None
    assert mem.calls == [(campaign.id, campaign.active_branch_id, 2)]
    snap = repo.get_state_at(campaign.id, campaign.active_branch_id, 2)
    assert snap["scene_id"] == "tavern" and snap["npc_attitudes"]["guard"] == 35
    events = repo.list_events(campaign.id, campaign.active_branch_id, types=["narration"])
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload["segments"][1]["speaker"] == "npc:barkeep"

def test_fallback_clears_pending_keeps_error():
    upd = fallback({"error": "decision_invalid", "npc_reactions": {"a": {}}, "narration": "x"})
    assert upd["error"] == "decision_invalid"  # error 保留（调用方读取后由 wait_input 清除）
    assert upd["npc_reactions"] == {} and upd["narration"] == "" and upd["check_results"] == []
