from app.rules.check import CheckDifficulty, SuccessLevel, roll_check

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
