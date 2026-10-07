"""主图装配：GM Supervisor + NPC 子图 Send 并行 + 检查点（M2 单机闭环核心）。

路由语义（与规格 §4/§8 一致）：
- 失败不推进 → fallback → wait_input（本轮 pending 丢弃，玩家重来）
- 战役熔断（④）→ 直接结束图，等待手动调高预算
"""
import logging
import sqlite3
from typing import Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.graph.npc import build_npc_dispatch, build_npc_subgraph, build_npc_worker
from app.graph.nodes.gm import build_decide_node, build_narrate_node, build_validate_node
from app.graph.nodes.memory import build_memory_query_node
from app.graph.nodes.turn import (build_apply_transition_node, build_combat_resolve_node,
                                  build_intake_node, build_post_turn_node,
                                  build_resolve_checks_node, fallback, wait_input)
from app.graph.state import GameState

logger = logging.getLogger(__name__)


def build_checkpointer(sqlite_path: str) -> SqliteSaver:
    """SqliteSaver：CLI 重启后仍可恢复挂起的回合（断点续玩）。"""
    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")   # 与 repo 连接并发写：等待而非立即失败
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _guarded(code: str, fn: Callable) -> Callable:
    """纯代码节点真异常兜底 → 标记错误，交由统一 fallback（规格 §8）。"""

    def wrapped(state: GameState) -> dict:
        try:
            return fn(state)
        except Exception:
            logger.exception("节点真异常兜底：%s", code)  # 降级静默但必须留痕（排障入口）
            return {"error": code, "degraded": {code: True}}

    return wrapped


def _route_after_intake(state: GameState) -> str:
    return "halt" if state.get("error") == "budget_paused" else "gm_decide"


def _route_after_decide(state: GameState) -> str:
    return "fallback" if state.get("error") else "validate"


def _route_after_validate(state: GameState) -> str:
    if state.get("error"):
        return "fallback"
    checks = (state.get("decision") or {}).get("checks", [])
    return "combat_resolve" if any(c.get("target") for c in checks) else "resolve_checks"


def _route_after_combat(state: GameState) -> str:
    return "fallback" if state.get("error") else "resolve_checks"


def _route_after_resolve(state: GameState) -> str:
    return "fallback" if state.get("error") else "apply_transition"


def _route_after_narrate(state: GameState) -> str:
    return "fallback" if state.get("error") else "post_turn"


def _route_after_post_turn(state: GameState) -> str:
    return "end" if state.get("ending_reached") else "wait_input"


def build_game_graph(repo, module, memory, client, guard, checkpointer=None):
    g = StateGraph(GameState)
    g.add_node("intake", build_intake_node(repo, module, guard))
    g.add_node("gm_decide", build_decide_node(client, module, repo))
    g.add_node("validate", build_validate_node(client, module))
    g.add_node("combat_resolve",
               _guarded("combat_failed", build_combat_resolve_node(repo, module)))
    g.add_node("resolve_checks",
               _guarded("resolve_failed", build_resolve_checks_node(repo)))
    g.add_node("apply_transition", build_apply_transition_node(module))
    g.add_node("memory_query", build_memory_query_node(memory))
    g.add_node("npc_respond", build_npc_worker(build_npc_subgraph(client)))
    g.add_node("gm_narrate", build_narrate_node(client, module, repo))
    g.add_node("post_turn", build_post_turn_node(repo, memory, module))
    g.add_node("wait_input", wait_input)
    g.add_node("fallback", fallback)

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", _route_after_intake,
                            {"halt": END, "gm_decide": "gm_decide"})
    g.add_conditional_edges("gm_decide", _route_after_decide,
                            {"fallback": "fallback", "validate": "validate"})
    g.add_conditional_edges("validate", _route_after_validate,
                            {"fallback": "fallback", "combat_resolve": "combat_resolve",
                             "resolve_checks": "resolve_checks"})
    g.add_conditional_edges("combat_resolve", _route_after_combat,
                            {"fallback": "fallback", "resolve_checks": "resolve_checks"})
    g.add_conditional_edges("resolve_checks", _route_after_resolve,
                            {"fallback": "fallback", "apply_transition": "apply_transition"})
    g.add_edge("apply_transition", "memory_query")
    g.add_conditional_edges("memory_query", build_npc_dispatch(module),
                            ["npc_respond", "gm_narrate"])
    g.add_edge("npc_respond", "gm_narrate")   # Send 各分支全部完成后汇合
    g.add_conditional_edges("gm_narrate", _route_after_narrate,
                            {"fallback": "fallback", "post_turn": "post_turn"})
    g.add_conditional_edges("post_turn", _route_after_post_turn,
                            {"end": END, "wait_input": "wait_input"})
    g.add_edge("wait_input", "intake")        # interrupt 恢复后开启下一回合
    g.add_edge("fallback", "wait_input")      # 失败不推进：重新收集输入
    return g.compile(checkpointer=checkpointer)
