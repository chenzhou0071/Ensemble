"""WS 事件总线：seq 分配、可见性过滤、断线重放环形缓冲（纯内存，无 IO）。"""
import asyncio
import json
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WsEvent:
    seq: int
    type: str
    visibility: str
    payload: dict

    def to_json(self, replay: bool = False) -> str:
        data = {"seq": self.seq, "type": self.type,
                "visibility": self.visibility, "payload": self.payload}
        if replay:
            data["replay"] = True   # 历史回放标记：消费方据此区分「重放」与「实时」
        return json.dumps(data, ensure_ascii=False)

    def visible_to(self, player_id: str) -> bool:
        return self.visibility == "all" or self.visibility == f"player:{player_id}"


@dataclass
class Subscriber:
    player_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class EventBus:
    def __init__(self, replay_size: int = 500):
        self._seq = 0
        self._buffer: deque[WsEvent] = deque(maxlen=replay_size)
        self._subscribers: list[Subscriber] = []

    @property
    def current_seq(self) -> int:
        return self._seq

    def push(self, event_type: str, payload: dict, visibility: str = "all") -> WsEvent:
        self._seq += 1
        evt = WsEvent(seq=self._seq, type=event_type, visibility=visibility,
                      payload=payload)
        self._buffer.append(evt)
        for sub in list(self._subscribers):
            if evt.visible_to(sub.player_id):
                sub.queue.put_nowait(evt)
        return evt

    def subscribe(self, player_id: str) -> Subscriber:
        sub = Subscriber(player_id=player_id)
        self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        if sub in self._subscribers:
            self._subscribers.remove(sub)

    def replay(self, since_seq: int, player_id: str) -> tuple[list[WsEvent], bool]:
        """该玩家可见的增量事件 + gap 标志（缓冲被截断时调用方应全量 resync）。"""
        events = [e for e in self._buffer if e.seq > since_seq and e.visible_to(player_id)]
        gap = bool(self._buffer) and self._buffer[0].seq > since_seq + 1
        return events, gap
