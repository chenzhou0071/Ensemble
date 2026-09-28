from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.nodes.turn import wait_input
from app.graph.state import GameState

def build_mini():
    g = StateGraph(GameState)
    g.add_node("wait_input", wait_input)
    g.add_edge(START, "wait_input")
    g.add_edge("wait_input", END)
    return g.compile(checkpointer=MemorySaver())

def test_interrupt_then_resume_clears_pending():
    app = build_mini()
    cfg = {"configurable": {"thread_id": "t1"}}
    app.invoke({"turn_id": 0, "player_inputs": [], "npc_reactions": {"old": {}},
                "check_results": [{"x": 1}], "narration": "旧叙事", "error": "旧错误"}, cfg)
    assert app.get_state(cfg).next == ("wait_input",)  # 已挂起
    result = app.invoke(Command(resume={
        "turn_id": 1,
        "inputs": [{"player_id": "p1", "character_id": "pc_1", "text": "我推门进去"}],
        "skipped": [],
    }), cfg)
    assert result["player_inputs"][0]["text"] == "我推门进去"
    assert result["is_opening"] is False
    assert result["npc_reactions"] == {} and result["check_results"] == []
    assert result["error"] is None and result["narration"] == ""
