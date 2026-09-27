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

def test_events_sequenced_and_filterable(repo, campaign):
    b = campaign.active_branch_id
    assert repo.add_event(campaign.id, b, 0, "narration", {"text": "开场"}) == 1
    assert repo.add_event(campaign.id, b, 1, "narration", {"text": "第一幕"}) == 2
    repo.add_event(campaign.id, b, 1, "check", {"text": "侦查成功"})
    evs = repo.list_events(campaign.id, b)
    assert [e.seq for e in evs] == [1, 2, 3]
    assert [e.turn_id for e in repo.list_events(campaign.id, b, upto_turn=0)] == [0]
    assert len(repo.list_events(campaign.id, b, types=["check"])) == 1
    assert json.loads(evs[0].payload_json)["text"] == "开场"

def test_versioned_state_reads(repo, campaign):
    b = campaign.active_branch_id
    repo.append_state(campaign.id, b, 0, {"scene_id": "gate"})
    repo.append_state(campaign.id, b, 3, {"scene_id": "tavern"})
    assert repo.get_state_at(campaign.id, b, 2)["scene_id"] == "gate"
    assert repo.get_state_at(campaign.id, b, 3)["scene_id"] == "tavern"
    assert repo.get_state_at(campaign.id, b, -1) is None

def test_versioned_character_reads(repo, campaign):
    b = campaign.active_branch_id
    repo.append_character(campaign.id, b, 0, "pc_1", {"hp": 10})
    repo.append_character(campaign.id, b, 3, "pc_1", {"hp": 6})
    repo.append_character(campaign.id, b, 0, "pc_2", {"hp": 10})
    assert repo.get_character_at(campaign.id, b, 2, "pc_1")["hp"] == 10
    assert repo.get_character_at(campaign.id, b, 3, "pc_1")["hp"] == 6
    assert sorted(c["hp"] for c in repo.list_characters_at(campaign.id, b, 2)) == [10, 10]

def test_summary_latest(repo, campaign):
    b = campaign.active_branch_id
    repo.append_summary(campaign.id, b, 3, "前三回合摘要")
    repo.append_summary(campaign.id, b, 6, "前六回合摘要")
    assert repo.latest_summary(campaign.id, b).upto_turn == 6
