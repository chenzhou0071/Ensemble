"""模组静态可达性校验：坏模组必须在加载期暴露，而不是跑到一半炸。"""
from collections import deque

from app.content.schema import Module


def _duplicates(ids: list[str]) -> list[str]:
    seen, dup = set(), []
    for i in ids:
        if i in seen:
            dup.append(i)
        else:
            seen.add(i)
    return dup


def validate_module(module: Module) -> list[str]:
    issues: list[str] = []

    for kind, ids in [("scene", [s.id for s in module.scenes]),
                      ("npc", [n.id for n in module.npcs]),
                      ("clue", [c.id for c in module.clues]),
                      ("ending", [e.id for e in module.endings])]:
        for dup in _duplicates(ids):
            issues.append(f"duplicate {kind} id: {dup}")

    scene_ids = {s.id for s in module.scenes}
    npc_ids = {n.id for n in module.npcs}
    clue_ids = {c.id for c in module.clues}

    if module.opening.scene_id not in scene_ids:
        issues.append(f"opening scene not found: {module.opening.scene_id}")

    for s in module.scenes:
        for ex in s.exits:
            if ex not in scene_ids:
                issues.append(f"scene {s.id}: exit target not found: {ex}")
        for n in s.npcs:
            if n not in npc_ids:
                issues.append(f"scene {s.id}: scene npc not found: {n}")
        for c in s.clues:
            if c not in clue_ids:
                issues.append(f"scene {s.id}: scene clue not found: {c}")

    for c in module.clues:
        for u in c.unlocks:
            prefix, _, target = u.partition(":")
            if prefix not in ("scene", "clue") or not target:
                issues.append(f"clue {c.id}: bad unlock format: {u}")
            elif (prefix == "scene" and target not in scene_ids) or \
                 (prefix == "clue" and target not in clue_ids):
                issues.append(f"clue {c.id}: unlock target not found: {u}")

    if module.opening.scene_id in scene_ids:
        reachable, queue = {module.opening.scene_id}, deque([module.opening.scene_id])
        by_id = {s.id: s for s in module.scenes}
        while queue:
            cur = queue.popleft()
            for ex in by_id[cur].exits:
                if ex in by_id and ex not in reachable:
                    reachable.add(ex)
                    queue.append(ex)
        for sid in sorted(scene_ids - reachable):
            issues.append(f"unreachable scene: {sid}")
        for e in module.endings:
            if e.scene not in scene_ids:
                issues.append(f"ending {e.id}: ending scene not found: {e.scene}")
            elif e.scene not in reachable:
                issues.append(f"ending {e.id}: ending scene unreachable: {e.scene}")
    return issues
