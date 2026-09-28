import pytest
from app.memory.base import MemoryEvent
from app.memory.journal import JournalMemory
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

@pytest.fixture
def env(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    repo = SqliteRepository(engine)
    campaign = repo.create_campaign("m", "t")
    return repo, campaign

def test_write_event_and_search(env):
    repo, campaign = env
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="clue", text="磨坊夜里传出哭声", turn_id=1))
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="npc", text="王守卫不喜欢陌生人", turn_id=1))
    hits = mem.search(campaign.id, campaign.active_branch_id, "磨坊 哭声")
    assert hits and "磨坊" in hits[0].text and hits[0].turn_id == 1

def test_search_no_match_returns_empty(env):
    repo, campaign = env
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, campaign.active_branch_id,
                    MemoryEvent(type="clue", text="无关内容", turn_id=1))
    assert mem.search(campaign.id, campaign.active_branch_id, "磨坊") == []

def test_get_context_includes_summary_and_recent(env):
    repo, campaign = env
    b = campaign.active_branch_id
    repo.append_summary(campaign.id, b, 3, "已有摘要")
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, b, MemoryEvent(type="note", text="最新事件", turn_id=4))
    ctx = mem.get_context(campaign.id, b)
    assert "已有摘要" in ctx and "最新事件" in ctx

def test_update_summaries_uses_summarizer_and_threshold(env):
    repo, campaign = env
    b = campaign.active_branch_id
    calls = []
    def summarizer(messages):
        calls.append(messages)
        return "压缩后的摘要"
    mem = JournalMemory(repo, summarizer=summarizer)
    for i in range(12):
        mem.write_event(campaign.id, b, MemoryEvent(type="note", text=f"事件{i}", turn_id=i // 3))
    mem.update_summaries(campaign.id, b, turn_id=3)
    assert repo.latest_summary(campaign.id, b).content == "压缩后的摘要"
    assert len(calls) == 1

def test_update_summaries_below_threshold_skips(env):
    repo, campaign = env
    b = campaign.active_branch_id
    repo.append_summary(campaign.id, b, 0, "旧摘要")
    mem = JournalMemory(repo)
    mem.write_event(campaign.id, b, MemoryEvent(type="note", text="一条新事件", turn_id=1))
    mem.update_summaries(campaign.id, b, turn_id=1)
    assert repo.latest_summary(campaign.id, b).content == "旧摘要"  # 未触发新摘要

def test_update_summaries_passes_prior_summary_to_summarizer(env):
    repo, campaign = env
    b = campaign.active_branch_id
    repo.append_summary(campaign.id, b, 0, "旧摘要")
    captured = []
    def summarizer(messages):
        captured.append(messages)
        return "新摘要"
    mem = JournalMemory(repo, summarizer=summarizer)
    for i in range(12):
        mem.write_event(campaign.id, b, MemoryEvent(type="note", text=f"事件{i}", turn_id=1 + i // 3))
    mem.update_summaries(campaign.id, b, turn_id=5)
    user_msg = captured[0][1]
    assert user_msg.role == "user"
    assert user_msg.content.startswith("已有摘要：旧摘要")
    assert "新事件：" in user_msg.content
