"""回合节点：intake / wait_input（本任务）与 resolve_checks / post_turn / fallback（Task 16）。"""
from langgraph.types import interrupt

from app.graph.state import GameState
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
        results = []
        for chk in checks:
            actor, skill = chk["actor"], chk["skill"]
            skill_value = _skill_value(state, actor, skill)
            seed = new_seed()
            r = roll_check(actor, skill, skill_value,
                           CheckDifficulty(chk.get("difficulty", "regular")), seed)
            repo.add_dice_record(campaign_id, branch_id, turn_id, r.actor, r.skill,
                                 r.skill_value, str(r.difficulty), r.roll, str(r.level), r.seed)
            verdict = "成功" if r.success else "失败"
            repo.add_event(campaign_id, branch_id, turn_id, type="check",
                           payload={"text": f"{actor} 的「{skill}」检定：{r.roll}/{r.skill_value} "
                                            f"→ {r.level}（{verdict}）",
                                    "roll": r.roll, "level": str(r.level), "success": r.success})
            results.append({"actor": r.actor, "skill": r.skill, "roll": r.roll,
                            "skill_value": r.skill_value, "level": str(r.level),
                            "success": r.success, "seed": r.seed,
                            "difficulty": str(r.difficulty)})
        return {"check_results": results}

    return resolve_checks


def build_post_turn_node(repo, memory):
    def post_turn(state: GameState) -> dict:
        campaign_id, branch_id, turn_id = state["campaign_id"], state["branch_id"], state["turn_id"]
        narration = state.get("narration", "")
        if narration:
            repo.add_event(campaign_id, branch_id, turn_id, type="narration",
                           payload={"text": narration,
                                    "segments": state.get("narration_segments", [])})
        repo.append_state(campaign_id, branch_id, turn_id,
                          {"scene_id": state.get("scene_id"),
                           "npc_attitudes": state.get("npc_attitudes", {})})
        memory.update_summaries(campaign_id, branch_id, turn_id)
        return {"turn_id": turn_id + 1, "decision": None}

    return post_turn


def fallback(state: GameState) -> dict:
    """失败不推进：清空本轮 pending，保留 error 供调用方读取（wait_input 恢复时清除）。"""
    return {"player_inputs": [], "decision": None, "decision_raw": "",
            "check_results": [], "npc_reactions": {}, "narration": "",
            "narration_segments": [], "degraded": {},
            "error": state.get("error")}
