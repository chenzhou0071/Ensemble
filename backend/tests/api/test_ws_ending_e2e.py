"""端到端验收：misty_hollow 三回合全流程（开场 → 检定/线索 → 结局）+ 重连回放。

用真实 WS 协议 + FakeLLM 脚本，验证 M3 各组件在装配后的集成行为；
若本文件失败，优先怀疑是集成缝隙而非单元缺陷——这正是本任务的价值。
"""
import json
from dataclasses import asdict
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import AppDeps, create_app
from app.config import Settings
from app.llm.fakes import FakeLLM
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

ROOT = Path(__file__).resolve().parents[3]


def script_factory(items):
    """按模型名消耗脚本；每次 chat/chat_stream 新建 FakeLLM。"""
    queues = {"qwen3.8-flash": list(items)}

    def factory(model, base_url, api_key):
        q = queues.get(model)
        if not q:
            raise AssertionError(f"unexpected model call: {model}")
        return FakeLLM([q.pop(0)])

    return factory


def make_script(char_id: str) -> list[str]:
    """六条 qwen3.8-flash 脚本：回合0 decide/narrate → 回合1 decide（检定+线索）/narrate
    → 回合2 decide（结局）/narrate。检定 actor 用动态角色 id。"""
    open_decide = json.dumps({"intent_summary": "开场", "checks": [],
                              "proactive_npc_triggers": [], "scene_transition": None,
                              "memory_queries": []})
    turn1_decide = json.dumps({"intent_summary": "查看公告栏",
                               "checks": [{"actor": char_id, "skill": "侦查",
                                           "difficulty": "regular"}],
                               "proactive_npc_triggers": [], "scene_transition": None,
                               "memory_queries": [],
                               "clues_revealed": ["clue_missing"]})
    ending_decide = json.dumps({"intent_summary": "终结旧约", "checks": [],
                                "proactive_npc_triggers": [], "scene_transition": None,
                                "memory_queries": [], "ending_reached": "ending_break"})
    return [open_decide, "暮色把雾霭镇压得很低，无面的神像俯视着广场。",
            turn1_decide, "公告栏上贴着泛黄的寻人启事：学徒小满，三个月前失踪。",
            ending_decide, "石台在轰鸣中崩塌，缠绕镇子的低语骤然停止。"]


def build_env(tmp_path, script=None, campaign=None):
    """构建应用环境；campaign 传入时复用既有战役（模拟重开服务：同库重建）。"""
    engine = make_engine(str(tmp_path / "e2e.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    settings = Settings(sqlite_path=str(tmp_path / "e2e.db"),
                        modules_dir=str(ROOT / "modules"),
                        pricing_path=str(ROOT / "config" / "pricing.yaml"),
                        extractor_model="qwen-extract",  # 摘要隔离：后台线程不抢脚本
                        single_player_debounce_seconds=0.1,
                        turn_window_seconds=10.0)
    if campaign is None:
        campaign = repo.create_campaign("misty_hollow", "端到端")
        player = repo.add_player(campaign.id, "张三")
        char = make_default_character(player.id, "张三")
        repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id,
                              asdict(char))
    else:
        player = repo.list_players(campaign.id)[0]
        char = make_default_character(player.id, player.display_name)
    deps = AppDeps(settings=settings, repo=repo,
                   model_factory=script_factory(script if script is not None
                                                else make_script(char.id)))
    return create_app(deps), repo, campaign, player, char


def pump_until(ws, collected, predicate, limit=400):
    """持续接收事件直到 predicate(collected) 为真；全程断言 seq 严格单调。"""
    last_seq = collected[-1]["seq"] if collected else 0
    for _ in range(limit):
        evt = json.loads(ws.receive_text())
        assert evt["seq"] > last_seq, f"seq must strictly increase: {evt['seq']}"
        last_seq = evt["seq"]
        collected.append(evt)
        if predicate(collected):
            return
    raise AssertionError(f"timeout; got {[e['type'] for e in collected]}")


def _collecting(turn_id):
    def check(evts):
        return any(e["type"] == "turn" and e["payload"].get("phase") == "collecting"
                   and e["payload"].get("turn_id") == turn_id for e in evts)
    return check


