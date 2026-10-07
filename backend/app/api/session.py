"""会话驱动：RoomSession（每战役一个）与 SessionManager（图的唯一驱动者）。

职责：把 LangGraph 的挂起/恢复（interrupt/resume）翻译成 WS 事件流；
窗口收集玩家输入（TurnBuffer）；从 L2 读权威结果（骰子/线索）推送。
"""
import asyncio
import json
import time
from dataclasses import dataclass, field

from langgraph.types import Command

from app.api.events import EventBus
from app.api.turn_buffer import TurnBuffer
from app.config import Settings, load_pricing
from app.content.loader import load_module
from app.content.registry import find_module_path
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient, make_repo_budget_probe
from app.llm.usage import BudgetGuard
from app.memory.graphiti import build_memory
from app.memory.scheduler import BackgroundSummaries
from app.memory.summarizer import LLMSummarizer
from app.obs.counters import get_counters
from app.obs.tracer import Tracer, make_tracer
from app.storage.repo import SqliteRepository
from app.tasks import BackgroundQueue

_SUCCESS_LEVELS = ("critical", "extreme", "hard", "regular")


def _dice_payload(row) -> dict:
    return {"actor": row.actor, "skill": row.skill, "skill_value": row.skill_value,
            "difficulty": row.difficulty, "roll": row.roll, "level": row.level,
            "seed": row.seed, "success": row.level in _SUCCESS_LEVELS,
            "bonus": row.bonus, "penalty": row.penalty}


def _scene_payload(session, scene_id) -> dict | None:
    """场景展示数据；scene_id 不在模组中（越界/历史分支）→ None。"""
    try:
        scene = session.module.scene(scene_id)
    except KeyError:
        return None
    return {"scene_id": scene.id, "name": scene.name,
            "description": scene.description, "npcs": list(scene.npcs)}


@dataclass
class RoomSession:
    campaign_id: str
    repo: SqliteRepository
    settings: Settings
    module: object
    graph: object
    bus: EventBus
    buffer: TurnBuffer
    branch_id: str
    queue: BackgroundQueue
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started: bool = False
    ended: bool = False
    prev_scene: str | None = None
    last_clue_id: int = 0
    last_scene_id: int = 0
    last_dice_id: int = 0
    drive_task: asyncio.Task | None = None
    tracer: Tracer | None = None

    @property
    def config(self) -> dict:
        return {"configurable": {"thread_id": self.branch_id}}


