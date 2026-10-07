import pytest

from app.rules.combat import parse_damage_dice, resolve_attack, roll_damage


def test_parse_damage_dice_forms():
    assert parse_damage_dice("1d6") == (1, 6, 0)
    assert parse_damage_dice("2d4+1") == (2, 4, 1)
    assert parse_damage_dice("d8") == (1, 8, 0)              # N 可省略


@pytest.mark.parametrize("bad", ["", "1d", "abc", "1d6-2", "3x6"])
def test_parse_damage_dice_rejects(bad):
    with pytest.raises(ValueError):
        parse_damage_dice(bad)


def test_roll_damage_deterministic_and_in_range():
    for s in range(50):
        assert roll_damage(s, "1d6") == roll_damage(s, "1d6")
        assert 1 <= roll_damage(s, "1d6") <= 6
        assert 3 <= roll_damage(s, "2d4+1") <= 9


def test_resolve_attack_reproducible():
    a = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", 42)
    b = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", 42)
    assert a == b


def test_hit_iff_attack_succeeds_and_defense_fails():
    for s in range(300):
        o = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", s)
        assert o.hit == (o.attack.success and not o.defense.success)
        if not o.hit:
            assert o.damage == 0


def test_damage_range_when_hit():
    hits = [o for o in (resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", s)
                        for s in range(300)) if o.hit]
    assert hits and all(1 <= o.damage <= 6 for o in hits)


def test_bonus_passed_to_attack_check():
    o = resolve_attack("pc_1", "力量", 60, "whisperer", 45, "1d6", 123, bonus=2)
    assert o.attack.bonus == 2 and o.attack.penalty == 0
