"""模组内容模型：内容与引擎分离，字段即公开契约。"""
from pydantic import BaseModel, Field, field_validator

from app.rules.combat import parse_damage_dice


class ModuleMeta(BaseModel):
    id: str
    title: str
    author: str = ""
    version: str = "0.1"
    system: str = "coc-lite"


class Opening(BaseModel):
    narration: str
    scene_id: str
    player_goal: str = ""


class Scene(BaseModel):
    id: str
    name: str
    description: str = ""
    npcs: list[str] = Field(default_factory=list)
    exits: list[str] = Field(default_factory=list)
    clues: list[str] = Field(default_factory=list)


class NpcCombat(BaseModel):
    defense: int = Field(default=40, ge=1, le=100)   # 防御（闪避）技能值
    damage: str = "1d4"                              # 伤害骰表达式（NdM+K）
    hp: int = Field(default=8, ge=1)

    @field_validator("damage")
    @classmethod
    def _damage_must_parse(cls, v: str) -> str:
        parse_damage_dice(v)
        return v


class NpcDef(BaseModel):
    id: str
    name: str
    persona: str
    knowledge: list[str] = Field(default_factory=list)
    initial_attitude: int = 50
    combat: NpcCombat | None = None      # 存在即可被攻击（M5-7）；缺省 NPC 不可被攻击


class Clue(BaseModel):
    id: str
    content: str
    unlocks: list[str] = Field(default_factory=list)


class Ending(BaseModel):
    id: str
    scene: str
    condition: str


class Module(BaseModel):
    meta: ModuleMeta
    opening: Opening
    scenes: list[Scene]
    npcs: list[NpcDef]
    clues: list[Clue]
    endings: list[Ending]

    def scene(self, scene_id: str) -> Scene:
        for s in self.scenes:
            if s.id == scene_id:
                return s
        raise KeyError(f"scene not found: {scene_id}")

    def npc(self, npc_id: str) -> NpcDef:
        for n in self.npcs:
            if n.id == npc_id:
                return n
        raise KeyError(f"npc not found: {npc_id}")

    def ending(self, ending_id: str) -> Ending:
        for e in self.endings:
            if e.id == ending_id:
                return e
        raise KeyError(f"ending not found: {ending_id}")

    def clue(self, clue_id: str) -> Clue:
        for c in self.clues:
            if c.id == clue_id:
                return c
        raise KeyError(f"clue not found: {clue_id}")
