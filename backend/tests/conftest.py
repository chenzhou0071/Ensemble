import sys
from pathlib import Path

# 确保 `import harness.replay` 稳定可用（不依赖 pytest 的 prepend 行为）
sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def pytest_addoption(parser):
    parser.addoption("--record", action="store_true", default=False,
                     help="使用真实 LLM 重录回放基线（需要 API key 与网络）")


@pytest.fixture
def record_mode(pytestconfig) -> bool:
    return bool(pytestconfig.getoption("--record"))
