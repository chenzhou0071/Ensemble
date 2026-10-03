"""回合输入收集状态机：单人防抖（挂机不超时）、多人齐全即收、多人超时跳过、后发覆盖、间隙顺延。

时间一律由调用方传入（now / window_started），便于测试注入与定时器复用。
"""
from dataclasses import dataclass, field


@dataclass
class TurnBuffer:
    window_seconds: float = 60.0
    single_player_debounce_seconds: float = 2.0
    phase: str = "idle"                        # idle | collecting
    turn_id: int | None = None
    epoch: int = 0                             # open/close 均自增；旧定时器凭它退出
    active_players: list[str] = field(default_factory=list)
    submissions: dict[str, dict] = field(default_factory=dict)
    pending_next: dict[str, dict] = field(default_factory=dict)
    last_submit_ts: float | None = None

    def open(self, turn_id: int, active_players: list[str], now: float) -> int:
        self.phase = "collecting"
        self.turn_id = turn_id
        self.active_players = list(active_players)
        self.submissions = dict(self.pending_next)   # 窗口间隙的提交顺延入本轮
        self.pending_next = {}
        self.last_submit_ts = now if self.submissions else None
        self.epoch += 1
        return self.epoch

    def submit(self, player_id: str, entry: dict, now: float) -> str:
        if player_id not in self.active_players:
            return "ignored"
        if self.phase == "collecting":
            self.submissions[player_id] = entry     # 后发覆盖前发
            self.last_submit_ts = now
            return "accepted"
        self.pending_next[player_id] = entry
        return "deferred"

    def all_submitted(self) -> bool:
        return bool(self.active_players) and all(p in self.submissions
                                                 for p in self.active_players)

    def should_close(self, now: float, window_started: float) -> bool:
        if self.phase != "collecting":
            return False
        if self.all_submitted():
            if len(self.active_players) == 1 and self.last_submit_ts is not None:
                return (now - self.last_submit_ts) >= self.single_player_debounce_seconds
            return True
        if len(self.active_players) == 1:
            return False    # 单人：未提交永不超时（挂机等待输入，避免自动空跑消耗）
        return (now - window_started) >= self.window_seconds

    def close(self) -> dict:
        """收口并产出 interrupt resume payload（TurnInputs.model_dump() 结构）。"""
        inputs = [self.submissions[p] for p in self.active_players
                  if p in self.submissions]
        skipped = [p for p in self.active_players if p not in self.submissions]
        payload = {"turn_id": self.turn_id, "inputs": inputs, "skipped": skipped}
        self.phase = "idle"
        self.turn_id = None
        self.submissions = {}
        self.last_submit_ts = None
        self.epoch += 1
        return payload
