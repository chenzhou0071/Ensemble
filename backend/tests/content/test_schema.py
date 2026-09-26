import pytest
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

def test_lookup_missing_raises_key_error():
    m = Module.model_validate(MINIMAL)
    with pytest.raises(KeyError):
        m.scene("nowhere")
