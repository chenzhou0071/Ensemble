def test_add_and_lookup_player(repo, campaign):
    p = repo.add_player(campaign.id, "张三")
    assert p.join_token and len(p.join_token) >= 8
    assert repo.get_player(p.id).display_name == "张三"
    assert repo.get_player_by_token(p.join_token).id == p.id
    assert repo.get_player("ghost") is None
    assert [x.id for x in repo.list_players(campaign.id)] == [p.id]
