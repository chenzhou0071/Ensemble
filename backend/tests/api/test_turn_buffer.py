from app.api.turn_buffer import TurnBuffer


def entry(p, text):
    return {"player_id": p, "character_id": f"pc_{p}", "text": text,
            "submitted_at": ""}


def test_submit_then_close_yields_payload():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    assert buf.phase == "collecting"
    assert buf.submit("p1", entry("p1", "进门")) == "accepted"
    payload = buf.close()
    assert payload["turn_id"] == 1 and payload["skipped"] == []
    assert payload["inputs"][0]["text"] == "进门"
    assert buf.phase == "idle"


def test_resubmit_overwrites_before_close():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    buf.submit("p1", entry("p1", "第一次"))
    buf.submit("p1", entry("p1", "改主意了"))
    payload = buf.close()
    assert [i["text"] for i in payload["inputs"]] == ["改主意了"]


def test_submit_between_windows_deferred_to_next():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    buf.submit("p1", entry("p1", "第一回合"))
    buf.close()
    assert buf.submit("p1", entry("p1", "抢在下一轮前")) == "deferred"
    buf.open(2, ["p1"])
    payload = buf.close()
    assert payload["turn_id"] == 2
    assert [i["text"] for i in payload["inputs"]] == ["抢在下一轮前"]


def test_unknown_player_ignored():
    buf = TurnBuffer()
    buf.open(1, ["p1"])
    assert buf.submit("ghost", entry("ghost", "x")) == "ignored"
    assert buf.close()["skipped"] == ["p1"]
