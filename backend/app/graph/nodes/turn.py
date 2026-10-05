"""回合节点：intake / wait_input / resolve_checks / apply_transition / post_turn / fallback。"""
import json

from langgraph.types import interrupt

from app.graph.narrative import stream_writer
from app.graph.state import GameState
from app.memory.base import MemoryEvent
from app.rules.attitude import apply_attitude_deltas
from app.rules.check import CheckDifficulty, roll_check
from app.rules.dice import new_seed


def build_intake_node(repo, module, guard):
    def intake(state: GameState) -> dict:
        campaign_id = state["campaign_id"]
        branch_id = state["branch_id"]
        turn_id = state["turn_id"]
        snap = repo.get_state_at(campaign_id, branch_id, turn_id) or {}
        scene_id = snap.get("scene_id", module.opening.scene_id)
        attitudes = snap.get("npc_attitudes") or {n.id: n.initial_attitude for n in module.npcs}
        chars = {c["id"]: c for c in repo.list_characters_at(campaign_id, branch_id, turn_id)}
        inputs = state.get("player_inputs", [])
        is_opening = turn_id == 0 and not inputs

        turn_tokens = repo.turn_token_total(campaign_id, branch_id, turn_id)
        cost = repo.campaign_cost_total(campaign_id)
        level = str(guard.check(turn_tokens, cost))

        repo.add_event(campaign_id, branch_id, turn_id, type="turn_start",
                       payload={"inputs": [i.get("text", "") for i in inputs],
                                "is_opening": is_opening, "budget_level": level})

        upd: dict = {"scene_id": scene_id, "npc_attitudes": attitudes, "characters": chars,
                     "is_opening": is_opening, "budget_level": level, "error": None}
        if level == "paused":
            upd["error"] = "budget_paused"
        return upd

    return intake


def wait_input(state: GameState) -> dict:
    payload = interrupt({"type": "await_inputs", "turn_id": state.get("turn_id", 0)})
    inputs = payload.get("inputs", []) if isinstance(payload, dict) else []
    return {
        "player_inputs": inputs,
        "is_opening": False,
        # 清空本回合 pending（与"失败不推进/读档重掷"语义一致）
        "decision": None,
        "decision_raw": "",
        "check_results": [],
        "npc_reactions": {},
        "narration": "",
        "narration_segments": [],
        "memory_context": "",
        "error": None,
        "degraded": {},
        "ending_reached": None,
    }


def _skill_value(state: GameState, character_id: str, skill: str) -> int:
    char = state.get("characters", {}).get(character_id)
    if not char:
        return 0
    return char.get("skills", {}).get(skill, char.get("attributes", {}).get(skill, 0))


