def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}

def test_modules_listed(client):
    c, _ = client
    ids = [m["id"] for m in c.get("/api/modules").json()]
    assert "misty_hollow" in ids

def test_create_campaign_creates_player_and_character(client):
    c, repo = client
    r = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                       "title": "初探", "player_name": "张三"})
    assert r.status_code == 200
    data = r.json()
    assert data["campaign_id"] and data["player_id"] and data["character_id"]
    chars = repo.list_characters_at(data["campaign_id"], data["branch_id"], 10**9)
    assert chars[0]["name"] == "张三" and chars[0]["player_id"] == data["player_id"]

def test_get_campaign_detail(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "初探"}).json()["campaign_id"]
    r = c.get(f"/api/campaigns/{cid}")
    d = r.json()
    assert d["title"] == "初探" and d["scene_id"] == "square" and d["turn_id"] == 0
    assert len(d["players"]) == 1 and d["characters"]

def test_get_campaign_404(client):
    c, _ = client
    assert c.get("/api/campaigns/ghost").status_code == 404

def test_campaign_module_exposes_npc_names(client):
    c, repo = client
    cid = c.post("/api/campaigns", json={"module_id": "misty_hollow",
                                         "title": "x"}).json()["campaign_id"]
    d = c.get(f"/api/campaigns/{cid}/module").json()
    assert d["id"] == "misty_hollow"
    names = {n["id"]: n["name"] for n in d["npcs"]}
    assert names.get("elder")                       # 名字非空
    assert all(e["id"] and e["condition"] for e in d["endings"])
