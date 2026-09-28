"""GM 节点：结构化裁决（decide）与校验（validate，含 repair 重试）。"""
from typing import Callable

from app.graph.schemas import parse_decision_json
from app.graph.state import GameState
from app.llm.client import ChatMessage, LLMClient, LlmContext

DECIDE_SYSTEM = (
    "你是跑团主持人（COC 风格）。基于玩家行动与当前场景做结构化裁决，只输出一个 JSON 对象，字段：\n"
    'intent_summary(str)、checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme)})、'
    'proactive_npc_triggers(数组，元素 {"npc_id","trigger"})、'
    'scene_transition(null 或 {"to_scene","reason"})、memory_queries(字符串数组)。\n'
    "规则：只为玩家的主动行动要求检定，每回合最多 2 个检定；NPC 只能用场景内列出的；"
    "开场回合可以引入场面但不要要求检定。"
)


def _ctx(state: GameState) -> LlmContext:
    return LlmContext(state["campaign_id"], state["branch_id"], state["turn_id"])


def _cheap(state: GameState) -> bool:
    return state.get("budget_level") == "exceeded"


def build_decide_node(client: LLMClient, module) -> Callable[[GameState], dict]:
    def gm_decide(state: GameState) -> dict:
        scene = module.scene(state["scene_id"])
        npc_lines = "\n".join(
            f"- {nid}: {module.npc(nid).name}（{module.npc(nid).persona}），当前态度 {state['npc_attitudes'].get(nid, 50)}"
            for nid in scene.npcs
        ) or "（无）"
        inputs_txt = "\n".join(
            f"- {i['player_id']}: {i['text']}" for i in state.get("player_inputs", [])
        ) or "（本回合为开场，无玩家行动）"
        user = (
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"在场 NPC：\n{npc_lines}\n"
            f"记忆上下文：\n{state.get('memory_context') or '（无）'}\n"
            f"玩家行动：\n{inputs_txt}"
        )
        raw = client.chat("gm", [ChatMessage(role="system", content=DECIDE_SYSTEM),
                                 ChatMessage(role="user", content=user)],
                          _ctx(state), cheap=_cheap(state))
        return {"decision_raw": raw}

    return gm_decide


def build_validate_node(client: LLMClient) -> Callable[[GameState], dict]:
    def validate_decision(state: GameState) -> dict:
        raw = state.get("decision_raw", "")
        try:
            decision = parse_decision_json(raw)
        except Exception as first_error:
            repair = [ChatMessage(
                role="user",
                content=(f"你上次的输出无法解析（{first_error}）。"
                         f"请只输出合法 JSON，字段要求不变。上次输出：\n{raw}"),
            )]
            try:
                fixed = client.chat("gm", repair, _ctx(state), cheap=_cheap(state))
                decision = parse_decision_json(fixed)
            except Exception:
                return {"error": "decision_invalid", "decision": None,
                        "degraded": {"decision_invalid": True}}
        return {"decision": decision.model_dump(mode="json"), "error": None}

    return validate_decision
