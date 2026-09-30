"""GM 节点：结构化裁决（decide）与校验（validate，含 repair 重试）。"""
import json
import re
from typing import Callable

from app.graph.narrative import parse_segments
from app.graph.schemas import parse_decision_json
from app.graph.state import GameState
from app.llm.client import ChatMessage, LLMClient, LlmContext

DECIDE_SYSTEM = (
    "你是跑团主持人（COC 风格）。基于玩家行动与当前场景做结构化裁决，"
    "只输出一个 JSON 对象（不要 markdown 代码块、不要任何解释文字），字段：\n"
    'intent_summary(str，一句话概括玩家意图)、'
    'checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme)})、'
    'proactive_npc_triggers(数组，元素 {"npc_id","trigger"})、'
    'scene_transition(null 或 {"to_scene","reason"})、memory_queries(字符串数组)。\n'
    "规则：\n"
    "1. checks[].actor 必须用「玩家角色」列表里的角色 id；skill 从该角色卡的技能或属性名中逐字选取\n"
    "2. 只为结果不确定、失败有代价的玩家主动行动要求检定（闲聊、开门等必成动作不要检定）；每回合最多 2 个\n"
    "3. difficulty：普通行动 regular，专业或高风险 hard，近乎极限才用 extreme\n"
    "4. proactive_npc_triggers 仅当玩家行动直接涉及该 NPC、或场景需要其反应时给出；npc_id 只能用「在场 NPC」中列出的\n"
    "5. scene_transition 仅当玩家成功移向相邻场景时给出，to_scene 必须从「可去场景」中选，否则填 null\n"
    "6. memory_queries 为 0~3 个简短检索词，仅在需要回忆前情时给出\n"
    "7. 开场回合可以引入场面与 NPC，但不要要求检定；\n"
    "8. 玩家与 NPC 的社交行动即使检定失败，也要让该 NPC 在场回应（冷淡、回避、暗示皆可），不得让场面停滞或写成拒绝交流。"
)


def _ctx(state: GameState) -> LlmContext:
    return LlmContext(state["campaign_id"], state["branch_id"], state["turn_id"])


def _cheap(state: GameState) -> bool:
    return state.get("budget_level") == "exceeded"


def _kv(d: dict | None) -> str:
    return "、".join(f"{k} {v}" for k, v in (d or {}).items()) or "（无）"


def _exit_label(module, scene_id: str) -> str:
    try:
        return f"{scene_id}（{module.scene(scene_id).name}）"
    except KeyError:
        return scene_id


def build_decide_node(client: LLMClient, module) -> Callable[[GameState], dict]:
    def gm_decide(state: GameState) -> dict:
        scene = module.scene(state["scene_id"])
        npc_lines = "\n".join(
            f"- {nid}: {module.npc(nid).name}（{module.npc(nid).persona}），当前态度 {state['npc_attitudes'].get(nid, 50)}"
            for nid in scene.npcs
        ) or "（无）"
        exit_lines = "、".join(_exit_label(module, e) for e in scene.exits) or "（无）"
        char_lines = "\n".join(
            f"- {cid}：{c.get('name', '')}；技能 {_kv(c.get('skills'))}；属性 {_kv(c.get('attributes'))}"
            for cid, c in state.get("characters", {}).items()
        ) or "（无）"
        inputs_txt = "\n".join(
            f"- {i['player_id']}（角色 {i.get('character_id', '?')}）：{i['text']}"
            for i in state.get("player_inputs", [])
        ) or "（本回合为开场，无玩家行动）"
        user = (
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"可去场景：{exit_lines}\n"
            f"在场 NPC：\n{npc_lines}\n"
            f"玩家角色：\n{char_lines}\n"
            f"记忆上下文：\n{state.get('memory_context') or '（无）'}\n"
            f"玩家行动：\n{inputs_txt}"
        )
        try:
            raw = client.chat("gm", [ChatMessage(role="system", content=DECIDE_SYSTEM),
                                     ChatMessage(role="user", content=user)],
                              _ctx(state), cheap=_cheap(state))
        except Exception:
            # LLM 真异常（网络/超时/预算熔断）→ 失败不推进（规格 §8 统一原则）
            return {"decision_raw": "", "error": "decide_failed",
                    "degraded": {"decide_failed": True}}
        return {"decision_raw": raw}

    return gm_decide


