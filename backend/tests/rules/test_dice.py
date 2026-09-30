from app.rules.dice import new_seed, roll_d100

def test_roll_is_deterministic_for_same_seed():
    assert roll_d100(42) == roll_d100(42)

def test_roll_within_range_for_many_seeds():
    assert all(1 <= roll_d100(s) <= 100 for s in range(1000))

def test_new_seed_fits_sqlite_integer():
    # SQLite INTEGER 为有符号 64 位：种子 ≥2**63 时 add_dice_record 写库溢出
    # （真机验收 resolve_failed 事故根因：randbits(64) 约半数超界）
    samples = [new_seed() for _ in range(64)]
    assert all(0 <= s < 2**63 for s in samples)

def test_new_seed_varies():
    assert new_seed() != new_seed()
