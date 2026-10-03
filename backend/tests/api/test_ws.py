import json
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')
TURN_DECIDE = ('{"intent_summary": "调查", "checks": [], "proactive_npc_triggers": [],'
               ' "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    """按模型名消耗脚本；摘要（extractor 角色）在后台线程调用，
    用独立模型名隔离：未知模型抛 AssertionError 由后台队列吞掉（不消耗主脚本）。
    """
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if q is None:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)] if q else [])

    return factory


@pytest.fixture
def app(tmp_path):
    engine = make_engine(str(tmp_path / "ws.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "ws.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        extractor_model="qwen-extract",   # 摘要隔离：后台线程不抢脚本
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=3.0)
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。",
                              TURN_DECIDE, "你蹲下查看井边。"])
    deps = AppDeps(settings=settings, repo=repo, model_factory=factory)
    campaign = repo.create_campaign("misty_hollow", "联调")
    player = repo.add_player(campaign.id, "张三")
    char = make_default_character(player.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    return create_app(deps), campaign, player


def test_ws_full_round_trip(app):
    application, campaign, player = app
    last_seq = 0
    seen = set()
    with TestClient(application) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            turn_id = None
            while turn_id is None:                      # 收开场流直到窗口打开
                evt = json.loads(ws.receive_text())
                assert evt["seq"] > last_seq            # seq 严格单调
                last_seq = evt["seq"]
                seen.add(evt["type"])
                if evt["type"] == "turn" and evt["payload"].get("phase") == "collecting":
                    turn_id = evt["payload"]["turn_id"]
            assert turn_id == 1
            assert "token" in seen and "scene" in seen and "state" in seen

            ws.send_text(json.dumps({"type": "input", "text": "我绕到喷泉后面"}))

            got2 = False
            while not got2:                             # 等第二轮窗口
                evt = json.loads(ws.receive_text())
                assert evt["seq"] > last_seq
                last_seq = evt["seq"]
                if (evt["type"] == "turn" and evt["payload"].get("phase") == "collecting"
                        and evt["payload"].get("turn_id") == 2):
                    got2 = True
            assert got2


def test_ws_rejects_ghost_player(app):
    application, campaign, player = app
    with TestClient(application) as client:
        url = f"/ws/campaign/{campaign.id}?player_id=ghost"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url) as ws:
                ws.receive_text()
