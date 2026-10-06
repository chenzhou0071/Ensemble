"""轻量迁移：历史库（缺列）经 init_db 后可用新字段，且幂等。"""
import sqlite3

from sqlmodel import Session

from app.storage.db import init_db, make_engine
from app.storage.models import Campaign, DiceRecordRow


def test_init_db_migrates_legacy_dice_record_table(tmp_path):
    db = tmp_path / "legacy_dice.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE dicerecordrow ("
        "id INTEGER NOT NULL PRIMARY KEY, campaign_id VARCHAR NOT NULL,"
        "branch_id VARCHAR NOT NULL, turn_id INTEGER NOT NULL, actor VARCHAR NOT NULL,"
        "skill VARCHAR NOT NULL, skill_value INTEGER NOT NULL,"
        "difficulty VARCHAR NOT NULL, roll INTEGER NOT NULL, level VARCHAR NOT NULL,"
        "seed INTEGER NOT NULL, created_at DATETIME NOT NULL)")
    conn.execute("INSERT INTO dicerecordrow VALUES "
                 "(1, 'c1', 'c1@main', 1, 'pc_1', '侦查', 50, 'regular', 23, 'hard',"
                 " 7, '2026-01-01 00:00:00')")
    conn.commit()
    conn.close()

    engine = make_engine(str(db))
    init_db(engine)
    init_db(engine)                                    # 幂等：重复调用不报错

    with Session(engine) as s:
        row = s.get(DiceRecordRow, 1)
        assert row is not None and row.secret is False  # 历史行补列为默认 false


def test_init_db_fresh_database_has_secret_column(tmp_path):
    engine = make_engine(str(tmp_path / "fresh.db"))
    init_db(engine)
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(dicerecordrow)")}
    assert "secret" in cols


def test_init_db_migrates_legacy_campaign_owner_column(tmp_path):
    db = tmp_path / "legacy_owner.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE campaign ("
        "id VARCHAR NOT NULL PRIMARY KEY, module_id VARCHAR NOT NULL,"
        "title VARCHAR NOT NULL, active_branch_id VARCHAR NOT NULL,"
        "created_at DATETIME NOT NULL)")
    conn.execute("INSERT INTO campaign VALUES "
                 "('c1', 'misty_hollow', '旧战役', 'c1@main', '2026-01-01 00:00:00')")
    conn.commit()
    conn.close()

    engine = make_engine(str(db))
    init_db(engine)
    init_db(engine)                                     # 幂等

    with Session(engine) as s:
        row = s.get(Campaign, "c1")
        assert row is not None and row.owner_client_id == ""   # 历史行补列为默认空
