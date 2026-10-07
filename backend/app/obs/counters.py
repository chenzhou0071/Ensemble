"""进程内指标计数器（/metrics 数据源）。

设计约定：
- 纯进程内存：重启清零，响应以 scope="process" 声明；
- 回合延迟只保留最近 200 个样本（deque maxlen），p50/p95 为排序后最近秩取值；
- fallback kind 固定五类：memory_query / npc_silent / decision_invalid /
  narrate_failed / budget_paused，与各处降级路径一一对应。
"""
from collections import Counter, deque

_TURN_WINDOW = 200


class Counters:
    def __init__(self) -> None:
        self.llm_calls = 0
        self.llm_failures = 0
        self.fallbacks: Counter[str] = Counter()
        self.turn_latencies: deque[int] = deque(maxlen=_TURN_WINDOW)
        self.npc_activation: Counter[str] = Counter()

    def record_llm(self, ok: bool = True) -> None:
        self.llm_calls += 1
        if not ok:
            self.llm_failures += 1

    def record_fallback(self, kind: str) -> None:
        self.fallbacks[kind] += 1

    def record_turn(self, latency_ms: int, npc_count: int) -> None:
        self.turn_latencies.append(int(latency_ms))
        self.npc_activation[str(npc_count)] += 1

    def snapshot(self) -> dict:
        lat = sorted(self.turn_latencies)

        def _pct(p: float) -> int:
            if not lat:
                return 0
            return lat[min(len(lat) - 1, int(len(lat) * p))]

        return {
            "llm": {"calls": self.llm_calls, "failures": self.llm_failures},
            "fallbacks": dict(self.fallbacks),
            "turns": {"count": len(lat), "p50_ms": _pct(0.50), "p95_ms": _pct(0.95)},
            "npc_activation": dict(self.npc_activation),
        }


_counters = Counters()


def get_counters() -> Counters:
    return _counters


def reset_counters() -> None:
    """测试隔离用：替换为新实例（引用方始终经 get_counters() 取最新单例）。"""
    global _counters
    _counters = Counters()
