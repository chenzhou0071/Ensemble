import pytest
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository

@pytest.fixture
def repo(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    init_db(engine)
    return SqliteRepository(engine)

def test_create_campaign_makes_main_branch(repo):
    c = repo.create_campaign("misty-hollow", "迷雾谷")
    branches = repo.list_branches(c.id)
    assert len(branches) == 1
    main = branches[0]
    assert main.name == "main"
    assert main.id == f"{c.id}@main"
    assert c.active_branch_id == main.id

def test_thread_id_matches_branch_id(repo):
    c = repo.create_campaign("m", "t")
    b = repo.list_branches(c.id)[0]
    assert repo.thread_id_for(b) == b.id

def test_fork_branch_and_switch(repo):
    c = repo.create_campaign("m", "t")
    main = repo.list_branches(c.id)[0]
    fork = repo.create_branch(c.id, "b2", fork_turn_id=5, parent_branch_id=main.id)
    assert fork.id == f"{c.id}@b2" and fork.fork_turn_id == 5
    c2 = repo.switch_branch(c.id, fork.id)
    assert c2.active_branch_id == fork.id
    assert len(repo.list_branches(c.id)) == 2
