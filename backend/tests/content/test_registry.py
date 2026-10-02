from pathlib import Path
import pytest
from app.content.registry import find_module_path, list_modules

TWO_MODULES = {
    "m_a.yaml": 'meta: { id: aaa, title: 甲 }\nopening: { narration: x, scene_id: s }\n'
                'scenes: [{ id: s, name: S, npcs: [], exits: [] }]\nnpcs: []\nclues: []\n'
                'endings: [{ id: e, scene: s, condition: c }]\n',
    "m_b.yaml": 'meta: { id: bbb, title: 乙 }\nopening: { narration: x, scene_id: s }\n'
                'scenes: [{ id: s, name: S, npcs: [], exits: [] }]\nnpcs: []\nclues: []\n'
                'endings: [{ id: e, scene: s, condition: c }]\n',
}

@pytest.fixture
def moddir(tmp_path):
    for name, text in TWO_MODULES.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path

def test_list_modules_sorted(moddir):
    mods = list_modules(str(moddir))
    assert [m["id"] for m in mods] == ["aaa", "bbb"]
    assert mods[0]["title"] == "甲" and Path(mods[0]["path"]).exists()

def test_find_module_path_missing_raises(moddir):
    assert find_module_path(str(moddir), "bbb").name == "m_b.yaml"
    with pytest.raises(KeyError):
        find_module_path(str(moddir), "nope")
