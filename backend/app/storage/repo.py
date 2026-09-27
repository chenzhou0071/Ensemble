"""L2 领域仓储：append-only、版本化、分支隔离。"""
import uuid

from sqlmodel import Session, select

from app.storage.models import Branch, Campaign


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
