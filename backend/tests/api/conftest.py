from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def client(tmp_path):
    engine = make_engine(str(tmp_path / "api.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "api.db"),
                        modules_dir=str(ROOT / "modules"))
    return TestClient(create_app(AppDeps(settings=settings, repo=repo))), repo
