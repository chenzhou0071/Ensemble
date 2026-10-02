"""好感度硬边界：纯函数，写死常量；LLM 只说方向与理由，代码决定数值（设计 2026-09-26）。"""
MAX_DELTAS_PER_TURN = 2            # 保序取前 2 条
MAX_DELTA_ABS = 15                 # 单条与净变化双重上限
ATTITUDE_MIN, ATTITUDE_MAX = 0, 100
DEFAULT_ATTITUDE = 50


def _truncate(value: int) -> int:
    return max(-MAX_DELTA_ABS, min(MAX_DELTA_ABS, value))


def apply_attitude_deltas(
    current: dict[str, int],
    deltas: list[dict] | None,     # decision["attitude_deltas"] 原始 JSON
    present_npcs: set[str],        # 当前场景在场 npc_id 集合
) -> tuple[dict[str, int], list[dict]]:
    """返回 (新态度表副本, 变更记录)。纯函数：不抛异常、不修改入参、净 0/无变化不动。

    语义（写死）：保序取前 2 条 → 不在场/非 str npc_id 丢弃 → 非 int delta（含 bool）
    丢弃 → 单条截断到 ±15 → 同 npc 合并求和后净变化再截断 → clamp [0,100] →
    net==0 或 new==old 不更新不记录；记录取该 npc 首条 reason。
    """
    result = dict(current)
    if not isinstance(deltas, list):
        return result, []
    merged: dict[str, int] = {}
    first_reason: dict[str, str] = {}
    for entry in deltas[:MAX_DELTAS_PER_TURN]:
        if not isinstance(entry, dict):
            continue
        npc_id, raw = entry.get("npc_id"), entry.get("delta")
        if not isinstance(npc_id, str) or npc_id not in present_npcs:
            continue
        if isinstance(raw, bool) or not isinstance(raw, int):
            continue
        merged[npc_id] = merged.get(npc_id, 0) + _truncate(raw)
        first_reason.setdefault(npc_id, str(entry.get("reason") or ""))
    changes: list[dict] = []
    for npc_id, net in merged.items():
        net = _truncate(net)
        old = result.get(npc_id, DEFAULT_ATTITUDE)
        new = max(ATTITUDE_MIN, min(ATTITUDE_MAX, old + net))
        if net == 0 or new == old:
            continue
        result[npc_id] = new
        changes.append({"npc_id": npc_id, "old": old, "new": new,
                        "delta": net, "reason": first_reason[npc_id]})
    return result, changes
