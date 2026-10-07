"""轻量战斗结算（规格 §14：单次攻击对单 NPC；无先攻/轮循环/NPC 反击）。"""
import random
import re
from dataclasses import dataclass

from app.rules.check import CheckDifficulty, CheckResult, roll_check

DICE_EXPR_RE = re.compile(r"^(\d*)d(\d+)(?:\+(\d+))?$")


def parse_damage_dice(dice: str) -> tuple[int, int, int]:
    """'1d6' / '2d4+1' → (n, sides, bonus)；非法表达式抛 ValueError。"""
    m = DICE_EXPR_RE.match(dice.strip())
    if not m:
        raise ValueError(f"bad damage dice expression: {dice!r}")
    return int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 0)


def roll_damage(seed: int, dice: str) -> int:
    n, sides, bonus = parse_damage_dice(dice)
    rng = random.Random(seed)
    return sum(rng.randint(1, sides) for _ in range(n)) + bonus


@dataclass(frozen=True)
class CombatOutcome:
    attack: CheckResult      # 攻击检定（支持奖惩骰，M5-4）
    defense: CheckResult     # 防御检定（NPC 闪避）
    hit: bool                # 命中 = 攻击成功且防御失败
    damage: int              # 命中伤害；未命中恒为 0


def resolve_attack(actor: str, skill: str, attack_value: int,
                   defender: str, defense_value: int, damage_dice: str,
                   seed: int, difficulty: CheckDifficulty = CheckDifficulty.REGULAR,
                   bonus: int = 0, penalty: int = 0) -> CombatOutcome:
    rng = random.Random(seed)          # 单一 seed 派生三条子流：可复现且互不干扰
    # getrandbits 必须 < 2^63：seed 经 M5-7 落 dice 表（SQLite INTEGER 为有符号 64 位），
    # getrandbits(64) 约半数 ≥ 2^63 会溢出（M2 同根因事故，勿改回）
    attack = roll_check(actor, skill, attack_value, difficulty, rng.getrandbits(63),
                        bonus=bonus, penalty=penalty)
    defense = roll_check(defender, "闪避", defense_value, CheckDifficulty.REGULAR,
                         rng.getrandbits(63))
    hit = attack.success and not defense.success
    damage = roll_damage(rng.getrandbits(63), damage_dice) if hit else 0
    return CombatOutcome(attack=attack, defense=defense, hit=hit, damage=damage)
