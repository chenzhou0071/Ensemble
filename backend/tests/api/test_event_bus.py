import json

from app.api.events import EventBus


def drain(sub):
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


def test_push_assigns_increasing_seq_and_json_roundtrip():
    bus = EventBus()
    e1 = bus.push("token", {"speaker": "gm", "text": "雾气"})
    e2 = bus.push("turn", {"phase": "collecting", "turn_id": 1})
    assert (e1.seq, e2.seq, bus.current_seq) == (1, 2, 2)
    data = json.loads(e2.to_json())
    assert data == {"seq": 2, "type": "turn", "visibility": "all",
                    "payload": {"phase": "collecting", "turn_id": 1}}


def test_private_event_only_reaches_target_player():
    bus = EventBus()
    s1 = bus.subscribe("p1")
    s2 = bus.subscribe("p2")
    bus.push("token", {"text": "公开"})
    bus.push("notice", {"message": "秘密"}, visibility="player:p1")
    assert [e.type for e in drain(s1)] == ["token", "notice"]
    assert [e.type for e in drain(s2)] == ["token"]


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    s1 = bus.subscribe("p1")
    bus.unsubscribe(s1)
    bus.push("token", {"text": "x"})
    assert drain(s1) == []


def test_replay_filters_by_player_and_since_seq():
    bus = EventBus()
    bus.push("token", {"text": "1"})
    bus.push("state", {"x": 1}, visibility="player:p2")
    bus.push("token", {"text": "2"})
    events, gap = bus.replay(0, "p1")
    assert [e.seq for e in events] == [1, 3] and gap is False


def test_replay_reports_gap_when_buffer_trimmed():
    bus = EventBus(replay_size=2)
    for i in range(3):
        bus.push("token", {"text": str(i)})
    events, gap = bus.replay(0, "p1")
    assert gap is True
    events2, gap2 = bus.replay(1, "p1")
    assert gap2 is False and [e.seq for e in events2] == [2, 3]