def build_validate_node(client: LLMClient) -> Callable[[GameState], dict]:
    def validate_decision(state: GameState) -> dict:
        raw = state.get("decision_raw", "")
        try:
            decision = parse_decision_json(raw)
        except Exception as first_error:
            repair = [
                ChatMessage(role="system", content=DECIDE_SYSTEM),
                ChatMessage(
                    role="user",
                    content=(f"你上次的输出无法解析（{first_error}）。"
                             f"请只输出合法 JSON，字段要求不变。上次输出：\n{raw}"),
                ),
            ]
            try:
                fixed = client.chat("gm", repair, _ctx(state), cheap=_cheap(state))
                decision = parse_decision_json(fixed)
            except Exception:
                return {"error": "decision_invalid", "decision": None,
                        "degraded": {"decision_invalid": True}}
        return {"decision": decision.model_dump(mode="json"), "error": None}

    return validate_decision


NARRATE_SYSTEM = (
    "你是跑团主持人（COC 风格）。把本回合的结果编排成一段连贯的中文叙事。\n"
    "要求：\n"
    "1. NPC 的台词必须用标记包裹：[[npc:<npc_id>]]台词内容[[/npc]]，<npc_id> 只能用给定的 id；标记内只写原话，不要写「某某说：」前缀；\n"
    "2. 标记之外的文字是你的旁白（环境、动作、结果）；NPC 的动作放进旁白描述；\n"
    "3. 把检定结果转化为故事后果（成功与失败都要有后果）；不要把掷骰数值、id、规则术语写进叙事；\n"
    "4. NPC 台词与动作以给定的「NPC 反应」为准：可润色使其连贯，不得改变原意，不得编造未提供的台词；\n"
    "5. 用第二人称（你/你们）叙述，需要区分玩家时用角色名；单回合篇幅 300 字以内，开场可稍长；\n"
    "6. 不要输出 JSON、markdown 标记、规则解释或任何元评论；可以补充环境细节，但不要新增重要角色、地点或剧情事实；不得虚构未发生过的行动或接触（如并未发生的握手、触碰）；\n"
    "7. 不重复描写已描述过的环境与氛围：仅当场景首次出现或发生切换时描写环境，其余直接从玩家行动的结果或上一回合的结尾承接推进；\n"
    "8. 旁白中提及 NPC 时一律用其名字，不要换成其他身份称呼（如「店主」「老板娘」）；\n"
    "9. 失败或受挫的结果也要有推进感：可以表现为沉默、警告、谜语或意有所指的举动，不要把答案或下一步指令写得太直白；\n"
    "10. 不得引入模组外的具体人物：背景人群只能一笔带过（如「几个客人」），不得刻画可被互动、追问或跟随的个人，也不要给背景人物取名或赋予可被追究的身份（如说「那边耳朵背的客人」，不说「老周」）；若玩家行动指向并不存在的人物，用自然方式淡化（如那人只是打盹的旅人、已起身离开），不要让其成为剧情角色。"
)


def _char_name(state: GameState, character_id: str | None) -> str:
    """叙事用角色名：查不到回退 id（避免内部 id 泄进叙事文本）。"""
    if character_id:
        c = state.get("characters", {}).get(character_id)
        if c and c.get("name"):
            return c["name"]
    return character_id or "?"


def _check_lines(state: GameState) -> str:
    lines = []
    for c in state.get("check_results", []):
        verdict = "成功" if c.get("success") else "失败"
        lines.append(f"- {_char_name(state, c.get('actor'))}的「{c['skill']}」："
                     f"{c['roll']}/{c['skill_value']} → {c['level']}（{verdict}）")
    return "\n".join(lines) or "（本回合无检定）"


