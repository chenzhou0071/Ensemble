from copy import deepcopy
from app.content.schema import Module, Scene
from app.content.validate import validate_module

BASE = {
    "meta": {"id": "t1", "title": "测试"},
    "opening": {"narration": "开场", "scene_id": "gate"},
    "scenes": [
        {"id": "gate", "name": "村口", "npcs": ["guard"], "exits": ["tavern"], "clues": []},
        {"id": "tavern", "name": "酒馆", "npcs": [], "exits": [], "clues": ["c1"]},
    ],
    "npcs": [{"id": "guard", "name": "王守卫", "persona": "多疑"}],
    "clues": [{"id": "c1", "content": "传闻", "unlocks": ["scene:tavern"]}],
    "endings": [{"id": "e1", "scene": "tavern", "condition": "真相"}],
}

def mod():
    return Module.model_validate(deepcopy(BASE))

def test_valid_module_has_no_issues():
    assert validate_module(mod()) == []

def test_duplicate_scene_id():
    d = mod()
    d.scenes[1].id = "gate"
    assert any("duplicate scene id" in e for e in validate_module(d))

def test_missing_scene_reference_in_exits():
    d = mod()
    d.scenes[0].exits = ["nowhere"]
    assert any("exit target not found" in e for e in validate_module(d))

def test_missing_npc_reference():
    d = mod()
    d.scenes[0].npcs = ["ghost"]
    assert any("scene npc not found" in e for e in validate_module(d))

def test_missing_clue_reference_in_scene():
    d = mod()
    d.scenes[1].clues = ["c9"]
    assert any("scene clue not found" in e for e in validate_module(d))

def test_bad_clue_unlock_format_and_target():
    d = mod()
    d.clues[0].unlocks = ["castle:x"]
    assert any("bad unlock format" in e for e in validate_module(d))
    d.clues[0].unlocks = ["scene:nowhere"]
    assert any("unlock target not found" in e for e in validate_module(d))

def test_opening_scene_must_exist():
    d = mod()
    d.opening.scene_id = "void"
    assert any("opening scene not found" in e for e in validate_module(d))

def test_unreachable_scene_detected():
    d = mod()
    d.scenes.append(Scene(id="island", name="孤岛"))
    assert any("unreachable scene: island" in e for e in validate_module(d))

def test_ending_scene_must_exist_and_be_reachable():
    d = mod()
    d.scenes.append(Scene(id="island", name="孤岛"))
    d.endings[0].scene = "island"
    assert any("ending scene unreachable: island" in e for e in validate_module(d))
