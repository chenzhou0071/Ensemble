from app.rules.character import Character, make_default_character

def test_skill_lookup_falls_back_to_attribute():
    c = Character(id="c1", name="张探员", player_id="p1",
                  attributes={"力量": 60, "意志": 50}, skills={"侦查": 70}, hp=10, max_hp=10)
    assert c.skill_value("侦查") == 70
    assert c.skill_value("力量") == 60
    assert c.skill_value("不存在") == 0

def test_default_character_is_playable():
    c = make_default_character("p1", "张探员")
    assert c.skill_value("侦查") >= 40 and c.hp == c.max_hp
