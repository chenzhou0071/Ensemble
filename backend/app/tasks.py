"""通用后台队列：watermark 追赶语义（按 key 合并，最新票胜出）。

任务 = (key, watermark)，处理器语义为"把 key 追赶到 watermark"且必须可从持久层重算；
因此合并、丢弃、重启丢失均无害，下次提交自动补齐（设计：specs/2026-09-29-async-queue-design.md）。
"""
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class BackgroundQueue:
    """单 daemon 工作线程 + 覆盖式合并；不 start() 时用 run_pending() 同步执行（测试）。"""

    def __init__(self, handler: Callable[[str, Any], None], name: str = "bg"):
        self._handler = handler
        self._name = name
        self._pending: dict[str, Any] = {}
        self._busy = False
        self._stopping = False
        self._lock = threading.Condition()
        self._thread: threading.Thread | None = None

    def submit(self, key: str, payload: Any) -> None:
        with self._lock:
            if self._stopping:
                return
            self._pending[key] = payload
            self._lock.notify()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop,
                                        name=f"ensemble-{self._name}", daemon=True)
        self._thread.start()

    def run_pending(self) -> int:
        processed = 0
        while True:
            job = self._pop()
            if job is None:
                return processed
            self._handle(*job)
            processed += 1

    def flush(self, timeout: float = 2.0) -> bool:
        with self._lock:
            return self._lock.wait_for(lambda: not self._pending and not self._busy,
                                       timeout=timeout)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            self._lock.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    # ---------- 内部 ----------

    def _loop(self) -> None:
        while True:
            with self._lock:
                self._lock.wait_for(lambda: self._pending or self._stopping)
                if not self._pending:
                    return  # 停止且已排空
                key, payload = self._pop_locked()
            self._handle(key, payload)

    def _pop(self) -> tuple[str, Any] | None:
        with self._lock:
            if not self._pending:
                return None
            return self._pop_locked()

    def _pop_locked(self) -> tuple[str, Any]:
        key = next(iter(self._pending))
        return key, self._pending.pop(key)

    def _handle(self, key: str, payload: Any) -> None:
        with self._lock:
            self._busy = True
        try:
            self._handler(key, payload)
        except Exception:
            logger.exception("后台任务失败（key=%s，已丢弃，等待下次提交自愈）", key)
        finally:
            with self._lock:
                self._busy = False
                self._lock.notify_all()
