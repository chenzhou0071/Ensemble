"""d100 检定：纯函数，LLM 不参与任何数值计算。"""
from dataclasses import dataclass
from enum import StrEnum

from app.rules.dice import roll_d100, roll_d100_with_bonus


class CheckDifficulty(StrEnum):
    REGULAR = "regular"
    HARD = "hard"
    EXTREME = "extreme"


class SuccessLevel(StrEnum):
    CRITICAL = "critical"
    EXTREME = "extreme"
    HARD = "hard"
    REGULAR = "regular"
    FAIL = "fail"
    FUMBLE = "fumble"


_RANK = {SuccessLevel.FUMBLE: 0, SuccessLevel.FAIL: 1, SuccessLevel.REGULAR: 2,
         SuccessLevel.HARD: 3, SuccessLevel.EXTREME: 4, SuccessLevel.CRITICAL: 5}
_REQUIRED = {CheckDifficulty.REGULAR: 2, CheckDifficulty.HARD: 3, CheckDifficulty.EXTREME: 4}


@dataclass(frozen=True)
class CheckResult:
    actor: str
    skill: str
    skill_value: int
    difficulty: CheckDifficulty
    roll: int
    seed: int
    level: SuccessLevel
    success: bool
    bonus: int = 0
    penalty: int = 0


def _level_for(roll: int, skill_value: int) -> SuccessLevel:
    if roll == 1:
        return SuccessLevel.CRITICAL
    if roll >= 96:
        return SuccessLevel.FUMBLE
    if roll <= max(1, skill_value // 5):
        return SuccessLevel.EXTREME
    if roll <= skill_value // 2:
        return SuccessLevel.HARD
    if roll <= skill_value:
        return SuccessLevel.REGULAR
    return SuccessLevel.FAIL


def roll_check(actor: str, skill: str, skill_value: int,
               difficulty: CheckDifficulty, seed: int,
               bonus: int = 0, penalty: int = 0) -> CheckResult:
    net = max(-2, min(2, int(bonus) - int(penalty)))
    if net == 0:
        roll = roll_d100(seed)              # 与既有行为完全一致（保留 monkeypatch 语义）
    else:
        roll = roll_d100_with_bonus(seed, bonus, penalty)
    level = _level_for(roll, skill_value)
    if level is SuccessLevel.CRITICAL:
        success = True
    elif level is SuccessLevel.FUMBLE:
        success = False
    else:
        success = _RANK[level] >= _REQUIRED[difficulty]
    return CheckResult(actor, skill, skill_value, difficulty, roll, seed, level, success,
                       bonus=max(net, 0), penalty=max(-net, 0))


def bonus_note(bonus: int, penalty: int) -> str:
    """展示用标注：'（奖励骰 ×1） ' / ''；事件文本、提示词行、前端文案同构。"""
    parts = []
    if bonus:
        parts.append(f"奖励骰 ×{bonus}")
    if penalty:
        parts.append(f"惩罚骰 ×{penalty}")
    return f"（{'，'.join(parts)}） " if parts else ""
