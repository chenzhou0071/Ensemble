from app.api.turn_buffer import TurnBuffer


def entry(p, text):
    return {"player_id": p, "character_id": f"pc_{p}", "text": text,
            "submitted_at": ""}


def test_single_player_debounce_then_close():
    buf = TurnBuffer(single_player_debounce_seconds=2.0)
    epoch = buf.open(1, ["p1"], now=100.0)
    assert epoch == 1 and buf.phase == "collecting"
    assert buf.submit("p1", entry("p1", "进门"), now=101.0) == "accepted"
    assert not buf.should_close(now=102.5, window_started=100.0)   # 防抖未满 2 秒
    assert buf.should_close(now=103.0, window_started=100.0)
    payload = buf.close()
    assert payload["turn_id"] == 1 and payload["skipped"] == []
    assert payload["inputs"][0]["text"] == "进门"
    assert buf.phase == "idle"


def test_single_player_never_times_out_without_submission():
    """单人：未提交时永不超时（挂机等待输入，不自动空跑消耗）；多人仍按窗口超时推进。"""
    buf = TurnBuffer(window_seconds=60.0)
    buf.open(1, ["p1"], now=100.0)
    assert not buf.should_close(now=1000.0, window_started=100.0)
    assert not buf.should_close(now=100000.0, window_started=100.0)
    assert buf.phase == "collecting"


def test_resubmit_overwrites_before_close():
    buf = TurnBuffer(single_player_debounce_seconds=0.0)
    buf.open(1, ["p1"], now=0.0)
    buf.submit("p1", entry("p1", "第一次"), now=1.0)
    buf.submit("p1", entry("p1", "改主意了"), now=2.0)
    payload = buf.close()
    assert [i["text"] for i in payload["inputs"]] == ["改主意了"]


def test_timeout_records_skipped():
    buf = TurnBuffer(window_seconds=60.0)
    buf.open(3, ["p1", "p2"], now=100.0)
    buf.submit("p1", entry("p1", "我上"), now=101.0)
    assert not buf.should_close(now=150.0, window_started=100.0)
    assert buf.should_close(now=160.0, window_started=100.0)
    assert buf.close()["skipped"] == ["p2"]


def test_multi_player_all_submitted_closes_immediately():
    buf = TurnBuffer(window_seconds=60.0)
    buf.open(1, ["p1", "p2"], now=0.0)
    buf.submit("p1", entry("p1", "a"), now=1.0)
    assert not buf.should_close(now=1.0, window_started=0.0)
    buf.submit("p2", entry("p2", "b"), now=2.0)
    assert buf.should_close(now=2.0, window_started=0.0)   # 多人：齐全即收，无防抖


def test_submit_between_windows_deferred_to_next():
    buf = TurnBuffer()
    buf.open(1, ["p1"], now=0.0)
    buf.submit("p1", entry("p1", "第一回合"), now=1.0)
    buf.close()
    assert buf.submit("p1", entry("p1", "抢在下一轮前"), now=5.0) == "deferred"
    buf.open(2, ["p1"], now=6.0)
    payload = buf.close()
    assert payload["turn_id"] == 2
    assert [i["text"] for i in payload["inputs"]] == ["抢在下一轮前"]


def test_unknown_player_ignored():
    buf = TurnBuffer()
    buf.open(1, ["p1"], now=0.0)
    assert buf.submit("ghost", entry("ghost", "x"), now=1.0) == "ignored"
    assert buf.close()["skipped"] == ["p1"]


def test_epoch_bumps_on_open_and_close():
    buf = TurnBuffer()
    e1 = buf.open(1, ["p1"], now=0.0)
    buf.close()
    e2 = buf.open(2, ["p1"], now=10.0)
    assert e2 == e1 + 2      # close 与 open 各 +1，旧定时器据此退出
