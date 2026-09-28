from app.graph.state import merge_dict, TurnInput, TurnInputs

def test_merge_dict_merges_and_clears():
    assert merge_dict({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_dict({"a": 1}, {}) == {}

def test_turn_inputs_roundtrip():
    ti = TurnInputs(turn_id=1,
                    inputs=[TurnInput(player_id="p1", character_id="pc_1", text="我推门进去")],
                    skipped=["p2"])
    data = ti.model_dump()
    assert data["inputs"][0]["text"] == "我推门进去" and data["skipped"] == ["p2"]
