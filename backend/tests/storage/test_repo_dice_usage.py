import json
import pytest
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

@pytest.fixture
def repo(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    return SqliteRepository(engine)

@pytest.fixture
def campaign(repo):
    return repo.create_campaign("m", "t")

def test_dice_record_persists_seed(repo, campaign):
    b = campaign.active_branch_id
    repo.add_dice_record(campaign.id, b, 1, "pc_1", "侦查", 50, "regular", 23, "hard", 987654321)
    rows = repo.list_dice_records(campaign.id, b, turn_id=1)
    assert len(rows) == 1 and rows[0].seed == 987654321 and rows[0].roll == 23

def test_usage_totals(repo, campaign):
    b = campaign.active_branch_id
    repo.record_usage(campaign.id, b, 1, "gm", "qwen-plus", 100, 200, 0.002, 900)
    repo.record_usage(campaign.id, b, 1, "npc", "deepseek-chat", 50, 80, 0.0005, 700)
    repo.record_usage(campaign.id, b, 2, "gm", "qwen-plus", 10, 20, 0.0002, 800)
    assert repo.turn_token_total(campaign.id, b, 1) == 430
    assert repo.turn_token_total(campaign.id, b, 2) == 30
    assert abs(repo.campaign_cost_total(campaign.id) - 0.0027) < 1e-9

def test_fork_history_concatenates_parent_upto_fork_turn(repo, campaign):
    main = campaign.active_branch_id
    repo.add_event(campaign.id, main, 0, "narration", {"text": "开场"})
    repo.add_event(campaign.id, main, 1, "narration", {"text": "主分支 turn1"})
    fork = repo.create_branch(campaign.id, "b2", fork_turn_id=0, parent_branch_id=main)
    repo.add_event(campaign.id, fork.id, 1, "narration", {"text": "分叉 turn1"})
    texts = [json.loads(e.payload_json)["text"] for e in repo.branch_history_events(campaign.id, fork.id)]
    assert texts == ["开场", "分叉 turn1"]

def test_branch_events_are_isolated(repo, campaign):
    main = campaign.active_branch_id
    fork = repo.create_branch(campaign.id, "b2", fork_turn_id=0, parent_branch_id=main)
    repo.add_event(campaign.id, main, 1, "narration", {"text": "只属于 main"})
    assert repo.list_events(campaign.id, fork.id) == []
