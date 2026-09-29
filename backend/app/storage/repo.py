"""L2 领域仓储：append-only、版本化、分支隔离。"""
import json
import uuid

from sqlmodel import Session, select

from app.storage.models import (Branch, Campaign, CharacterStateRow, DiceRecordRow,
                                GameEventRow, StateSnapshotRow, SummaryRow, UsageRow)


class SqliteRepository:
    def __init__(self, engine):
        self.engine = engine

    # ---------- campaigns & branches ----------

    def create_campaign(self, module_id: str, title: str) -> Campaign:
        campaign_id = uuid.uuid4().hex[:12]
        branch = Branch(id=f"{campaign_id}@main", campaign_id=campaign_id, name="main")
        campaign = Campaign(id=campaign_id, module_id=module_id, title=title,
                            active_branch_id=branch.id)
        with Session(self.engine) as s:
            s.add(branch)
            s.add(campaign)
            s.commit()
            s.refresh(campaign)
        return campaign

    def get_campaign(self, campaign_id: str) -> Campaign:
        with Session(self.engine) as s:
            c = s.get(Campaign, campaign_id)
        if c is None:
            raise KeyError(f"campaign not found: {campaign_id}")
        return c

    def get_branch(self, branch_id: str) -> Branch | None:
        with Session(self.engine) as s:
            return s.get(Branch, branch_id)

    def create_branch(self, campaign_id: str, name: str, fork_turn_id: int,
                      parent_branch_id: str) -> Branch:
        branch = Branch(id=f"{campaign_id}@{name}", campaign_id=campaign_id, name=name,
                        fork_turn_id=fork_turn_id, parent_branch_id=parent_branch_id)
        with Session(self.engine) as s:
            s.add(branch)
            s.commit()
            s.refresh(branch)
        return branch

    def switch_branch(self, campaign_id: str, branch_id: str) -> Campaign:
        with Session(self.engine) as s:
            c = s.get(Campaign, campaign_id)
            c.active_branch_id = branch_id
            s.add(c)
            s.commit()
            s.refresh(c)
        return c

    def list_branches(self, campaign_id: str) -> list[Branch]:
        with Session(self.engine) as s:
            return list(s.exec(select(Branch).where(Branch.campaign_id == campaign_id)).all())

    def thread_id_for(self, branch: Branch) -> str:
        return branch.id

    # ---------- events ----------

    def add_event(self, campaign_id: str, branch_id: str, turn_id: int, type: str,
                  payload: dict, visibility: str = "all") -> int:
        with Session(self.engine) as s:
            last = s.exec(select(GameEventRow).where(GameEventRow.branch_id == branch_id)
                          .order_by(GameEventRow.seq.desc())).first()
            seq = (last.seq + 1) if last else 1
            s.add(GameEventRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                               seq=seq, type=type, visibility=visibility,
                               payload_json=json.dumps(payload, ensure_ascii=False)))
            s.commit()
        return seq

    def list_events(self, campaign_id: str, branch_id: str, upto_turn: int | None = None,
                    types: list[str] | None = None) -> list[GameEventRow]:
        q = select(GameEventRow).where(GameEventRow.branch_id == branch_id)
        if upto_turn is not None:
            q = q.where(GameEventRow.turn_id <= upto_turn)
        if types is not None:
            q = q.where(GameEventRow.type.in_(types))
        q = q.order_by(GameEventRow.seq)
        with Session(self.engine) as s:
            return list(s.exec(q).all())

    # ---------- versioned state ----------

    def append_state(self, campaign_id: str, branch_id: str, turn_id: int, data: dict) -> None:
        with Session(self.engine) as s:
            s.add(StateSnapshotRow(campaign_id=campaign_id, branch_id=branch_id,
                                   turn_id=turn_id,
                                   data_json=json.dumps(data, ensure_ascii=False)))
            s.commit()

    def get_state_at(self, campaign_id: str, branch_id: str, turn_id: int) -> dict | None:
        """「截至 turn_id」的最新快照（时间旅行读）：查询 turn_id <= ?。

        回合内、本轮快照写入前调用时，返回回合初始状态（post_turn 的场景对比依赖此语义）。
        """
        q = (select(StateSnapshotRow).where(StateSnapshotRow.branch_id == branch_id,
                                            StateSnapshotRow.turn_id <= turn_id)
             .order_by(StateSnapshotRow.turn_id.desc(), StateSnapshotRow.id.desc()))
        with Session(self.engine) as s:
            row = s.exec(q).first()
        return json.loads(row.data_json) if row else None

    def append_character(self, campaign_id: str, branch_id: str, turn_id: int,
                         character_id: str, data: dict) -> None:
        with Session(self.engine) as s:
            s.add(CharacterStateRow(campaign_id=campaign_id, branch_id=branch_id,
                                    turn_id=turn_id, character_id=character_id,
                                    data_json=json.dumps(data, ensure_ascii=False)))
            s.commit()

    def get_character_at(self, campaign_id: str, branch_id: str, turn_id: int,
                         character_id: str) -> dict | None:
        q = (select(CharacterStateRow)
             .where(CharacterStateRow.branch_id == branch_id,
                    CharacterStateRow.turn_id <= turn_id,
                    CharacterStateRow.character_id == character_id)
             .order_by(CharacterStateRow.turn_id.desc(), CharacterStateRow.id.desc()))
        with Session(self.engine) as s:
            row = s.exec(q).first()
        return json.loads(row.data_json) if row else None

    def list_characters_at(self, campaign_id: str, branch_id: str, turn_id: int) -> list[dict]:
        q = (select(CharacterStateRow)
             .where(CharacterStateRow.branch_id == branch_id,
                    CharacterStateRow.turn_id <= turn_id)
             .order_by(CharacterStateRow.character_id,
                       CharacterStateRow.turn_id.desc(), CharacterStateRow.id.desc()))
        with Session(self.engine) as s:
            rows = s.exec(q).all()
        best: dict[str, dict] = {}
        for row in rows:
            best.setdefault(row.character_id, json.loads(row.data_json))
        return list(best.values())

    # ---------- summaries ----------

    def append_summary(self, campaign_id: str, branch_id: str, upto_turn: int,
                       content: str) -> None:
        with Session(self.engine) as s:
            s.add(SummaryRow(campaign_id=campaign_id, branch_id=branch_id,
                             upto_turn=upto_turn, content=content))
            s.commit()

    def latest_summary(self, campaign_id: str, branch_id: str) -> SummaryRow | None:
        q = (select(SummaryRow).where(SummaryRow.branch_id == branch_id)
             .order_by(SummaryRow.upto_turn.desc(), SummaryRow.id.desc()))
        with Session(self.engine) as s:
            return s.exec(q).first()

    # ---------- dice & usage ----------

    def add_dice_record(self, campaign_id: str, branch_id: str, turn_id: int, actor: str,
                        skill: str, skill_value: int, difficulty: str, roll: int,
                        level: str, seed: int) -> None:
        with Session(self.engine) as s:
            s.add(DiceRecordRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                                actor=actor, skill=skill, skill_value=skill_value,
                                difficulty=difficulty, roll=roll, level=level, seed=seed))
            s.commit()

    def list_dice_records(self, campaign_id: str, branch_id: str,
                          turn_id: int | None = None) -> list[DiceRecordRow]:
        q = select(DiceRecordRow).where(DiceRecordRow.branch_id == branch_id)
        if turn_id is not None:
            q = q.where(DiceRecordRow.turn_id == turn_id)
        q = q.order_by(DiceRecordRow.id)
        with Session(self.engine) as s:
            return list(s.exec(q).all())

    def record_usage(self, campaign_id: str, branch_id: str, turn_id: int, role: str,
                     model: str, tokens_in: int, tokens_out: int, cost_usd: float,
                     latency_ms: int) -> None:
        with Session(self.engine) as s:
            s.add(UsageRow(campaign_id=campaign_id, branch_id=branch_id, turn_id=turn_id,
                           role=role, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                           cost_usd=cost_usd, latency_ms=latency_ms))
            s.commit()

    def turn_token_total(self, campaign_id: str, branch_id: str, turn_id: int) -> int:
        q = select(UsageRow).where(UsageRow.branch_id == branch_id, UsageRow.turn_id == turn_id)
        with Session(self.engine) as s:
            rows = s.exec(q).all()
        return sum(r.tokens_in + r.tokens_out for r in rows)

    def campaign_cost_total(self, campaign_id: str) -> float:
        q = select(UsageRow).where(UsageRow.campaign_id == campaign_id)
        with Session(self.engine) as s:
            rows = s.exec(q).all()
        return round(sum(r.cost_usd for r in rows), 6)

    # ---------- branch history ----------

    def branch_history_events(self, campaign_id: str, branch_id: str) -> list[GameEventRow]:
        chain: list[Branch] = []
        cur = self.get_branch(branch_id)
        while cur is not None:
            chain.append(cur)
            cur = self.get_branch(cur.parent_branch_id) if cur.parent_branch_id else None
        chain.reverse()
        out: list[GameEventRow] = []
        for i, b in enumerate(chain):
            upto = chain[i + 1].fork_turn_id if i + 1 < len(chain) else None
            out.extend(self.list_events(campaign_id, b.id, upto_turn=upto))
        return out
