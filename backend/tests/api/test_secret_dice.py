"""暗骰可见性：玩家通道收不到 secret 骰子事件，但 L2 落库完整、重连回放过滤。"""
import asyncio
from dataclasses import asdict
from pathlib import Path

import pytest

from app.api.app import AppDeps
from app.api.session import SessionManager
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]

OPENING_DECIDE = ('{"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],'
                  ' "scene_transition": null, "memory_queries": []}')


def decide(char_id: str, skill: str, secret: bool) -> str:
    flag = "true" if secret else "false"
    return ('{"intent_summary": "行动", "checks": ['
            f'{{"actor": "{char_id}", "skill": "{skill}", "difficulty": "regular",'
            f' "secret": {flag}}}],'
            ' "proactive_npc_triggers": [], "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


@pytest.fixture
def solo(tmp_path):
    engine = make_engine(str(tmp_path / "secret.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "secret.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        extractor_model="qwen-extract")   # 摘要隔离：后台线程不抢脚本
    campaign = repo.create_campaign("misty_hollow", "暗骰")
    player = repo.add_player(campaign.id, "张三")
    char = make_default_character(player.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    return repo, settings, campaign, player, char


async def collect(sub, predicate, timeout=8.0):
    """以玩家身份订阅后收集事件；超时未见 predicate 即失败。"""
    events = []
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            evt = await asyncio.wait_for(sub.queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        events.append(evt)
        if predicate(events):
            return events
    raise AssertionError(f"condition not met; got {[e.type for e in events]}")


def collecting_turn(turn_id: int):
    return lambda evts: any(e.type == "turn" and e.payload.get("phase") == "collecting"
                            and e.payload.get("turn_id") == turn_id for e in evts)


async def test_secret_dice_hidden_from_players_but_kept_in_l2(solo):
    repo, settings, campaign, player, char = solo
    factory = script_factory([
        OPENING_DECIDE, "雾气笼罩着广场。",
        decide(char.id, "聆听", secret=True), "你听见井底传来若有若无的水声。",
        decide(char.id, "侦查", secret=False), "你在井边石缝里找到一枚铜扣。",
    ])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)

    sub = session.bus.subscribe(player.id)      # 以玩家身份订阅：只应收到可见事件
    try:
        assert await manager.handle_submit(campaign.id, player.id, "我侧耳倾听井底") == "accepted"
        round1 = await collect(sub, collecting_turn(2))
        assert not any(e.type == "dice" for e in round1)      # 暗骰不达玩家

        rows = repo.list_dice_records(campaign.id, campaign.active_branch_id)
        assert len(rows) == 1 and rows[0].secret is True      # 但 L2 完整落库
        events = repo.list_events(campaign.id, campaign.active_branch_id, types=["check"])
        assert events[0].visibility == "gm"

        assert await manager.handle_submit(campaign.id, player.id, "我检查井边石缝") == "accepted"
        round2 = await collect(sub, collecting_turn(3))
        dice = [e for e in round2 if e.type == "dice"]
        assert len(dice) == 1 and dice[0].payload["skill"] == "侦查"   # 明骰照常可见

        snap = manager.resync_payload(session)                # 重连回放不含暗骰
        assert [d["skill"] for d in snap["dice"]] == ["侦查"]
    finally:
        session.bus.unsubscribe(sub)
        await manager.close()