class SessionManager:
    def __init__(self, deps):
        self._deps = deps
        self._sessions: dict[str, RoomSession] = {}
        self._lock = asyncio.Lock()

    # ---------- 查询 ----------

    def get(self, campaign_id: str) -> RoomSession:
        session = self._sessions.get(campaign_id)
        if session is None:
            raise KeyError(campaign_id)
        return session

    def has(self, campaign_id: str) -> bool:
        """是否存在活跃会话（REST 切换分支时仅需通知有会话的战役）。"""
        return campaign_id in self._sessions

    # ---------- 生命周期 ----------

    def _assemble(self, campaign_id: str) -> RoomSession:
        deps = self._deps
        campaign = deps.repo.get_campaign(campaign_id)
        module = load_module(find_module_path(deps.settings.modules_dir,
                                              campaign.module_id))
        guard = BudgetGuard(deps.settings)
        tracer = make_tracer(deps.settings)
        client = LLMClient(deps.settings, load_pricing(deps.settings.pricing_path),
                           usage_sink=deps.repo, model_factory=deps.model_factory,
                           budget_probe=make_repo_budget_probe(deps.repo, guard),
                           tracer=tracer)
        journal = build_memory(deps.settings, deps.repo, summarizer=LLMSummarizer(client))
        queue = BackgroundQueue(lambda key, payload: journal.update_summaries(*payload),
                                name="summary")
        queue.start()
        graph = build_game_graph(deps.repo, module, BackgroundSummaries(journal, queue),
                                 client, guard,
                                 build_checkpointer(deps.settings.sqlite_path))
        session = RoomSession(
            campaign_id=campaign_id, repo=deps.repo, settings=deps.settings,
            module=module, graph=graph, queue=queue,
            bus=EventBus(replay_size=deps.settings.ws_replay_size),
            buffer=TurnBuffer(),
            branch_id=campaign.active_branch_id, tracer=tracer)
        self._sessions[campaign_id] = session
        return session

    async def ensure_started(self, campaign_id: str) -> RoomSession:
        async with self._lock:
            session = self._sessions.get(campaign_id)
            if session is None:
                session = self._assemble(campaign_id)
            if session.started:
                return session
            session.started = True
        await self._start(session)
        return session

    async def _start(self, session: RoomSession) -> None:
        """按 checkpoint 挂起状态决定：续玩开窗 / 全新开场 / 中间态报错 / 已结束。"""
        snap = session.graph.get_state(session.config)
        if snap.next == ("wait_input",):
            self._backfill(session, snap)   # 重开服务后内存总线为空：首连先补权威历史
            self._open_window(session)
            return
        if snap.next:
            session.bus.push("error",
                             {"message": f"图处于中间状态 {snap.next}，暂无法续玩"})
            return
        if not snap.values:
            await self._drive(session, {"campaign_id": session.campaign_id,
                                        "branch_id": session.branch_id,
                                        "turn_id": 0, "player_inputs": []})
            return
        if (snap.values or {}).get("ending_reached"):
            session.ended = True
            self._backfill(session, snap)   # 已结局的档：同样先补权威历史再报结局
            session.bus.push("turn", {"phase": "ended",
                                      "ending_reached": snap.values["ending_reached"]})

    async def on_branch_switch(self, campaign_id: str) -> None:
        async with self._lock:
            old = self._sessions.pop(campaign_id, None)
            if old is not None:
                if old.drive_task is not None and not old.drive_task.done():
                    old.drive_task.cancel()
                old.queue.stop()          # 旧分支摘要队列：跑完在队任务后退出
            session = self._assemble(campaign_id)
            if old is not None:
                session.bus = old.bus          # 已连接的 WS 订阅保持有效
                old.bus.push("notice", {"message": f"已切换到分支 {session.branch_id}"})
            session.started = True
        await self._start(session)

    async def handle_submit(self, campaign_id: str, player_id: str, text: str) -> str:
        session = self.get(campaign_id)
        player = session.repo.get_player(player_id)
        if player is None or player.campaign_id != campaign_id:
            raise KeyError(player_id)
        entry = {"player_id": player_id, "character_id": f"pc_{player_id}",
                 "text": text.strip(),
                 "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        status = session.buffer.submit(player_id, entry)
        if status == "accepted":
            session.bus.push("actor", {"player_id": player_id, "text": entry["text"]})
            # 单人即结算：提交即收口，后台驱动（不再等待窗口/防抖/超时）
            payload = session.buffer.close()
            session.drive_task = asyncio.create_task(
                self._drive(session, Command(resume=payload,
                                             update={"branch_id": session.branch_id})))
        elif status == "deferred":
            session.bus.push("notice",
                             {"kind": "submit", "status": "deferred",
                              "message": "本轮已开始结算，你的行动将在下一轮生效"},
                             visibility=f"player:{player_id}")
        return status

    async def close(self) -> None:
        for session in list(self._sessions.values()):
            if session.drive_task is not None and not session.drive_task.done():
                session.drive_task.cancel()
            session.queue.flush(2.0)      # 退出前尽力收尾摘要（丢任务无害：watermark 自愈）
            session.queue.stop()
        self._sessions.clear()

    # ---------- 驱动 ----------

    async def _drive(self, session: RoomSession, inp) -> None:
        snap0 = session.graph.get_state(session.config)
        turn_id0 = int((snap0.values or {}).get("turn_id", 0))
        session.bus.push("turn", {"phase": "resolving", "turn_id": turn_id0})
        loop = asyncio.get_running_loop()
        tracer = session.tracer
        run_id: str | None = None
        started = time.perf_counter()
        if tracer is not None:
            run_id = tracer.start_run(name=f"turn:{turn_id0}", run_type="chain",
                                      inputs={"campaign_id": session.campaign_id,
                                              "branch_id": session.branch_id,
                                              "turn_id": turn_id0})
            tracer.current_turn_run_id = run_id
        drive_error: str | None = None

        def _run() -> None:
            # 同步 stream 在 executor 线程执行（SqliteSaver 不支持 async 图接口）；
            # chunk 经 call_soon_threadsafe 回投事件循环，由 bus 分发。
            nonlocal drive_error
            try:
                for chunk in session.graph.stream(inp, session.config,
                                                  stream_mode="custom"):
                    if not isinstance(chunk, dict):
                        continue
                    if "text" in chunk or "reset" in chunk:
                        loop.call_soon_threadsafe(session.bus.push, "token", dict(chunk))
                    elif "dice" in chunk:      # 骰子先出：掷骰即推，先于叙事 token
                        loop.call_soon_threadsafe(self._push_dice, session,
                                                  dict(chunk["dice"]))
            except Exception as exc:  # 图执行意外崩溃：提示但保留会话（可重连续玩）
                drive_error = str(exc)
                loop.call_soon_threadsafe(
                    session.bus.push, "error", {"message": f"图执行失败：{exc}"})

        await asyncio.to_thread(_run)
        values = (session.graph.get_state(session.config).values) or {}
        latency_ms = int((time.perf_counter() - started) * 1000)
        npc_count = len(values.get("npc_reactions") or {})
        get_counters().record_turn(latency_ms, npc_count)     # 无 tracer 也计数
        if tracer is not None and run_id is not None:
            tracer.finish_run(run_id, outputs={
                "turn_id": int(values.get("turn_id", turn_id0)),
                "latency_ms": latency_ms,
                "npc_count": npc_count,
                "degraded": dict(values.get("degraded") or {}),
                "error": drive_error})
            tracer.current_turn_run_id = None
        self._push_snapshot(session)

    def _push_dice(self, session: RoomSession, payload: dict) -> None:
        """图内实时推送（resolve_checks 掷骰后立即，先于叙事 token）。"""
        rid = payload.pop("id", None)
        if rid is not None:
            session.last_dice_id = max(session.last_dice_id, int(rid))
        session.bus.push("dice", payload)

    def _backfill(self, session: RoomSession, snap) -> None:
        """从 L2 补推权威历史：骰子/线索/场景事件 + 状态快照（含场景首推兜底）。
        调用点：①驱动收口（_push_snapshot）；②重开服务后首连续玩（_start）——
        此时内存事件总线为空，客户端无从重建界面，必须由此对齐。"""
        values = snap.values or {}
        finished_turn = max(int(values.get("turn_id", 1)) - 1, 0)
        for row in session.repo.list_dice_records(session.campaign_id,
                                                  session.branch_id,
                                                  turn_id=finished_turn):
            if row.id is None or row.id <= session.last_dice_id:
                continue   # 已实时推送：不重复（含失败不推进回合的重放防护）
            session.last_dice_id = row.id
            session.bus.push("dice", _dice_payload(row),
                             visibility="gm" if row.secret else "all")
        for event in session.repo.list_events(session.campaign_id, session.branch_id,
                                              types=["clue"]):
            if event.id is not None and event.id > session.last_clue_id:
                session.last_clue_id = event.id
                session.bus.push("clue", json.loads(event.payload_json))
        for event in session.repo.list_events(session.campaign_id, session.branch_id,
                                              types=["scene_changed"]):
            if event.id is not None and event.id > session.last_scene_id:
                session.last_scene_id = event.id
                changed = json.loads(event.payload_json)
                payload = _scene_payload(session, changed.get("to_scene"))
                if payload is not None:
                    session.prev_scene = payload["scene_id"]
                    session.bus.push("scene", {**payload,
                                               "reason": changed.get("reason", "")})
        scene_id = values.get("scene_id")
        if scene_id and session.prev_scene is None:      # 首推兜底：本会话尚未推送过场景
            payload = _scene_payload(session, scene_id)
            if payload is not None:
                session.prev_scene = payload["scene_id"]
                session.bus.push("scene", payload)
        session.bus.push("state", self._state_payload(session))

    def _push_snapshot(self, session: RoomSession) -> None:
        """驱动收口：从 L2 读权威结果推送，并决定下一步（开窗/暂停/结束）。"""
        snap = session.graph.get_state(session.config)
        self._backfill(session, snap)
        values = snap.values or {}

        error = values.get("error")
        if error == "budget_paused":
            session.bus.push("error", {"message": "本局预算已熔断暂停（budget paused）。"})
            session.bus.push("turn", {"phase": "paused",
                                      "turn_id": int(values.get("turn_id", 0))})
            return
        if error:
            session.bus.push("error", {"message": f"本回合失败：{error}，请重新输入"})
        if snap.next == ("wait_input",):
            self._open_window(session)
            return
        if not snap.next:
            ending = values.get("ending_reached")
            if ending:
                session.ended = True
                session.bus.push("turn", {"phase": "ended", "ending_reached": ending})
            return
        session.bus.push("turn", {"phase": "paused",
                                  "turn_id": int(values.get("turn_id", 0))})

    # ---------- 输入窗口 ----------

    def _open_window(self, session: RoomSession) -> None:
        players = [p.id for p in session.repo.list_players(session.campaign_id)]
        snap = session.graph.get_state(session.config)
        turn_id = int((snap.values or {}).get("turn_id", 0))
        session.buffer.open(turn_id, players)
        session.bus.push("turn", {"phase": "collecting", "turn_id": turn_id})
        if session.buffer.submissions:      # 结算期间的顺延提交：立即驱动下一轮
            payload = session.buffer.close()
            session.drive_task = asyncio.create_task(
                self._drive(session, Command(resume=payload,
                                             update={"branch_id": session.branch_id})))

    # ---------- 快照 ----------

    def _state_payload(self, session: RoomSession) -> dict:
        values = session.graph.get_state(session.config).values or {}
        campaign_id, branch_id = session.campaign_id, session.branch_id
        seen, clues = set(), []
        for event in session.repo.list_events(campaign_id, branch_id, types=["clue"]):
            payload = json.loads(event.payload_json)
            if payload.get("clue_id") not in seen:
                seen.add(payload.get("clue_id"))
                clues.append(payload)
        # 已结识人物：叙事里开口说过话的 NPC（含开场叙事；GM 台词经 [[npc:id]] 标记解析为分段）
        spoken: set[str] = set()
        segments = []
        for event in session.repo.list_events(campaign_id, branch_id,
                                              types=["narration"]):
            for seg in json.loads(event.payload_json).get("segments", []):
                segments.append(seg)
                speaker = seg.get("speaker", "")
                if speaker.startswith("npc:"):
                    spoken.add(speaker[4:])
        return {"campaign_id": campaign_id, "branch_id": branch_id,
                "turn_id": int(values.get("turn_id", 0)),
                "scene_id": values.get("scene_id"),
                "characters": session.repo.list_characters_at(campaign_id, branch_id,
                                                              10**9),
                "clues_revealed": clues,
                "known_npcs": sorted(spoken),
                "ending_reached": values.get("ending_reached"),
                "segments": segments,
                "cost_usd": session.repo.campaign_cost_total(campaign_id)}

    def resync_payload(self, session: RoomSession) -> dict:
        """重连 gap 时的全量对齐：状态快照（含权威叙事分段）+ 最近骰子 + 当前相位。"""
        payload = self._state_payload(session)
        rows = [r for r in session.repo.list_dice_records(session.campaign_id,
                                                          session.branch_id)
                if not r.secret]
        phase = ("ended" if session.ended else
                 "collecting" if session.buffer.phase == "collecting" else "resolving")
        payload.update({"dice": [_dice_payload(r) for r in rows[-12:]],
                        "phase": phase})
        return payload
