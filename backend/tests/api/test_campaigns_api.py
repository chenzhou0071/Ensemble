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

def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}

def test_modules_listed(client):
    c, _ = client
    ids = [m["id"] for m in c.get("/api/modules").json()]
    assert "misty_hollow" in ids

def test_create_campaign_creates_player_and_character(client):
    c, repo = client
    r = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                       "title": "初探", "player_name": "张三"})
    assert r.status_code == 200
    data = r.json()
    assert data["campaign_id"] and data["player_id"] and data["character_id"]
    chars = repo.list_characters_at(data["campaign_id"], data["branch_id"], 10**9)
    assert chars[0]["name"] == "张三" and chars[0]["player_id"] == data["player_id"]

def test_get_campaign_detail(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "初探"}).json()["campaign_id"]
    r = c.get(f"/api/campaigns/{cid}")
    d = r.json()
    assert d["title"] == "初探" and d["scene_id"] == "square" and d["turn_id"] == 0
    assert len(d["players"]) == 1 and d["characters"]

def test_get_campaign_404(client):
    c, _ = client
    assert c.get("/api/campaigns/ghost").status_code == 404
