"""SQLite 引擎与建表。"""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel


def make_engine(sqlite_path: str) -> Engine:
    return create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
