import asyncio
import time
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
TURN_DECIDE = ('{"intent_summary": "调查", "checks": [], "proactive_npc_triggers": [],'
               ' "scene_transition": null, "memory_queries": []}')


def script_factory(items):
    """按模型名消耗脚本；每次 chat 新建 FakeLLM（与 LLMClient 的工厂调用方式一致）。

    摘要（extractor 角色）在后台线程调用，用独立模型名隔离：
    未知模型抛 AssertionError 由后台队列吞掉，不消耗主脚本。
    """
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if q is None:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)] if q else [])

    return factory


@pytest.fixture
def room(tmp_path):
    engine = make_engine(str(tmp_path / "api.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "api.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        extractor_model="qwen-extract",   # 摘要隔离：后台线程不抢脚本
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=3.0)
    campaign = repo.create_campaign("misty_hollow", "会话测试")
    player = repo.add_player(campaign.id, "张三")
    char = make_default_character(player.id, "张三")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    return repo, settings, campaign, player


async def collect_until(sub, predicate, timeout=8.0):
    """收集订阅队列事件直到 predicate(events) 为真（调用方负责订阅与退订）。"""
    events = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            evt = await asyncio.wait_for(
                sub.queue.get(), timeout=max(deadline - time.time(), 0.01))
        except asyncio.TimeoutError:
            break
        events.append(evt)
        if predicate(events):
            return events
    raise AssertionError(f"condition not met; got {[e.type for e in events]}")


async def test_opening_then_round_trip(room):
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。",
                              TURN_DECIDE, "你蹲下查看井边。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    assert session.buffer.phase == "collecting"

    sub = session.bus.subscribe("__test__")      # 先订阅再提交：actor 广播不遗漏
    try:
        status = await manager.handle_submit(campaign.id, player.id, "我绕到喷泉后面")
        assert status == "accepted"
        events = await collect_until(sub, lambda evts: any(
            e.type == "turn" and e.payload.get("phase") == "collecting"
            and e.payload.get("turn_id") == 2 for e in evts))
    finally:
        session.bus.unsubscribe(sub)
    assert any(e.type == "state" for e in events)
    assert any(e.type == "actor" for e in events)
    assert session.buffer.phase == "collecting"
    await manager.close()


async def test_state_payload_lists_only_acquainted_npcs(room):
    """已结识人物 = 叙事中出现过台词的 NPC（说过话 = 认识，含开场叙事；用户需求 2026-10-03）。

    GM 台词走 [[npc:id]]...[[/npc]] 标记语法（parse_segments 解析为 npc 分段）；
    没开过口的 NPC 不进名单。
    """
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。",
                              TURN_DECIDE, "[[npc:elder]]你们终于来了。[[/npc]]"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    assert manager.resync_payload(session)["known_npcs"] == []    # 开场无台词：无人开口

    sub = session.bus.subscribe("__test__")
    try:
        status = await manager.handle_submit(campaign.id, player.id, "我环顾四周")
        assert status == "accepted"
        events = await collect_until(sub, lambda evts: any(
            e.type == "turn" and e.payload.get("phase") == "collecting"
            and e.payload.get("turn_id") == 2 for e in evts))
    finally:
        session.bus.unsubscribe(sub)
    states = [e for e in events if e.type == "state"]
    assert states and states[-1].payload["known_npcs"] == ["elder"]   # 开口后进名单
    await manager.close()


async def test_single_player_window_never_auto_closes_on_timeout(room):
    """单人挂机不超时：窗口超时已过仍停留在 collecting，不产生空跑回合（用户需求 2026-10-03）。"""
    repo, settings, campaign, player = room      # turn_window_seconds=3.0
    factory = script_factory([OPENING_DECIDE, "雾气笼罩着广场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    assert session.buffer.phase == "collecting"

    await asyncio.sleep(3.5)                     # 已超过 3.0s 窗口
    assert session.buffer.phase == "collecting"
    snap = session.graph.get_state(session.config)
    assert int((snap.values or {}).get("turn_id", 0)) == 1   # 未空跑推进
    await manager.close()


async def test_ensure_started_is_idempotent(room):
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "开场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    seq = session.bus.current_seq
    again = await manager.ensure_started(campaign.id)
    assert again is session and again.bus.current_seq == seq   # 不重复驱动、不重复计费
    await manager.close()


async def test_branch_switch_reassembles_and_reopens(room):
    repo, settings, campaign, player = room
    factory = script_factory([OPENING_DECIDE, "开场。",
                              OPENING_DECIDE, "新分支开场。"])
    manager = SessionManager(AppDeps(settings=settings, repo=repo, model_factory=factory))
    session = await manager.ensure_started(campaign.id)
    old_bus = session.bus

    repo.create_branch(campaign.id, "alt", fork_turn_id=0,
                       parent_branch_id=campaign.active_branch_id)
    repo.switch_branch(campaign.id, f"{campaign.id}@alt")
    await manager.on_branch_switch(campaign.id)

    new = manager.get(campaign.id)
    assert new is not session and new.bus is old_bus
    assert new.branch_id == f"{campaign.id}@alt"
    assert new.buffer.phase == "collecting"      # 无 checkpoint 的分支自动全新开场
    await manager.close()
