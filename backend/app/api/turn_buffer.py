"""单人回合缓冲：暂存本回合输入，收口时产出 interrupt resume payload。

单人即结算：提交即由 SessionManager 收口驱动，无需窗口/超时/防抖；
结算期间到达的输入顺延到下一轮（pending_next）。
"""
from dataclasses import dataclass, field


@dataclass
class TurnBuffer:
    phase: str = "idle"                        # idle | collecting
    turn_id: int | None = None
    active_players: list[str] = field(default_factory=list)
    submissions: dict[str, dict] = field(default_factory=dict)
    pending_next: dict[str, dict] = field(default_factory=dict)

    def open(self, turn_id: int, active_players: list[str]) -> None:
        self.phase = "collecting"
        self.turn_id = turn_id
        self.active_players = list(active_players)
        self.submissions = dict(self.pending_next)   # 窗口间隙的提交顺延入本轮
        self.pending_next = {}

    def submit(self, player_id: str, entry: dict) -> str:
        if player_id not in self.active_players:
            return "ignored"
        if self.phase == "collecting":
            self.submissions[player_id] = entry     # 后发覆盖前发
            return "accepted"
        self.pending_next[player_id] = entry
        return "deferred"

    def close(self) -> dict:
        """收口并产出 interrupt resume payload（TurnInputs.model_dump() 结构）。"""
        inputs = [self.submissions[p] for p in self.active_players
                  if p in self.submissions]
        skipped = [p for p in self.active_players if p not in self.submissions]
        payload = {"turn_id": self.turn_id, "inputs": inputs, "skipped": skipped}
        self.phase = "idle"
        self.turn_id = None
        self.submissions = {}
        return payload
