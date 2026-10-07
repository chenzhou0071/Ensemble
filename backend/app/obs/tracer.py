"""可观测性：本地 JSONL 追踪（一行一个完整 run，字段对齐 LangSmith run 格式）。

设计约定：
- start_run 只登记内存，finish_run 才追加写盘 → 中途放弃的流不会留下断头 run；
- 每行 JSON 独立完整；单进程内追加写（open "a"）简单安全；
- 与 LangSmith 字段对齐，供本地无网调试与"每回合延迟 / LLM 成功率"分析。
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Tracer:
    def __init__(self, traces_dir: str):
        self._dir = Path(traces_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "traces.jsonl"
        self._pending: dict[str, dict] = {}
        self.current_turn_run_id: str | None = None

    def start_run(self, name: str, run_type: str, inputs: dict | None = None,
                  parent_run_id: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        self._pending[run_id] = {
            "run_id": run_id, "parent_run_id": parent_run_id,
            "name": name, "run_type": run_type,
            "inputs": inputs or {}, "start_time": _now(),
        }
        return run_id

    def finish_run(self, run_id: str, outputs: dict | None = None,
                   error: str | None = None) -> None:
        meta = self._pending.pop(run_id, None)
        if meta is None:
            return
        meta["outputs"] = outputs or {}
        meta["end_time"] = _now()
        meta["error"] = error
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")


def make_tracer(settings) -> Tracer | None:
    """traces_dir 为空（默认）→ 关闭追踪，零开销。"""
    return Tracer(settings.traces_dir) if settings.traces_dir else None
