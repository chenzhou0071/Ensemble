from app.rules.dice import new_seed, roll_d100

def test_roll_is_deterministic_for_same_seed():
    assert roll_d100(42) == roll_d100(42)

def test_roll_within_range_for_many_seeds():
    assert all(1 <= roll_d100(s) <= 100 for s in range(1000))

def test_new_seed_within_64bit():
    s = new_seed()
    assert 0 <= s < 2**64

def test_new_seed_varies():
    assert new_seed() != new_seed()
