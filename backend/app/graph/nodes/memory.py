"""记忆查询节点：为 GM/NPC 组装记忆上下文；失败降级为"无长期记忆"继续。"""
from app.graph.state import GameState
from app.obs.counters import get_counters

SEARCH_LIMIT_PER_QUERY = 2
MAX_QUERIES = 3


def build_memory_query_node(memory):
    def memory_query(state: GameState) -> dict:
        campaign_id, branch_id = state["campaign_id"], state["branch_id"]
        level = state.get("budget_level", "ok")
        try:
            if level in ("tight", "exceeded"):
                # 阶梯①：记忆检索降档（只给最近摘要）
                ctx = memory.get_context(campaign_id, branch_id, budget_chars=600)
            else:
                queries = (state.get("decision") or {}).get("memory_queries", [])[:MAX_QUERIES]
                hits = []
                for q in queries:
                    hits.extend(memory.search(campaign_id, branch_id, q,
                                              limit=SEARCH_LIMIT_PER_QUERY))
                ctx = memory.get_context(campaign_id, branch_id)
                if hits:
                    lines = "\n".join(f"- {h.text}" for h in hits)
                    ctx = f"{ctx}\n【检索命中】\n{lines}"
        except Exception:
            get_counters().record_fallback("memory_query")
            return {"memory_context": "", "degraded": {"memory_query": True}}
        return {"memory_context": ctx}

    return memory_query
