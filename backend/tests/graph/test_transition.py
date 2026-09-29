from app.graph.nodes.turn import build_apply_transition_node


def state_dict(**extra):
    return {"campaign_id": "c1", "branch_id": "c1@main", "turn_id": 1,
            "scene_id": "gate", "decision": {}, **extra}


def test_transition_applies_for_adjacent_scene(mini_module):
    node = build_apply_transition_node(mini_module)
    upd = node(state_dict(decision={"scene_transition": {"to_scene": "tavern", "reason": "推门"}}))
    assert upd == {"scene_id": "tavern"}


def test_transition_ignored_for_non_adjacent_scene(mini_module):
    node = build_apply_transition_node(mini_module)
    assert node(state_dict(decision={"scene_transition": {"to_scene": "mill", "reason": "跳墙"}})) == {}
    assert node(state_dict(decision={"scene_transition": {"to_scene": "ghost_scene"}})) == {}


def test_transition_noop_without_transition(mini_module):
    node = build_apply_transition_node(mini_module)
    assert node(state_dict()) == {}
    assert node(state_dict(decision=None)) == {}