def test_full_campaign_playthrough_to_ending(tmp_path):
    app, repo, campaign, player, char = build_env(tmp_path)
    events: list[dict] = []
    with TestClient(app) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            pump_until(ws, events, _collecting(1))          # 回合 0：开场驱动后开窗
            assert any(e["type"] == "token" for e in events)
            assert any(e["type"] == "scene" and e["payload"]["scene_id"] == "square"
                       for e in events)
            assert any(e["type"] == "state" for e in events)

            ws.send_text(json.dumps({"type": "input", "text": "我凑近公告栏查看启事"}))
            pump_until(ws, events, _collecting(2))          # 回合 1：检定与线索推送
            assert any(e["type"] == "dice" and e["payload"]["actor"] == char.id
                       for e in events)
            assert any(e["type"] == "clue"
                       and e["payload"]["clue_id"] == "clue_missing" for e in events)

            ws.send_text(json.dumps({"type": "input", "text": "我推倒石台，终结旧约"}))
            pump_until(ws, events, lambda evts: any(     # 回合 2：结局收束，图终止
                e["type"] == "turn" and e["payload"].get("phase") == "ended"
                for e in evts))
            ended = [e for e in events if e["type"] == "turn"
                     and e["payload"].get("phase") == "ended"]
            assert ended[-1]["payload"]["ending_reached"] == "ending_break"

        detail = client.get(f"/api/campaigns/{campaign.id}").json()   # REST 回查落库
        assert [c["clue_id"] for c in detail["clues_revealed"]] == ["clue_missing"]
        assert detail["scene_id"] == "square"


def test_reconnect_replays_full_history_and_can_continue(tmp_path):
    app, repo, campaign, player, char = build_env(tmp_path)
    url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
    with TestClient(app) as client:
        with client.websocket_connect(url) as ws:           # 首次连接：走完回合 0/1
            events: list[dict] = []
            pump_until(ws, events, _collecting(1))
            ws.send_text(json.dumps({"type": "input", "text": "我凑近公告栏查看启事"}))
            pump_until(ws, events, _collecting(2))

        replayed: list[dict] = []                           # F5 刷新：resume_from=0 全量回放
        with client.websocket_connect(url + "&resume_from=0") as ws2:
            pump_until(ws2, replayed, lambda evts: any(
                e["type"] == "clue" and e["payload"]["clue_id"] == "clue_missing"
                for e in evts))
            assert replayed[0]["seq"] == 1 and replayed[0]["type"] == "turn"
            types = {e["type"] for e in replayed}
            assert {"token", "dice", "clue", "state", "turn"} <= types
            # 全量回放段：骰子事件带 replay 标记（前端据此只回填日志、不重播动画）
            dice_replayed = [e for e in replayed if e["type"] == "dice"]
            assert dice_replayed and all(e.get("replay") is True for e in dice_replayed)

            ws2.send_text(json.dumps({"type": "input", "text": "我推倒石台"}))   # 重连后继续玩
            pump_until(ws2, replayed, lambda evts: any(
                e["type"] == "turn" and e["payload"].get("phase") == "ended"
                for e in evts))
            ended = [e for e in replayed if e["type"] == "turn"
                     and e["payload"].get("phase") == "ended"]
            assert ended[-1]["payload"]["ending_reached"] == "ending_break"
            # 实时事件（本回合新产生）不带 replay 标记
            assert "replay" not in ended[-1]


def test_reenter_after_backend_restart_restores_state(tmp_path):
    """重开后端后重进存档：首连即补推权威状态（角色/历史叙事/场景/线索），
    无需等到下一次输入驱动回合。"""
    app, repo, campaign, player, char = build_env(tmp_path)
    url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
    with TestClient(app) as client:
        with client.websocket_connect(url) as ws:
            events: list[dict] = []
            pump_until(ws, events, _collecting(1))
            ws.send_text(json.dumps({"type": "input", "text": "我凑近公告栏查看启事"}))
            pump_until(ws, events, _collecting(2))

    # 模拟后端重启：同一数据库重建应用（内存会话与事件总线全部丢失）
    app2, *_ = build_env(tmp_path, campaign=campaign)
    with TestClient(app2) as client2:
        replayed: list[dict] = []
        with client2.websocket_connect(url + "&resume_from=0") as ws2:
            pump_until(ws2, replayed, _collecting(2))

    states = [e for e in replayed if e["type"] == "state"]
    assert states, "重开后首连应收到权威状态快照"
    payload = states[-1]["payload"]
    assert len(payload["characters"]) == 1                  # 角色信息恢复
    assert payload["segments"], "历史叙事应随状态恢复（旧文字立即可见）"
    assert [c["clue_id"] for c in payload["clues_revealed"]] == ["clue_missing"]
    assert any(e["type"] == "scene" and e["payload"]["scene_id"] == "square"
               for e in replayed), "场景（含 NPC 列表）应恢复"
    assert any(e["type"] == "dice" for e in replayed), "骰子日志应恢复"
    assert all(e.get("replay") is True for e in replayed), "恢复事件均属回放（不重播动画）"


