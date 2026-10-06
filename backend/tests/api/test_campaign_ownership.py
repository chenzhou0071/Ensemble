"""战役归属：列表/详情/WS 三入口按 client_id 隔离；无主历史档兼容可见。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository
from ws_utils import ws_connect

ROOT = Path(__file__).resolve().parents[3]

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


@pytest.fixture
def world(tmp_path):
    engine = make_engine(str(tmp_path / "own.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "own.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        extractor_model="qwen-extract")   # 摘要隔离：后台线程不抢脚本
    app = create_app(AppDeps(settings=settings, repo=repo,
                             model_factory=script_factory(
                                 [OPENING_DECIDE, "雾气笼罩着广场。"] * 4)))
    with TestClient(app) as client:      # 挂 lifespan：启动装配 + 收尾清理
        yield client, repo


def create(c, title: str, client_id: str) -> str:
    return c.post("/api/campaigns",
                  json={"module_id": "misty_hollow", "title": title,
                        "player_name": "张三", "client_id": client_id}
                  ).json()["campaign_id"]


def test_list_shows_only_own_campaigns(world):
    c, _ = world
    alice = create(c, "爱丽丝的档", "alice")
    create(c, "鲍勃的档", "bob")
    rows = c.get("/api/campaigns?client_id=alice").json()
    assert [r["id"] for r in rows] == [alice]


def test_legacy_ownerless_campaign_visible_to_all(world):
    """升级前的历史档（无 owner）：任何浏览器可见（保护已有存档不消失）。"""
    c, repo = world
    legacy = repo.create_campaign("misty_hollow", "旧档").id     # 未传 owner
    assert [r["id"] for r in c.get("/api/campaigns?client_id=alice").json()] == [legacy]
    assert [r["id"] for r in c.get("/api/campaigns?client_id=bob").json()] == [legacy]


def test_list_without_client_id_hides_owned_campaigns(world):
    """缺省 client_id 只能看到无主档：owner 档不泄露给未标识客户端。"""
    c, _ = world
    create(c, "爱丽丝的档", "alice")
    assert c.get("/api/campaigns").json() == []


def test_detail_rejects_foreign_client(world):
    c, _ = world
    alice = create(c, "爱丽丝的档", "alice")
    assert c.get(f"/api/campaigns/{alice}?client_id=alice").status_code == 200
    assert c.get(f"/api/campaigns/{alice}?client_id=bob").status_code == 404
    assert c.get(f"/api/campaigns/{alice}").status_code == 404


def test_ws_rejects_foreign_client(world):
    c, repo = world
    bob = create(c, "鲍勃的档", "bob")
    player = repo.list_players(bob)[0]
    url = f"/ws/campaign/{bob}?player_id={player.id}&client_id=alice"
    with pytest.raises(WebSocketDisconnect):
        with ws_connect(c, url) as ws:
            ws.receive_text()


def test_ws_accepts_owner_client(world):
    """归属者连 WS：进入正常事件流（收到开场结算后的 collecting 窗口）。"""
    c, repo = world
    bob = create(c, "鲍勃的档", "bob")
    player = repo.list_players(bob)[0]
    url = f"/ws/campaign/{bob}?player_id={player.id}&client_id=bob"
    with ws_connect(c, url) as ws:
        for _ in range(50):
            evt = json.loads(ws.receive_text())
            if evt["type"] == "turn" and evt["payload"].get("phase") == "collecting":
                return
        raise AssertionError("no collecting window before stream end")
