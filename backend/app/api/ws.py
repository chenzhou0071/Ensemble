"""WebSocket 端点：实时事件流 + 玩家输入。"""
import asyncio
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.events import WsEvent

router = APIRouter()


def _deps(websocket: WebSocket):
    return websocket.app.state.deps


@router.websocket("/ws/campaign/{campaign_id}")
async def ws_campaign(websocket: WebSocket, campaign_id: str,
                      player_id: str = Query(...), resume_from: int = Query(0),
                      client_id: str = Query("")):
    deps = _deps(websocket)
    if deps.manager is None:
        await websocket.close(code=4403)
        return
    try:
        campaign = deps.repo.get_campaign(campaign_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    if campaign.owner_client_id not in ("", client_id):
        await websocket.close(code=4404)
        return
    player = deps.repo.get_player(player_id)
    if player is None or player.campaign_id != campaign_id:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        session = await deps.manager.ensure_started(campaign_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    sub = session.bus.subscribe(player_id)
    try:
        events, gap = session.bus.replay(resume_from, player_id)
        if gap:
            resync = WsEvent(seq=session.bus.current_seq, type="state",
                             visibility="all",
                             payload=deps.manager.resync_payload(session))
            await websocket.send_text(resync.to_json())
        else:
            for evt in events:
                await websocket.send_text(evt.to_json(replay=True))   # 历史回放标记
        await _serve(websocket, session, sub, deps.manager, campaign_id, player_id)
    finally:
        session.bus.unsubscribe(sub)


async def _serve(websocket, session, sub, manager, campaign_id, player_id):
    async def sender():
        while True:
            evt = await sub.queue.get()
            await websocket.send_text(evt.to_json())

    async def receiver():
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "input":
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            try:
                await manager.handle_submit(campaign_id, player_id, text)
            except KeyError:
                continue

    sender_task = asyncio.create_task(sender())
    receiver_task = asyncio.create_task(receiver())
    try:
        await asyncio.wait({sender_task, receiver_task},
                           return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        receiver_task.cancel()
        await asyncio.gather(sender_task, receiver_task, return_exceptions=True)
