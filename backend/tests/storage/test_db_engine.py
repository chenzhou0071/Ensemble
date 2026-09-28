from app.storage.db import make_engine


def test_engine_enables_wal_and_busy_timeout(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