def _reaction_lines(state: GameState, module) -> str:
    lines = []
    for npc_id, r in (state.get("npc_reactions") or {}).items():
        r = r or {}
        speech, action = r.get("speech", ""), r.get("action")
        if not speech and not action:
            continue  # 沉默占位（NPC 失败降级，规格 §8）：不进入提示词
        try:
            name = module.npc(npc_id).name
        except KeyError:
            name = npc_id
        part = f"- {npc_id}（{name}）"
        if speech:
            part += f" 台词：「{speech}」"
        if action:
            part += f" 动作：{action}"
        lines.append(part)
    return "\n".join(lines) or "（本回合无 NPC 回应）"


def _previous_narration_tail(state: GameState, repo) -> str:
    """上一回合叙事结尾（接续锚点）：防止每回合从头铺垫环境导致重复。"""
    if repo is None:
        return ""
    rows = repo.list_events(state["campaign_id"], state["branch_id"], types=["narration"])
    if not rows:
        return ""
    try:
        text = json.loads(rows[-1].payload_json).get("text", "")
    except (ValueError, TypeError):
        return ""
    text = re.sub(r"\[\[[^\]]*\]\]", "", text)  # 剥离 [[npc:…]] 标记，防碎片入提示词
    tail = text[-120:]
    return f"上一回合结尾（仅供承接，不要复述）：…{tail}\n" if tail else ""


def build_narrate_node(client: LLMClient, module, repo=None) -> Callable[[GameState], dict]:
    def gm_narrate(state: GameState) -> dict:
        scene = module.scene(state["scene_id"])
        inputs_txt = "\n".join(
            f"- {_char_name(state, i.get('character_id') or i.get('player_id'))}：{i['text']}"
            for i in state.get("player_inputs", [])
        ) or "（开场回合，无玩家行动）"
        opener = module.opening.narration.strip() if state.get("is_opening") else ""
        opening_line = ""
        if opener:
            opening_line = ("开场白（原文将直接呈现给玩家，无需你重复或改写；请在它之后衔接叙事）：\n"
                            f"{opener}\n")
        prev_line = _previous_narration_tail(state, repo)
        tail_instr = ("请接着开场白写下去（从玩家进入当前场景开始），不要复述开场白。"
                      if opener else "请输出本回合的完整叙事。")
        user = (
            f"{opening_line}"
            f"{prev_line}"
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"玩家行动：\n{inputs_txt}\n"
            f"检定结果：\n{_check_lines(state)}\n"
            f"NPC 反应：\n{_reaction_lines(state, module)}\n"
            f"{tail_instr}"
        )
        messages = [ChatMessage(role="system", content=NARRATE_SYSTEM),
                    ChatMessage(role="user", content=user)]
        last_error = ""
        for _ in range(2):  # 首次 + repair 重试 1 次（规格 §8）
            try:
                raw = client.chat("gm", messages, _ctx(state), cheap=_cheap(state))
                segs = parse_segments(raw)
                if segs:
                    out_segs = [{"speaker": s.speaker, "text": s.text} for s in segs]
                    if opener:  # 模组开场白逐字置顶（模型改写不可信，代码级保真）
                        return {"narration": f"{opener}\n\n{raw}",
                                "narration_segments": [{"speaker": "gm", "text": opener}] + out_segs,
                                "error": None}
                    return {"narration": raw, "narration_segments": out_segs, "error": None}
                last_error = "empty narration"
            except Exception as exc:
                last_error = str(exc)
            messages = messages + [ChatMessage(
                role="user",
                content=f"上次输出不合格（{last_error}）。请重新输出完整叙事，"
                        "NPC 台词必须带 [[npc:id]] 标记。")]
        return {"error": "narrate_failed", "degraded": {"narrate_failed": True},
                "narration": "", "narration_segments": []}

    return gm_narrate
