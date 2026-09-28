import pytest

from app.content.schema import Module

MINI_MODULE_DICT = {
    "meta": {"id": "mini", "title": "迷你模组"},
    "opening": {"narration": "开场叙述", "scene_id": "gate"},
    "scenes": [
        {"id": "gate", "name": "村口", "npcs": ["guard"], "exits": ["tavern"]},
        {"id": "tavern", "name": "酒馆", "npcs": ["barkeep"], "exits": []},
    ],
    "npcs": [
        {"id": "guard", "name": "王守卫", "persona": "多疑的老兵", "initial_attitude": 40},
        {"id": "barkeep", "name": "刘老板", "persona": "健谈的酒馆老板", "initial_attitude": 60},
    ],
    "clues": [],
    "endings": [{"id": "e1", "scene": "tavern", "condition": "揭开真相"}],
}

@pytest.fixture
def mini_module() -> Module:
    return Module.model_validate(MINI_MODULE_DICT)

@pytest.fixture
def repo(tmp_path):
    from app.storage.db import init_db, make_engine
    from app.storage.repo import SqliteRepository
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(engine)
    return SqliteRepository(engine)

@pytest.fixture
def campaign(repo):
    return repo.create_campaign("mini", "测试局")
