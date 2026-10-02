def _mk(client, title="时间线"):
    cid = client.post("/api/campaigns", json={"module_id": "misty_hollow",
                                              "title": title}).json()["campaign_id"]
    return cid

def test_timeline_lists_branches_with_counts(client):
    c, repo = client
    cid = _mk(c)
    cemp = repo.get_campaign(cid)
    for t in range(3):
        repo.append_state(cid, cemp.active_branch_id, t, {"scene_id": "square",
                                                          "npc_attitudes": {}})
    data = c.get(f"/api/campaigns/{cid}/timeline").json()
    assert data["active_branch_id"] == cemp.active_branch_id
    assert data["branches"][0]["completed_turns"] == 3

def test_switch_branch(client):
    c, repo = client
    cid = _mk(c)
    camp = repo.get_campaign(cid)
    b2 = repo.create_branch(cid, "alt", fork_turn_id=0, parent_branch_id=camp.active_branch_id)
    r = c.post(f"/api/campaigns/{cid}/switch", json={"branch_id": b2.id})
    assert r.json()["active_branch_id"] == b2.id
    assert repo.get_campaign(cid).active_branch_id == b2.id

def test_switch_rejects_foreign_branch(client):
    c, repo = client
    cid1, cid2 = _mk(c, "甲"), _mk(c, "乙")
    b_foreign = repo.get_campaign(cid2).active_branch_id
    r = c.post(f"/api/campaigns/{cid1}/switch", json={"branch_id": b_foreign})
    assert r.status_code == 400
