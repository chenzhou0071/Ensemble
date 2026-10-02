"""checkpoint 分叉：把源 thread 的历史挂起点链复制到新 thread（规格 §7 读档回滚）。

实现要点：不做反序列化、原样复制 rows。挂起点判定 = 该 checkpoint 存在
`__interrupt__` 写（langgraph 把 interrupt 存为 reserved 通道的 write）。
第 k 个挂起点（从最旧数起，1-based）= 第 k-1 个回合结束后的 wait_input 挂起。

M3-7 探测事实（langgraph-checkpoint-sqlite 3.1.1）：
- 同一 thread 上子图（Send 并行）会写入 `checkpoint_ns` 非空的行，必须只沿
  主图链（`checkpoint_ns = ''`）上溯，否则链会断裂/混入；
- 主图链为单链（单 root、无分叉 parent）；
- 库中尚无 checkpoint 表（从未跑过图）按"无 checkpoint"处理。
"""
import sqlite3


def _chain(db_path: str, thread_id: str) -> list[str]:
    """按从旧到新返回主图（checkpoint_ns=''）的 checkpoint 链（沿 parent 上溯）。"""
    with sqlite3.connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT checkpoint_id, parent_checkpoint_id FROM checkpoints "
                "WHERE thread_id = ? AND checkpoint_ns = ''", (thread_id,)).fetchall()
        except sqlite3.OperationalError:      # 表不存在 = 从未跑图
            return []
    parents = {cid: pid for cid, pid in rows}
    children = {pid: cid for cid, pid in rows if pid}
    roots = [cid for cid, pid in rows if not pid or pid not in parents]
    if not roots:
        return []
    chain, cur = [], roots[0]
    while cur:
        chain.append(cur)
        cur = children.get(cur)
    return chain


def fork_thread(db_path: str, src_thread: str, dst_thread: str, upto_turn: int) -> None:
    chain = _chain(db_path, src_thread)
    if not chain:
        raise ValueError(f"no checkpoints on thread {src_thread}")
    with sqlite3.connect(db_path) as conn:
        parked = {cid for (cid,) in conn.execute(
            "SELECT DISTINCT checkpoint_id FROM writes "
            "WHERE thread_id = ? AND checkpoint_ns = '' AND channel = '__interrupt__'",
            (src_thread,)).fetchall()}
        ordered_parked = [cid for cid in chain if cid in parked]
        if len(ordered_parked) <= upto_turn:
            raise ValueError(
                f"turn boundary not found: turn {upto_turn} "
                f"(仅 {len(ordered_parked)} 个已完成回合挂起点)")
        boundary = ordered_parked[upto_turn]          # 第 upto_turn+1 个挂起点
        copy_ids = chain[: chain.index(boundary) + 1]  # 含边界在内的全部祖先

        for table in ("checkpoints", "writes"):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            marks = ",".join("?" for _ in cols)
            sel = (f"SELECT {','.join(cols)} FROM {table} "
                   f"WHERE thread_id = ? AND checkpoint_ns = '' "
                   f"AND checkpoint_id IN ({','.join('?' for _ in copy_ids)})")
            rows = conn.execute(sel, [src_thread, *copy_ids]).fetchall()
            ins = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({marks})"
            for row in rows:
                values = dict(zip(cols, row))
                values["thread_id"] = dst_thread
                conn.execute(ins, [values[c] for c in cols])
        conn.commit()
