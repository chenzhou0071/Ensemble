from app.rules.attitude import (ATTITUDE_MAX, ATTITUDE_MIN, MAX_DELTA_ABS,
                                apply_attitude_deltas)


def item(npc_id, delta, reason=""):
    return {"npc_id": npc_id, "delta": delta, "reason": reason}


def test_present_only_and_keeps_input_intact():
    current = {"guard": 40, "barkeep": 60}
    attitudes, changes = apply_attitude_deltas(
        current, [item("guard", -10, "被威胁"), item("ghost", 5)], {"guard", "barkeep"})
    assert attitudes["guard"] == 30 and attitudes["barkeep"] == 60
    assert current == {"guard": 40, "barkeep": 60}          # 不修改入参
    assert changes == [{"npc_id": "guard", "old": 40, "new": 30,
                        "delta": -10, "reason": "被威胁"}]


def test_slice_first_two_before_filtering():
    # 先保序取前 2 条再逐条过滤：非法的第 1 条占掉一个名额（写死语义）
    attitudes, changes = apply_attitude_deltas(
        {"a": 50, "b": 50, "c": 50},
        [item("ghost", 5), item("a", 5), item("b", 5), item("c", 5)], {"a", "b", "c"})
    assert [c["npc_id"] for c in changes] == ["a"]


def test_non_int_delta_dropped():
    for bad in (True, 3.5, "5", None):
        attitudes, changes = apply_attitude_deltas({"a": 50}, [item("a", bad)], {"a"})
        assert changes == [] and attitudes == {"a": 50}


def test_non_dict_item_skipped():
    attitudes, changes = apply_attitude_deltas({"a": 50}, [None, item("a", 5)], {"a"})
    assert attitudes["a"] == 55 and len(changes) == 1


def test_single_delta_truncated_then_merged_net_truncated():
    attitudes, changes = apply_attitude_deltas({"a": 50}, [item("a", 100)], {"a"})
    assert attitudes["a"] == 50 + MAX_DELTA_ABS and changes[0]["delta"] == MAX_DELTA_ABS
    attitudes, changes = apply_attitude_deltas(      # 合并 10+10=20 → 净再截断为 15
        {"a": 50}, [item("a", 10), item("a", 10)], {"a"})
    assert attitudes["a"] == 50 + MAX_DELTA_ABS and changes[0]["delta"] == MAX_DELTA_ABS


def test_same_npc_merges_and_keeps_first_reason():
    attitudes, changes = apply_attitude_deltas(
        {"a": 50}, [item("a", 5, "甲"), item("a", -2, "乙")], {"a"})
    assert attitudes["a"] == 53 and len(changes) == 1
    assert changes[0]["reason"] == "甲"


def test_clamped_to_bounds_delta_records_truncated_net():
    attitudes, changes = apply_attitude_deltas({"a": 95}, [item("a", 15)], {"a"})
    assert attitudes["a"] == ATTITUDE_MAX and changes[0]["delta"] == MAX_DELTA_ABS
    attitudes, changes = apply_attitude_deltas({"a": 5}, [item("a", -15)], {"a"})
    assert attitudes["a"] == ATTITUDE_MIN


def test_net_zero_or_no_actual_change_records_nothing():
    attitudes, changes = apply_attitude_deltas(
        {"a": 50}, [item("a", 5), item("a", -5)], {"a"})   # 净 0
    assert changes == [] and attitudes == {"a": 50}
    attitudes, changes = apply_attitude_deltas({"a": 100}, [item("a", 15)], {"a"})  # 卡边
    assert changes == [] and attitudes == {"a": 100}


def test_missing_attitude_defaults_to_50():
    attitudes, changes = apply_attitude_deltas({}, [item("a", 10)], {"a"})
    assert attitudes["a"] == 60 and changes[0]["old"] == 50


def test_non_list_deltas_treated_as_empty():
    attitudes, changes = apply_attitude_deltas({"a": 50}, None, {"a"})
    assert (attitudes, changes) == ({"a": 50}, [])
