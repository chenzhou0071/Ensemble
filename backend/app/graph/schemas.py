"""GM 决策与 NPC 反应的结构化契约；叙事有序性依赖它保持中间产物结构化。"""
from pydantic import BaseModel, Field

from app.rules.check import CheckDifficulty


class CheckRequest(BaseModel):
    actor: str
    skill: str
    difficulty: CheckDifficulty = CheckDifficulty.REGULAR
    secret: bool = False          # true=暗骰：玩家角色无从察觉，叙事不得直接暴露


class NpcTrigger(BaseModel):
    npc_id: str
    trigger: str = ""


class SceneTransition(BaseModel):
    to_scene: str
    reason: str = ""


class AttitudeDelta(BaseModel):
    npc_id: str
    delta: int                    # 建议 -15..15；代码最终截断
    reason: str = ""


class GmDecision(BaseModel):
    intent_summary: str = ""
    checks: list[CheckRequest] = Field(default_factory=list)
    proactive_npc_triggers: list[NpcTrigger] = Field(default_factory=list)
    scene_transition: SceneTransition | None = None
    memory_queries: list[str] = Field(default_factory=list)
    clues_revealed: list[str] = Field(default_factory=list)
    ending_reached: str | None = None
    attitude_deltas: list[AttitudeDelta] = Field(default_factory=list)   # 代码最多取前 2 条


class NpcReaction(BaseModel):
    npc_id: str
    speech: str
    action: str | None = None


def parse_decision_json(raw: str) -> GmDecision:
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in LLM output")
    return GmDecision.model_validate_json(text[start:end + 1])