def build_resolve_checks_node(repo):
    def resolve_checks(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        checks = (state.get("decision") or {}).get("checks", [])
        writer = stream_writer()
        results = []
        for chk in checks:
            actor, skill = chk["actor"], chk["skill"]
            secret = bool(chk.get("secret"))
            skill_value = _skill_value(state, actor, skill)
            seed = new_seed()
            r = roll_check(actor, skill, skill_value,
                           CheckDifficulty(chk.get("difficulty", "regular")), seed)
            rid = repo.add_dice_record(campaign_id, branch_id, turn_id, r.actor, r.skill,
                                       r.skill_value, str(r.difficulty), r.roll, str(r.level),
                                       r.seed, secret=secret)
            # 骰子先出：明骰掷后立即经流式通道推送（先于叙事 token；收口快照按 id 去重兜底）；
            # 暗骰不进实时流——流式通道无法按订阅者过滤，其可见性由收口快照统一兜底
            if not secret:
                writer({"dice": {"id": rid, "actor": r.actor, "skill": r.skill,
                                 "skill_value": r.skill_value, "difficulty": str(r.difficulty),
                                 "roll": r.roll, "level": str(r.level),
                                 "success": r.success, "seed": r.seed}})
            verdict = "成功" if r.success else "失败"
            repo.add_event(campaign_id, branch_id, turn_id, type="check",
                           payload={"text": f"{actor} 的「{skill}」检定：{r.roll}/{r.skill_value} "
                                            f"→ {r.level}（{verdict}）",
                                    "roll": r.roll, "level": str(r.level), "success": r.success,
                                    "secret": secret},
                           visibility="gm" if secret else "all")
            results.append({"actor": r.actor, "skill": r.skill, "roll": r.roll,
                            "skill_value": r.skill_value, "level": str(r.level),
                            "success": r.success, "seed": r.seed,
                            "difficulty": str(r.difficulty), "secret": secret})
        upd: dict = {"check_results": results}
        # 结局动作的检定失败 → 本回合不收束（decide 判定时尚未掷骰，此处按结果纠正，
        # 防"检定失败但结局盲发"；叙事与路由随之按未收束走）
        decision = state.get("decision") or {}
        if decision.get("ending_reached") and any(not r["success"] for r in results):
            upd["decision"] = {**decision, "ending_reached": None}
        return upd

    return resolve_checks


def build_apply_transition_node(module):
    """应用 GM 裁决的场景移动：仅相邻场景生效，越界/无效目标静默忽略。"""

    def apply_transition(state: GameState) -> dict:
        tr = (state.get("decision") or {}).get("scene_transition")
        to_scene = (tr or {}).get("to_scene")
        if not to_scene:
            return {}
        if to_scene not in module.scene(state["scene_id"]).exits:
            return {}
        return {"scene_id": to_scene}

    return apply_transition


def build_post_turn_node(repo, memory, module=None):
    def post_turn(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        narration = state.get("narration", "")
        if narration:
            repo.add_event(campaign_id, branch_id, turn_id, type="narration",
                           payload={"text": narration,
                                    "segments": state.get("narration_segments", [])})
        decision = state.get("decision") or {}
        # 场景移动回合：写 scene_changed 技术事件（持久化 + 供前端切换场景与 NPC 区，§4.3）
        # get_state_at 语义为「≤ turn_id 的最新快照」：本轮快照随后才写入，此刻取到的
        # 正是 intake 读过的回合初始状态（单写者：生产代码仅本节点写快照）
        new_scene = state.get("scene_id")
        old_scene = (repo.get_state_at(campaign_id, branch_id, turn_id) or {}).get("scene_id")
        if old_scene and new_scene and old_scene != new_scene:
            transition = decision.get("scene_transition") or {}
            repo.add_event(campaign_id, branch_id, turn_id, type="scene_changed",
                           payload={"from_scene": old_scene, "to_scene": new_scene,
                                    "reason": transition.get("reason") or ""})
        clue_ids = decision.get("clues_revealed", [])
        already: set = set()
        if clue_ids:          # 懒查询：无提名时不查库
            already = {json.loads(e.payload_json).get("clue_id")
                       for e in repo.list_events(campaign_id, branch_id,
                                                 types=["clue"])}
        for clue_id in clue_ids:
            if clue_id in already:
                continue      # 已揭示过：不重复写事件与记忆（防 GM 重复提名）
            already.add(clue_id)
            content = ""
            if module is not None:
                try:
                    content = module.clue(clue_id).content
                except KeyError:
                    content = ""
            repo.add_event(campaign_id, branch_id, turn_id, type="clue",
                           payload={"clue_id": clue_id, "text": content})
            memory.write_event(campaign_id, branch_id,
                               MemoryEvent(type="clue", text=content or clue_id,
                                           turn_id=turn_id))
        # M3-4A：好感度应用（单点写入；module 未注入时零行为变化）
        attitudes = state.get("npc_attitudes", {})
        attitude_upd: dict = {}
        if module is not None:
            try:
                present = set(module.scene(new_scene).npcs)
                attitudes, changes = apply_attitude_deltas(
                    attitudes, decision.get("attitude_deltas", []), present)
                for change in changes:
                    repo.add_event(campaign_id, branch_id, turn_id, type="attitude",
                                   payload=change, visibility="all")
                if changes:
                    attitude_upd = {"npc_attitudes": attitudes}
            except Exception:      # 容错（设计 §4）：态度独立于回合成败，异常不更新
                attitudes = state.get("npc_attitudes", {})
                attitude_upd = {}
        repo.append_state(campaign_id, branch_id, turn_id,
                          {"scene_id": new_scene, "npc_attitudes": attitudes})
        memory.update_summaries(campaign_id, branch_id, turn_id)
        return {"turn_id": turn_id + 1, "decision": None,
                "ending_reached": decision.get("ending_reached"), **attitude_upd}

    return post_turn


def fallback(state: GameState) -> dict:
    """失败不推进：清空本轮 pending，保留 error 供调用方读取（wait_input 恢复时清除）。"""
    return {"player_inputs": [], "decision": None, "decision_raw": "",
            "check_results": [], "npc_reactions": {}, "narration": "",
            "narration_segments": [], "degraded": {},
            "ending_reached": None,
            "error": state.get("error")}
