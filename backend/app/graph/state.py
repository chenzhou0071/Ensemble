"""主图状态：L1 图内状态 + 回合中间产物。"""
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


class TurnInput(BaseModel):
    player_id: str
    character_id: str
    text: str
    submitted_at: str = ""


class TurnInputs(BaseModel):
    turn_id: int
    inputs: list[TurnInput] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def merge_dict(current: dict, update: dict) -> dict:
    """dict 通道合并；update 为空 dict 时清空（回合间重置用）。"""
    if update == {}:
        return {}
    return {**current, **update}


class GameState(TypedDict, total=False):
    campaign_id: str
    branch_id: str
    thread_id: str
    turn_id: int
    is_opening: bool
    # L2 快照（intake 装载，回合内只读）
    scene_id: str
    npc_attitudes: dict[str, int]
    characters: dict[str, dict]
    # 预算层级（ok / tight / exceeded / paused）
    budget_level: str
    # 本回合产物
    player_inputs: list[dict]
    decision: dict | None
    decision_raw: str
    check_results: list[dict]
    memory_context: str
    npc_reactions: Annotated[dict[str, dict], merge_dict]
    narration: str
    narration_segments: list[dict]
    error: str | None
    degraded: Annotated[dict[str, bool], merge_dict]
    ending_reached: str | None
