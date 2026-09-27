"""L2 领域库表模型：append-only + 版本化（branch_id + turn_id）。"""
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(SQLModel, table=True):
    id: str = Field(primary_key=True)
    module_id: str
    title: str
    active_branch_id: str
    created_at: datetime = Field(default_factory=_now)


class Branch(SQLModel, table=True):
    id: str = Field(primary_key=True)  # f"{campaign_id}@{name}"，同时是 LangGraph thread_id
    campaign_id: str = Field(index=True)
    name: str
    parent_branch_id: str | None = None
    fork_turn_id: int | None = None
    created_at: datetime = Field(default_factory=_now)


class Player(SQLModel, table=True):
    id: str = Field(primary_key=True)
    campaign_id: str = Field(index=True)
    display_name: str
    join_token: str


class CharacterStateRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    character_id: str = Field(index=True)
    data_json: str


class GameEventRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    seq: int
    type: str
    visibility: str = "all"
    payload_json: str
    created_at: datetime = Field(default_factory=_now)


class DiceRecordRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    actor: str
    skill: str
    skill_value: int
    difficulty: str
    roll: int
    level: str
    seed: int
    created_at: datetime = Field(default_factory=_now)


class StateSnapshotRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    turn_id: int
    data_json: str


class SummaryRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str = Field(index=True)
    upto_turn: int
    content: str
    created_at: datetime = Field(default_factory=_now)


class UsageRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    branch_id: str
    turn_id: int
    role: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    created_at: datetime = Field(default_factory=_now)
