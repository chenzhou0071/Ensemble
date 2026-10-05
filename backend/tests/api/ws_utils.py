"""WS 测试工具：宽容 anyio/starlette teardown 的时序竞态假红。

`TestClient.websocket_connect` 上下文退出时偶发 `concurrent.futures.CancelledError`
（ASGI portal future 竞态，与业务无关）。`ws_connect` 仅在块内无异常（断言均通过）
时吞掉退出阶段的该异常；块内失败照常传播，避免掩盖真实缺陷。
"""
import concurrent.futures
import sys
from contextlib import contextmanager


@contextmanager
def ws_connect(client, url: str):
    """等效 `with client.websocket_connect(url) as ws:`，退出阶段宽容 CancelledError。"""
    ctx = client.websocket_connect(url)
    ws = ctx.__enter__()
    try:
        yield ws
    except BaseException:                       # 块内异常/断言失败：原样传播
        ctx.__exit__(*sys.exc_info())
        raise
    else:
        try:
            ctx.__exit__(None, None, None)
        except concurrent.futures.CancelledError:
            pass                                # teardown 竞态假红：断言已通过，宽容
