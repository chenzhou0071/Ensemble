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