MOVE_SCRIPT = [
    json.dumps({"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],
                "scene_transition": None, "memory_queries": []}),
    "暮色把雾霭镇压得很低，无面的神像俯视着广场。",
    json.dumps({"intent_summary": "前往白鹭旅店", "checks": [],
                "proactive_npc_triggers": [],
                "scene_transition": {"to_scene": "inn", "reason": "推门而入"},
                "memory_queries": []}),
    "你推门走进白鹭旅店，壁炉的暖意扑面而来。",
]


def test_scene_move_pushes_scene_event(tmp_path):
    """移动回合：apply_transition → post_turn 落 scene_changed → WS 推 scene（含 reason）。"""
    app, repo, campaign, player, char = build_env(tmp_path, script=MOVE_SCRIPT)
    events: list[dict] = []
    with TestClient(app) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            pump_until(ws, events, _collecting(1))             # 回合 0：开场（广场首推）
            assert any(e["type"] == "scene" and e["payload"]["scene_id"] == "square"
                       for e in events)
            ws.send_text(json.dumps({"type": "input", "text": "我推门走进白鹭旅店"}))
            pump_until(ws, events, lambda evts: any(     # 回合 1：场景切换推送新场景
                e["type"] == "scene" and e["payload"].get("scene_id") == "inn"
                for e in evts))
            moved = [e for e in events if e["type"] == "scene"
                     and e["payload"].get("scene_id") == "inn"]
            assert moved[-1]["payload"]["reason"] == "推门而入"
        detail = client.get(f"/api/campaigns/{campaign.id}").json()   # REST 回查落库
        assert detail["scene_id"] == "inn"


def test_dice_event_precedes_narration_tokens(tmp_path):
    """骰子先出：resolve_checks 掷骰后立即推送 dice 事件，先于同回合的叙事 token。"""
    app, repo, campaign, player, char = build_env(tmp_path)
    events: list[dict] = []
    with TestClient(app) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            pump_until(ws, events, _collecting(1))
            ws.send_text(json.dumps({"type": "input", "text": "我凑近公告栏查看启事"}))
            pump_until(ws, events, _collecting(2))
    start = next(i for i, e in enumerate(events) if e["type"] == "turn"
                 and e["payload"].get("phase") == "resolving"
                 and e["payload"].get("turn_id") == 1)
    dice_at = next(i for i in range(start, len(events)) if events[i]["type"] == "dice")
    token_at = next(i for i in range(start, len(events)) if events[i]["type"] == "token")
    assert dice_at < token_at, "骰子事件应先于叙事 token（骰子先出）"


FALLBACK_SCRIPT = [
    json.dumps({"intent_summary": "开场", "checks": [], "proactive_npc_triggers": [],
                "scene_transition": None, "memory_queries": []}),
    "暮色把雾霭镇压得很低。",
    json.dumps({"intent_summary": "查看公告栏",
                "checks": [{"actor": "pc_any", "skill": "侦查", "difficulty": "regular"}],
                "proactive_npc_triggers": [], "scene_transition": None,
                "memory_queries": []}),
    "公告栏上贴着泛黄的寻人启事。",
    "这不是合法 JSON", "仍然不是",
]


def test_fallback_does_not_replay_previous_dice(tmp_path):
    """失败不推进的回合：收口兜底不重播已推过的骰子（last_dice_id 增量去重）。"""
    app, repo, campaign, player, char = build_env(tmp_path, script=FALLBACK_SCRIPT)
    events: list[dict] = []
    with TestClient(app) as client:
        url = f"/ws/campaign/{campaign.id}?player_id={player.id}"
        with client.websocket_connect(url) as ws:
            pump_until(ws, events, _collecting(1))
            ws.send_text(json.dumps({"type": "input", "text": "查看公告栏"}))
            pump_until(ws, events, _collecting(2))             # 回合 1 成功（含检定）
            ws.send_text(json.dumps({"type": "input", "text": "我继续前进"}))
            pump_until(ws, events, lambda evts: any(           # 回合 2 决策失败 → fallback
                e["type"] == "error" for e in evts))
    dice_events = [e for e in events if e["type"] == "dice"]
    assert len(dice_events) == 1, f"骰子不应重播，实际收到 {len(dice_events)} 条"
