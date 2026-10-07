"""M5-5：单战役用量端点 —— 汇总 + 最近明细（倒序）。"""


def test_usage_endpoint_aggregates_and_lists_recent(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "记账"}).json()["campaign_id"]
    branch = repo.get_campaign(cid).active_branch_id
    repo.record_usage(cid, branch, 1, "gm", "qwen3.8-flash", 100, 50, 0.0004, 120)
    repo.record_usage(cid, branch, 2, "npc", "deepseek-flash", 80, 40, 0.0001, 90)
    d = c.get(f"/api/campaigns/{cid}/usage").json()
    assert d["totals"]["calls"] == 2
    assert d["totals"]["tokens_in"] == 180 and d["totals"]["tokens_out"] == 90
    assert abs(d["totals"]["cost_usd"] - 0.0005) < 1e-9
    assert d["cap_usd"] > 0
    assert [r["role"] for r in d["recent"]] == ["npc", "gm"]        # 最近在前
    assert d["recent"][0]["turn_id"] == 2 and d["recent"][0]["model"] == "deepseek-flash"


def test_usage_endpoint_404_for_unknown_campaign(client):
    c, _ = client
    assert c.get("/api/campaigns/none/usage").status_code == 404
