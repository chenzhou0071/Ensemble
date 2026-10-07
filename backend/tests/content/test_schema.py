import pytest
from copy import deepcopy

from pydantic import ValidationError

from app.content.schema import Module

MINIMAL = {
    "meta": {"id": "t1", "title": "测试模组"},
    "opening": {"narration": "你们来到村口。", "scene_id": "gate"},
    "scenes": [{"id": "gate", "name": "村口", "npcs": ["guard"], "exits": ["tavern"], "clues": []},
               {"id": "tavern", "name": "酒馆", "exits": []}],
    "npcs": [{"id": "guard", "name": "王守卫", "persona": "多疑"}],
    "clues": [],
    "endings": [{"id": "e1", "scene": "tavern", "condition": "揭开真相"}],
}

def test_parse_minimal_module_with_defaults():
    m = Module.model_validate(MINIMAL)
    assert m.meta.system == "coc-lite"
    assert m.npcs[0].initial_attitude == 50
    assert m.scenes[0].exits == ["tavern"]

def test_lookup_helpers():
    m = Module.model_validate(MINIMAL)
    assert m.scene("gate").name == "村口"
    assert m.npc("guard").name == "王守卫"
    assert m.ending("e1").scene == "tavern"

def test_lookup_missing_raises_key_error():
    m = Module.model_validate(MINIMAL)
    with pytest.raises(KeyError):
        m.scene("nowhere")
    with pytest.raises(KeyError):
        m.npc("nowhere")
    with pytest.raises(KeyError):
        m.ending("nowhere")


def test_npc_combat_optional_and_parsed():
    m = Module.model_validate(MINIMAL)
    assert m.npc("guard").combat is None                     # 无战斗块：不可被攻击
    data = deepcopy(MINIMAL)
    data["npcs"][0]["combat"] = {"defense": 45, "damage": "1d6", "hp": 12}
    m2 = Module.model_validate(data)
    assert m2.npc("guard").combat.hp == 12
    assert m2.npc("guard").combat.defense == 45


def test_npc_combat_rejects_bad_damage_expression():
    data = deepcopy(MINIMAL)
    data["npcs"][0]["combat"] = {"damage": "1d6-2"}
    with pytest.raises(ValidationError):
        Module.model_validate(data)
