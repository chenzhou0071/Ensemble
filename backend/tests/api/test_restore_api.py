def test_restore_creates_branch_and_switches(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "恢复"}).json()["campaign_id"]
    # 无 checkpoint（本测试环境未跑图）→ restore 应报 400 且不切分支
    r = c.post(f"/api/campaigns/{cid}/restore", json={"turn_id": 0})
    assert r.status_code == 400
    assert repo.get_campaign(cid).active_branch_id.endswith("@main")
