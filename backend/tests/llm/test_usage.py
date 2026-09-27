from app.config import Settings
from app.llm.usage import BudgetGuard, BudgetLevel

def guard():
    return BudgetGuard(Settings(turn_token_cap=100, campaign_cost_cap_usd=1.0))

def test_ok_below_thresholds():
    assert guard().check(turn_tokens=0, campaign_cost_usd=0.0) is BudgetLevel.OK
    assert guard().check(turn_tokens=69, campaign_cost_usd=0.69) is BudgetLevel.OK

def test_tight_at_70_percent():
    assert guard().check(turn_tokens=70, campaign_cost_usd=0.0) is BudgetLevel.TIGHT
    assert guard().check(turn_tokens=0, campaign_cost_usd=0.7) is BudgetLevel.TIGHT

def test_exceeded_at_turn_token_cap():
    assert guard().check(turn_tokens=100, campaign_cost_usd=0.0) is BudgetLevel.EXCEEDED

def test_paused_at_campaign_cost_cap():
    assert guard().check(turn_tokens=0, campaign_cost_usd=1.0) is BudgetLevel.PAUSED
    assert guard().check(turn_tokens=999, campaign_cost_usd=1.0) is BudgetLevel.PAUSED
