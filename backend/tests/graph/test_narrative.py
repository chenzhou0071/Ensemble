from app.graph.narrative import parse_segments

def test_plain_text_is_single_gm_segment():
    segs = parse_segments("你推开门，灰尘扑面而来。")
    assert len(segs) == 1 and segs[0].speaker == "gm"

def test_marker_produces_ordered_segments():
    text = "你推开门。[[npc:guard]]站住！[[/npc]]他的眼神充满怀疑。"
    segs = parse_segments(text)
    assert [s.speaker for s in segs] == ["gm", "npc:guard", "gm"]
    assert segs[1].text == "站住！"

def test_multiple_npc_markers_and_empty_text():
    segs = parse_segments("[[npc:a]]一[[/npc]]中间[[npc:b]]二[[/npc]]")
    assert [s.speaker for s in segs] == ["npc:a", "gm", "npc:b"]
    assert parse_segments("   ") == []
