"""REST：模组、战役（M3-5）；时间线（M3-6）；分叉恢复（M3-7）。"""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


def _deps(request: Request):
    return request.app.state.deps


class CreateCampaignRequest(BaseModel):
    module_id: str
    title: str
    player_name: str = "调查员"


@router.get("/modules")
def list_modules_endpoint(request: Request):
    from app.content.registry import list_modules
    return list_modules(_deps(request).settings.modules_dir)


@router.post("/campaigns")
def create_campaign(req: CreateCampaignRequest, request: Request):
    from app.content.loader import load_module
    from app.content.registry import find_module_path
    from app.rules.character import make_default_character

    deps = _deps(request)
    try:
        module = load_module(find_module_path(deps.settings.modules_dir, req.module_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    campaign = deps.repo.create_campaign(module.meta.id, req.title)
    player = deps.repo.add_player(campaign.id, req.player_name)
    char = make_default_character(player.id, req.player_name)
    deps.repo.append_character(campaign.id, campaign.active_branch_id, 0,
                               char.id, asdict(char))
    return {"campaign_id": campaign.id, "branch_id": campaign.active_branch_id,
            "player_id": player.id, "character_id": char.id}


@router.get("/campaigns")
def list_campaigns(request: Request):
    repo = _deps(request).repo
    from app.storage.models import Campaign
    from sqlmodel import Session, select
    with Session(repo.engine) as s:
        rows = s.exec(select(Campaign).order_by(Campaign.created_at.desc())).all()
    out = []
    for c in rows:
        out.append({"id": c.id, "title": c.title, "module_id": c.module_id,
                    "active_branch_id": c.active_branch_id,
                    "created_at": c.created_at.isoformat()})
    return out


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, request: Request):
    import json
    deps = _deps(request)
    repo = deps.repo
    try:
        campaign = repo.get_campaign(campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign not found")
    from app.content.loader import load_module
    from app.content.registry import find_module_path
    module = load_module(find_module_path(deps.settings.modules_dir, campaign.module_id))
    branch_id = campaign.active_branch_id
    snap = repo.latest_snapshot(campaign_id, branch_id)
    scene_id = (json.loads(snap.data_json).get("scene_id") if snap else None) \
        or module.opening.scene_id
    turn_id = (snap.turn_id + 1) if snap else 0
    players = [{"id": p.id, "display_name": p.display_name}
               for p in repo.list_players(campaign_id)]
    characters = repo.list_characters_at(campaign_id, branch_id, 10**9)
    seen, clues = set(), []
    for e in repo.list_events(campaign_id, branch_id, types=["clue"]):
        payload = json.loads(e.payload_json)
        if payload.get("clue_id") not in seen:
            seen.add(payload.get("clue_id"))
            clues.append(payload)
    return {"id": campaign.id, "title": campaign.title, "module_id": campaign.module_id,
            "module_title": module.meta.title, "active_branch_id": branch_id,
            "scene_id": scene_id, "turn_id": turn_id,
            "cost_usd": repo.campaign_cost_total(campaign_id),
            "players": players, "characters": characters, "clues_revealed": clues}
