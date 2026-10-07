from app.rules.check import CheckDifficulty, SuccessLevel, bonus_note, roll_check

def make(skill_value, difficulty=CheckDifficulty.REGULAR, seed=1):
    return roll_check("pc_1", "潜行", skill_value, difficulty, seed)

def test_critical_on_natural_one(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 1)
    r = make(50)
    assert r.level is SuccessLevel.CRITICAL and r.success

def test_fumble_on_96_plus(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 96)
    r = make(90)
    assert r.level is SuccessLevel.FUMBLE and not r.success

def test_extreme_hard_regular_fail_bands(monkeypatch):
    for roll, expected in [(5, SuccessLevel.EXTREME), (25, SuccessLevel.HARD), (50, SuccessLevel.REGULAR), (51, SuccessLevel.FAIL)]:
        monkeypatch.setattr("app.rules.check.roll_d100", lambda seed, r=roll: r)
        assert make(50).level is expected

def test_difficulty_gate(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 25)  # HARD 级
    assert make(50, CheckDifficulty.HARD).success
    assert not make(50, CheckDifficulty.EXTREME).success

def test_result_carries_seed_and_roll():
    r = roll_check("pc_1", "聆听", 60, CheckDifficulty.REGULAR, seed=123456)
    assert r.seed == 123456 and 1 <= r.roll <= 100


def test_zero_net_keeps_plain_roll(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 42)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7)
    assert r.roll == 42 and r.bonus == 0 and r.penalty == 0

def test_net_zero_cancels_bonus_and_penalty(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100", lambda seed: 17)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7,
                   bonus=2, penalty=2)
    assert r.roll == 17 and r.bonus == 0 and r.penalty == 0

def test_bonus_delegates_and_clamps_to_two(monkeypatch):
    seen = []
    def fake(seed, bonus=0, penalty=0):
        seen.append((seed, bonus, penalty))
        return 30
    monkeypatch.setattr("app.rules.check.roll_d100_with_bonus", fake)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7, bonus=3)
    assert r.roll == 30 and r.bonus == 2 and r.penalty == 0        # 结果字段存夹紧值
    assert seen == [(7, 3, 0)]                                     # 原样透传给掷骰（内部再夹紧）

def test_penalty_net_negative(monkeypatch):
    monkeypatch.setattr("app.rules.check.roll_d100_with_bonus",
                        lambda seed, bonus=0, penalty=0: 88)
    r = roll_check("pc_1", "侦查", 50, CheckDifficulty.REGULAR, seed=7,
                   bonus=1, penalty=2)
    assert r.roll == 88 and r.bonus == 0 and r.penalty == 1        # net = -1

def test_bonus_note_text():
    assert bonus_note(0, 0) == ""
    assert bonus_note(1, 0) == "（奖励骰 ×1） "
    assert bonus_note(0, 2) == "（惩罚骰 ×2） "
    assert bonus_note(1, 1) == "（奖励骰 ×1，惩罚骰 ×1） "
