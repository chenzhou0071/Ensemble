"""预算熔断：事前约束（阶梯①②③④语义见设计规格 §9）。"""
from enum import StrEnum

from app.config import Settings


class BudgetLevel(StrEnum):
    OK = "ok"              # 正常
    TIGHT = "tight"        # 阶梯①②：记忆降档 + NPC 收缩到首位
    EXCEEDED = "exceeded"  # 阶梯③：GM 换便宜模型兜底
    PAUSED = "paused"      # 阶梯④：战役熔断暂停


class BudgetGuard:
    def __init__(self, settings: Settings):
        self.turn_cap = settings.turn_token_cap
        self.cost_cap = settings.campaign_cost_cap_usd

    def check(self, turn_tokens: int, campaign_cost_usd: float) -> BudgetLevel:
        if campaign_cost_usd >= self.cost_cap:
            return BudgetLevel.PAUSED
        if turn_tokens >= self.turn_cap:
            return BudgetLevel.EXCEEDED
        if turn_tokens >= 0.7 * self.turn_cap or campaign_cost_usd >= 0.7 * self.cost_cap:
            return BudgetLevel.TIGHT
        return BudgetLevel.OK
