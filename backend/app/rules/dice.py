"""骰子：secrets 生成真随机 seed，random.Random(seed) 保证结果可复现。"""
import random
import secrets


def new_seed() -> int:
    return secrets.randbits(64)


def roll_d100(seed: int) -> int:
    return random.Random(seed).randint(1, 100)
