"""GM 节点：结构化裁决（decide）与校验（validate，含 repair 重试）。"""
import json
import re
from typing import Callable

from app.graph.narrative import IncrementalSegmenter, parse_segments, stream_writer
from app.graph.schemas import parse_decision_json
from app.graph.state import GameState
from app.llm.client import ChatMessage, LLMClient, LlmContext
from app.obs.counters import get_counters
from app.rules.check import bonus_note

DECIDE_SYSTEM = (
    "你是跑团主持人（COC 风格）。基于玩家行动与当前场景做结构化裁决，"
    "只输出一个 JSON 对象（不要 markdown 代码块、不要任何解释文字），字段：\n"
    'intent_summary(str，一句话概括玩家意图)、'
    'checks(数组，元素 {"actor","skill","difficulty"(regular|hard|extreme),"secret"(bool，可选，默认 false),"bonus"(int，可选，0-2，默认 0),"penalty"(int，可选，0-2，默认 0),"target"(str，可选，攻击目标 NPC 的 id)})、'
    'proactive_npc_triggers(数组，元素 {"npc_id","trigger"})、'
    'scene_transition(null 或 {"to_scene","reason"})、'
    'clues_revealed(数组，元素为线索 id，仅当本回合玩家明确获得线索时填写)、'
    'ending_reached(null 或模块给定结局 id；命中结局条件时按收束规则必须填写)、'
    'attitude_deltas(数组，元素 {"npc_id","delta"(整数),"reason"}，仅当玩家行为在本回合实质影响了某在场 NPC 对你们的态度时给出，最多 2 条，否则空数组；npc_id 只能用当前场景内列出的；delta 按行为严重程度取 -15..15，拿不准就不给)、'
    'memory_queries(字符串数组)。\n'
    "规则：\n"
    "1. checks[].actor 必须用「玩家角色」列表里的角色 id；skill 从该角色卡的技能或属性名中逐字选取\n"
    "2. 只为结果不确定、失败有代价的玩家主动行动要求检定（闲聊、开门等必成动作不要检定）；每回合最多 2 个\n"
    "3. difficulty：普通行动 regular，专业或高风险 hard，近乎极限才用 extreme\n"
    "4. proactive_npc_triggers 仅当玩家行动直接涉及该 NPC、或场景需要其反应时给出；npc_id 只能用「在场 NPC」中列出的\n"
    "5. scene_transition 仅当玩家成功移向相邻场景时给出，to_scene 必须从「可去场景」中选，否则填 null\n"
    "6. memory_queries 为 0~3 个简短检索词，仅在需要回忆前情时给出\n"
    "7. 开场回合可以引入场面与 NPC，但不要要求检定；\n"
    "8. 玩家与 NPC 的社交行动即使检定失败，也要让该 NPC 在场回应（冷淡、回避、暗示皆可），不得让场面停滞或写成拒绝交流。\n"
    "9. secret=true 表示玩家角色无从察觉的暗骰（如暗中进行的观察或聆听）；其检定与结果不得在叙事中直接暴露。\n"
    "10. 奖励/惩罚骰（bonus/penalty）仅在情境明显有利/不利时给出（如充分准备、恶劣环境），各最多 2，默认省略。\n"
    "11. target 仅在玩家攻击当前场景内某个 NPC 时填写（被攻击者必须可被攻击），其余检定不要填 target。"
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


def _clue_block(state: GameState, module, scene, repo) -> str:
    """线索清单：已掌握（供核对结局前置）+ 本场景待发现（供提名 clues_revealed）。"""
    known_ids = {c.id for c in module.clues}
    revealed: list[str] = []
    if repo is not None:
        for e in repo.list_events(state["campaign_id"], state["branch_id"], types=["clue"]):
            cid = json.loads(e.payload_json).get("clue_id")
            if cid in known_ids and cid not in revealed:
                revealed.append(cid)
    parts: list[str] = []
    if revealed:
        lines = "\n".join(f"- {cid}：{module.clue(cid).content}" for cid in revealed)
        parts.append("玩家已掌握的线索（用于核对结局前置要求；不要重复填进 clues_revealed）：\n"
                     f"{lines}\n")
    pending = [cid for cid in scene.clues if cid not in revealed]
    if pending:
        lines = "\n".join(f"- {cid}：{module.clue(cid).content}" for cid in pending)
        parts.append("本场景可发现的线索（仅当玩家行动确实发现时，才把这些 id 填进 "
                     f"clues_revealed；未列出的不要填）：\n{lines}\n")
    return "".join(parts)


def build_decide_node(client: LLMClient, module, repo=None) -> Callable[[GameState], dict]:
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
        ending_lines = "\n".join(f"- {e.id}：{e.condition}" for e in module.endings)
        ending_block = (
            f"结局条件（命中即须收束）：\n{ending_lines}\n"
            "收束规则：本回合玩家行动已实际执行某条结局条件描述的行动、且其前置要求已满足时"
            "（前置可对照「玩家已掌握的线索」核对），必须把该结局 id 填进 ending_reached；"
            "不得新增设定使条件落空，不得把已命中的结局动作改写为无效、被阻止或延迟。"
            "若你认为该行动结果不确定而要求了检定，仍须照填 ending_reached"
            "（检定成功则正式收束、失败则本回合不收束，系统自动处理）。\n"
            if ending_lines else "")
        clue_block = _clue_block(state, module, scene, repo)
        user = (
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"可去场景：{exit_lines}\n"
            f"在场 NPC：\n{npc_lines}\n"
            f"玩家角色：\n{char_lines}\n"
            f"记忆上下文：\n{state.get('memory_context') or '（无）'}\n"
            f"{clue_block}"
            f"{ending_block}"
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


def build_validate_node(client: LLMClient, module=None) -> Callable[[GameState], dict]:
    def _check_refs(decision) -> str | None:
        if module is None:
            return None
        known_clues = {c.id for c in module.clues}
        unknown = [c for c in decision.clues_revealed if c not in known_clues]
        if unknown:
            return f"未知线索 id：{unknown}（可用：{sorted(known_clues)}）"
        if decision.ending_reached is not None:
            known_endings = {e.id for e in module.endings}
            if decision.ending_reached not in known_endings:
                return f"未知结局 id：{decision.ending_reached}（可用：{sorted(known_endings)}）"
        return None

    def _normalize_targets(decision, state: GameState) -> None:
        """非法/已败亡的攻击目标就地降级为普通检定（不触发 repair）；无 module/场景信息时跳过。"""
        if module is None:
            return
        try:
            scene = module.scene(state.get("scene_id", ""))
        except KeyError:
            return
        npc_hp = state.get("npc_hp") or {}
        for chk in decision.checks:
            if chk.target is None:
                continue
            try:
                npc = module.npc(chk.target)
            except KeyError:
                chk.target = None
                continue
            if (npc.combat is None or chk.target not in scene.npcs
                    or int(npc_hp.get(chk.target, 1)) <= 0):
                chk.target = None

    def validate_decision(state: GameState) -> dict:
        raw = state.get("decision_raw", "")
        repair_msg = ""
        for attempt in range(2):  # 首次 + repair 重试恰好 1 次（规格 §8）
            try:
                decision = parse_decision_json(raw)
                ref_error = _check_refs(decision)
                if ref_error is None:
                    _normalize_targets(decision, state)
                    return {"decision": decision.model_dump(mode="json"), "error": None}
                repair_msg = ref_error
            except Exception as exc:
                repair_msg = str(exc)
            if attempt == 1:
                break  # repair 后仍不合格：放弃，不再追加调用
            repair = [
                ChatMessage(role="system", content=DECIDE_SYSTEM),
                ChatMessage(
                    role="user",
                    content=(f"你上次的输出不合格（{repair_msg}）。"
                             f"请只输出合法 JSON，字段要求不变。上次输出：\n{raw}")),
            ]
            try:
                raw = client.chat("gm", repair, _ctx(state), cheap=_cheap(state))
            except Exception as exc:
                repair_msg = str(exc)
                break  # 请求本身失败：无可修复
        get_counters().record_fallback("decision_invalid")
        return {"error": "decision_invalid", "decision": None,
                "degraded": {"decision_invalid": True}}

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
        dice_note = bonus_note(int(c.get("bonus", 0)), int(c.get("penalty", 0)))
        note = ("（暗骰：不得在叙事中直接暴露该检定与结果，只可化为隐约的线索或不安感）"
                if c.get("secret") else "")
        lines.append(f"- {_char_name(state, c.get('actor'))}的「{c['skill']}」："
                     f"{c['roll']}/{c['skill_value']} {dice_note}→ {c['level']}（{verdict}）{note}")
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


def _combat_lines(state: GameState) -> str:
    lines = []
    for c in state.get("combat_log", []):
        atk, dfn = c.get("attack", {}), c.get("defense", {})
        if c.get("hit"):
            outcome = f"命中，伤害 {c['damage']}（HP {c['hp_before']}→{c['hp_after']}）"
            if c.get("hp_after") == 0:
                outcome += "，目标倒下（败亡）"
        else:
            outcome = "未命中"
        lines.append(f"- {c['name']}（{c['npc_id']}）：{outcome}；"
                     f"攻击 {atk.get('roll')}/{atk.get('skill_value')} → {atk.get('level')}，"
                     f"闪避 {dfn.get('roll')}/{dfn.get('skill_value')} → {dfn.get('level')}")
    return "\n".join(lines)


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
        ending_line = ""
        decision = state.get("decision") or {}
        if decision.get("ending_reached"):
            try:  # 终章指令：条件文案即收尾方向；要求写全"直接结果+余波"，并放宽篇幅
                ending_line = (
                    f"结局收束（{decision['ending_reached']}）："
                    f"{module.ending(decision['ending_reached']).condition}\n"
                    "这是故事的最后一幕。请写一段完整的终章叙事：先交代玩家行动带来的直接结果，"
                    "再以余波笔法写清后续——这个地方与生活于此的人们接下来如何、相关 NPC 的结局、"
                    "玩家角色自身的最终处境（可补足与剧本设定相称的后续）；让故事完整收束，"
                    "不要停在动作发生的瞬间，也不要留下悬而未决的线索。"
                    "本回合篇幅可放宽到 500 字左右。\n")
            except KeyError:
                ending_line = ""
        clue_line = ""
        known_clues = {c.id for c in module.clues}
        new_clues = list(dict.fromkeys(
            cid for cid in (decision.get("clues_revealed") or []) if cid in known_clues))
        if new_clues:
            items = "\n".join(f"- {module.clue(cid).content}" for cid in new_clues)
            clue_line = ("本回合玩家新发现的线索（须在叙事中自然呈现发现过程与内容；"
                         "不要罗列清单、不要出现线索编号或规则术语）：\n"
                         f"{items}\n")
        prev_line = _previous_narration_tail(state, repo)
        tail_instr = ("请接着开场白写下去（从玩家进入当前场景开始），不要复述开场白。"
                      if opener else "请输出本回合的完整叙事。")
        combat_lines = _combat_lines(state)
        combat_block = f"战斗结算：\n{combat_lines}\n" if combat_lines else ""
        user = (
            f"{opening_line}"
            f"{ending_line}"
            f"{prev_line}"
            f"当前场景：{scene.name}\n{scene.description}\n"
            f"玩家行动：\n{inputs_txt}\n"
            f"检定结果：\n{_check_lines(state)}\n"
            f"{combat_block}"
            f"NPC 反应：\n{_reaction_lines(state, module)}\n"
            f"{clue_line}"
            f"{tail_instr}"
        )
        messages = [ChatMessage(role="system", content=NARRATE_SYSTEM),
                    ChatMessage(role="user", content=user)]
        writer = stream_writer()
        last_error = ""
        for _ in range(2):  # 首次 + repair 重试 1 次（规格 §8）
            writer({"reset": True})  # 重试时通知消费方清空已呈现内容
            if opener:  # 开场白代码级置顶保真：流式先发原文，再流模型衔接
                writer({"speaker": "gm", "text": opener})
            segmenter = IncrementalSegmenter()
            parts: list[str] = []
            try:
                for delta in client.chat_stream("gm", messages, _ctx(state),
                                                cheap=_cheap(state)):
                    parts.append(delta)
                    for speaker, text in segmenter.feed(delta):
                        writer({"speaker": speaker, "text": text})
                for speaker, text in segmenter.flush():
                    writer({"speaker": speaker, "text": text})
                raw = "".join(parts)
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
        get_counters().record_fallback("narrate_failed")
        return {"error": "narrate_failed", "degraded": {"narrate_failed": True},
                "narration": "", "narration_segments": []}

    return gm_narrate
