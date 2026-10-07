"""SQLite 引擎与建表。"""
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel


def make_engine(sqlite_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{sqlite_path}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """旧表缺列时补列（SQLModel.create_all 不会修改已存在的表）。"""
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    if rows and column not in {r[1] for r in rows}:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def migrate_schema(engine: Engine) -> None:
    """轻量迁移清单：每列一行，幂等可重复执行。"""
    with engine.begin() as conn:
        _ensure_column(conn, "dicerecordrow", "secret",
                       "secret BOOLEAN NOT NULL DEFAULT 0")
        _ensure_column(conn, "campaign", "owner_client_id",
                       "owner_client_id VARCHAR NOT NULL DEFAULT ''")
        _ensure_column(conn, "dicerecordrow", "bonus",
                       "bonus INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "dicerecordrow", "penalty",
                       "penalty INTEGER NOT NULL DEFAULT 0")


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    migrate_schema(engine)
