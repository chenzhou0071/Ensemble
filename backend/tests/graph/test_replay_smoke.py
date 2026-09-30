"""整局脚本回放：确定性跑通开场 + 第一回合（零网络零 key）。"""
import os
from dataclasses import asdict
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import load_pricing, load_settings
from app.content.loader import load_module
from app.graph.main import build_game_graph
from app.llm.usage import BudgetGuard
from app.memory.journal import JournalMemory
from app.rules.character import make_default_character
from harness.replay import build_recording_client, build_replay_client, load_turn, save_turn

TESTS_DIR = Path(__file__).resolve().parents[1]          # backend/tests
ROOT = Path(__file__).resolve().parents[3]               # 仓库根
FIXTURE_DIR = TESTS_DIR / "fixtures" / "misty_hollow" / "smoke"
MODULES_DIR = ROOT / "modules"


def test_misty_hollow_module_is_valid():
    module = load_module(MODULES_DIR / "misty_hollow.yaml")  # 校验不过即抛
    assert len(module.scenes) >= 4 and len(module.npcs) >= 4
    assert module.opening.scene_id == "square"


def _setup(monkeypatch, repo, client):
    settings = load_settings()
    module = load_module(MODULES_DIR / "misty_hollow.yaml")
    campaign = repo.create_campaign(module.meta.id, "回放冒烟")
    char = make_default_character("p1", "调查员")
    repo.append_character(campaign.id, campaign.active_branch_id, 0, char.id, asdict(char))
    graph = build_game_graph(repo, module, JournalMemory(repo), client,
                             BudgetGuard(settings), MemorySaver())
    branch = repo.get_branch(campaign.active_branch_id)
    cfg = {"configurable": {"thread_id": repo.thread_id_for(branch)}}
    return settings, module, campaign, graph, cfg


def test_smoke_replay_offline(repo, monkeypatch):
    settings = load_settings()
    pricing = load_pricing(ROOT / "config" / "pricing.yaml")

    seeds = list(load_turn(FIXTURE_DIR / "turn_1.json").get("seeds", []))
    monkeypatch.setattr("app.graph.nodes.turn.new_seed", lambda: seeds.pop(0))

    client, replay = build_replay_client(
        settings, pricing, [FIXTURE_DIR / "turn_0.json", FIXTURE_DIR / "turn_1.json"],
        usage_sink=repo)
    _, module, campaign, graph, cfg = _setup(monkeypatch, repo, client)

    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",) and snap.values["turn_id"] == 1

    graph.invoke(Command(resume={"turn_id": 1, "inputs": [
        {"player_id": "p1", "character_id": "pc_p1", "text": "我向陈长老打听失踪的学徒"}],
        "skipped": []}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ("wait_input",)
    assert snap.values["turn_id"] == 2 and snap.values["error"] is None

    rows = repo.list_dice_records(campaign.id, campaign.active_branch_id, turn_id=1)
    assert len(rows) == 1 and rows[0].seed == 20260924 and rows[0].skill == "话术"

    assert [s["speaker"] for s in snap.values["narration_segments"]] == \
        ["gm", "npc:elder", "gm"]
    assert snap.values["npc_reactions"]["elder"]["speech"].startswith("三个月了")

    types = [e.type for e in repo.list_events(campaign.id, campaign.active_branch_id)]
    assert types.count("narration") == 2 and types.count("check") == 1
    assert replay.index == 6          # 全部录制响应按序精确消耗
    assert replay.calls[1]["model"] == "deepseek-flash"


def test_record_mode_writes_new_baseline(repo, monkeypatch, record_mode):
    """--record：真实调用并把新基线写回 fixtures（需 DASHSCOPE/DEEPSEEK key）。"""
    if not record_mode:
        pytest.skip("未启用 --record（默认回放零网络）")
    if not (os.environ.get("DASHSCOPE_API_KEY") and os.environ.get("DEEPSEEK_API_KEY")):
        pytest.skip("缺少 API key，无法录制")

    settings = load_settings()
    pricing = load_pricing(ROOT / "config" / "pricing.yaml")
    client, collected = build_recording_client(settings, pricing, usage_sink=repo)
    _, module, campaign, graph, cfg = _setup(monkeypatch, repo, client)

    graph.invoke({"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
                  "turn_id": 0, "player_inputs": []}, cfg)
    save_turn(FIXTURE_DIR / "turn_0.json", {"responses": collected, "seeds": []})
    assert collected, "未录制到任何响应"
