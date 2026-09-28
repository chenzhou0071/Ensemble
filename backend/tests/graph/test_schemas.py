import pytest
from app.graph.schemas import GmDecision, parse_decision_json

def test_parse_plain_json():
    d = parse_decision_json('{"intent_summary": "查看四周"}')
    assert d.intent_summary == "查看四周" and d.checks == []

def test_parse_fenced_json_with_noise():
    raw = '好的，裁决如下：\n```json\n{"intent_summary": "潜入", "checks": [{"actor": "pc_1", "skill": "潜行", "difficulty": "hard"}]}\n```\n完毕。'
    d = parse_decision_json(raw)
    assert d.checks[0].skill == "潜行" and d.checks[0].difficulty == "hard"

def test_parse_rejects_garbage():
    with pytest.raises(Exception):
        parse_decision_json("这里没有 JSON")
