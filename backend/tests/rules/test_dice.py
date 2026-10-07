from app.rules.dice import new_seed, roll_d100, roll_d100_with_bonus

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


def test_zero_net_matches_plain_roll():
    for s in (1, 2, 3, 99):
        assert roll_d100_with_bonus(s) == roll_d100(s)
        assert roll_d100_with_bonus(s, 2, 2) == roll_d100(s)      # net 抵销

def test_bonus_not_worse_penalty_not_better():
    for s in range(50):
        assert roll_d100_with_bonus(s, 1) <= roll_d100(s)          # 奖励取最小 ≥ 不劣于原掷
        assert roll_d100_with_bonus(s, 0, 1) >= roll_d100(s)       # 惩罚取最大 ≥ 不优于原掷

def test_net_clamped_to_two():
    for s in range(20):
        assert roll_d100_with_bonus(s, 9, 0) == roll_d100_with_bonus(s, 2, 0)
        assert roll_d100_with_bonus(s, 0, 9) == roll_d100_with_bonus(s, 0, 2)

def test_bonus_result_in_range():
    assert all(1 <= roll_d100_with_bonus(s, 2, 0) <= 100 for s in range(200))
