"""骰子：secrets 生成真随机 seed，random.Random(seed) 保证结果可复现。

seed 取 63 位：SQLite INTEGER 为有符号 64 位（上限 2**63-1），
64 位随机数约半数超出范围，会在 add_dice_record 写库时 OverflowError。
"""
import random
import secrets


def new_seed() -> int:
    return secrets.randbits(63)


def roll_d100(seed: int) -> int:
    return random.Random(seed).randint(1, 100)


def roll_d100_with_bonus(seed: int, bonus: int = 0, penalty: int = 0) -> int:
    """奖惩骰（COC 7e 惯例）：net = bonus - penalty，夹紧 ±2；net == 0 完全等价 roll_d100。

    net > 0：连掷 net+1 个 d100 取最小（有利）；net < 0：取最大（不利）。
    同一条 random.Random(seed) 流，结果完全可复现。
    """
    net = max(-2, min(2, int(bonus) - int(penalty)))
    if net == 0:
        return roll_d100(seed)
    rng = random.Random(seed)
    rolls = [rng.randint(1, 100) for _ in range(abs(net) + 1)]
    return min(rolls) if net > 0 else max(rolls)
