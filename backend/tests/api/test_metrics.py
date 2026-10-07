"""GET /metrics：进程内快照（scope=process）+ DB usage 汇总。"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.obs.counters import get_counters, reset_counters
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


def test_metrics_snapshot_and_usage(client):
    reset_counters()
    c, repo = client
    repo.record_usage("c1", "c1@main", 1, "gm", "qwen3.8-flash", 100, 50, 0.0004, 120)
    get_counters().record_llm(ok=True)
    get_counters().record_turn(1500, npc_count=2)
    body = c.get("/metrics").json()
    assert body["scope"] == "process"
    assert body["llm"] == {"calls": 1, "failures": 0}
    assert body["turns"]["count"] == 1 and body["turns"]["p50_ms"] == 1500
    assert body["npc_activation"] == {"2": 1}
    assert body["usage"] == {"calls": 1, "tokens_in": 100,
                             "tokens_out": 50, "cost_usd": 0.0004}
