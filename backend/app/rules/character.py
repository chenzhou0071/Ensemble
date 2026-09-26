"""角色卡领域模型。"""
from dataclasses import dataclass, field


@dataclass
class Character:
    id: str
    name: str
    player_id: str | None
    attributes: dict[str, int] = field(default_factory=dict)
    skills: dict[str, int] = field(default_factory=dict)
    hp: int = 10
    max_hp: int = 10

    def skill_value(self, skill: str) -> int:
        return self.skills.get(skill, self.attributes.get(skill, 0))


def make_default_character(player_id: str, name: str) -> Character:
    """CLI 阶段的最小可用角色；正式建卡流程在 M3 计划实现。"""
    return Character(
        id=f"pc_{player_id}", name=name, player_id=player_id,
        attributes={"力量": 50, "敏捷": 55, "意志": 55, "智力": 60},
        skills={"侦查": 50, "聆听": 45, "潜行": 40, "话术": 45, "图书馆使用": 40},
        hp=10, max_hp=10,
    )
