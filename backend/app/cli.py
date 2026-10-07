"""单机 CLI：新建战役 / 开跑 / 断点续玩（M2 出口验收）。"""
import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from langgraph.types import Command

from app.config import Settings, load_pricing, load_settings, resolve_resource_path
from app.content.loader import load_module
from app.graph.main import build_checkpointer, build_game_graph
from app.llm.client import LLMClient, make_repo_budget_probe
from app.llm.usage import BudgetGuard
from app.memory.graphiti import build_memory
from app.memory.scheduler import BackgroundSummaries
from app.memory.summarizer import LLMSummarizer
from app.obs.tracer import make_tracer
from app.rules.character import make_default_character
from app.storage.db import init_db, make_engine
from app.storage.repo import SqliteRepository
from app.tasks import BackgroundQueue

PLAYER_ID = "p1"
QUIT_WORDS = {"quit", "exit", "q", "退出"}


@dataclass
class AppContext:
    settings: Settings
    repo: SqliteRepository
    module: object
    client: LLMClient | None
    guard: BudgetGuard | None
    memory: object | None
    graph: object
    queue: BackgroundQueue | None = None      # 摘要后台队列（Task 18b）


def assemble(settings: Settings, module_path: str | Path) -> AppContext:
    """装配全部组件；L2 与检查点共用同一 SQLite 文件（CLI 单进程顺序访问）。

    摘要接后台队列（Task 18b）：post_turn 的 update_summaries 只入队，
    LLM 压缩在 ensemble-summary 线程完成，不阻塞回合收尾。
    """
    repo = SqliteRepository(make_engine(settings.sqlite_path))
    init_db(repo.engine)
    module = load_module(module_path)
    # 定价表路径：CWD 相对优先；找不到则回退仓库根（CLI 常在 backend/ 下运行）
    pricing = load_pricing(resolve_resource_path(settings.pricing_path))
    guard = BudgetGuard(settings)
    client = LLMClient(settings, pricing, usage_sink=repo,
                       budget_probe=make_repo_budget_probe(repo, guard),
                       tracer=make_tracer(settings))
    memory = build_memory(settings, repo, summarizer=LLMSummarizer(client))
    queue = BackgroundQueue(lambda key, payload: memory.update_summaries(*payload),
                            name="summary")
    queue.start()
    graph = build_game_graph(repo, module, BackgroundSummaries(memory, queue), client, guard,
                             build_checkpointer(settings.sqlite_path))
    return AppContext(settings=settings, repo=repo, module=module, client=client,
                      guard=guard, memory=memory, queue=queue, graph=graph)


def render_narration(segments: list[dict], module) -> list[str]:
    lines = []
    for s in segments:
        if s["speaker"] == "gm":
            lines.append(s["text"])
        else:
            npc_id = s["speaker"].split(":", 1)[1]
            try:
                name = module.npc(npc_id).name
            except KeyError:
                name = npc_id
            lines.append(f"【{name}】{s['text']}")
    return lines


def play_loop(graph, config, module, turn_id: int, input_fn, print_fn) -> str:
    """输入 → 恢复图 → 渲染，循环直到退出/结局/熔断。返回 "quit"/"ended"/"paused"。"""
    while True:
        try:
            text = input_fn(">> ")
        except (EOFError, KeyboardInterrupt):
            print_fn("（已退出，存档保留；再次运行 play 可继续）")
            return "quit"
        if text is None or text.strip().lower() in QUIT_WORDS:
            print_fn("（已退出，存档保留；再次运行 play 可继续）")
            return "quit"

        result = graph.invoke(Command(resume={
            "turn_id": turn_id,
            "inputs": [{"player_id": PLAYER_ID, "character_id": f"pc_{PLAYER_ID}",
                        "text": text.strip()}],
            "skipped": [],
        }), config)
        interrupts = result.get("__interrupt__")
        if interrupts:
            turn_id = interrupts[0].value["turn_id"]

        if result.get("error") == "budget_paused":
            print_fn("本局预算已熔断暂停（budget paused）。调高上限后重新运行 play。")
            return "paused"
        if result.get("error"):
            print_fn(f"（本回合失败：{result['error']}，请重新输入）")
            continue

        for line in render_narration(result.get("narration_segments", []), module):
            print_fn(line)
        if result.get("ending_reached"):
            print_fn(f"（结局已达：{result['ending_reached']}）")
            return "ended"
        if not interrupts:
            print_fn("（图执行结束）")
            return "quit"


def run_play(ctx: AppContext, campaign_id: str, input_fn=input, print_fn=print) -> str:
    campaign = ctx.repo.get_campaign(campaign_id)
    branch = ctx.repo.get_branch(campaign.active_branch_id)
    config = {"configurable": {"thread_id": ctx.repo.thread_id_for(branch)}}
    snap = ctx.graph.get_state(config)

    if snap.next == ("wait_input",):
        # 断点续玩：图挂在 wait_input（进程重启后同样成立）
        print_fn("（读取存档，继续运行）")
        tasks = snap.tasks or ()
        interrupts = tasks[0].interrupts if tasks else ()
        turn_id = (interrupts[0].value["turn_id"] if interrupts
                   else int(snap.values.get("turn_id", 0)))
        return play_loop(ctx.graph, config, ctx.module, turn_id, input_fn, print_fn)

    if snap.next:
        print_fn(f"（图处于中间状态 {snap.next}，无法续玩，请重新启动）")
        return "quit"

    if snap.values:
        if snap.values.get("error") == "budget_paused":
            # 熔断暂停的存档（图停在 END）：调高上限后重驱动挂起的回合（规格 §9）
            print_fn("（检测到预算暂停的存档，以上调后的上限继续运行）")
            result = ctx.graph.invoke({"campaign_id": campaign.id,
                                       "branch_id": campaign.active_branch_id,
                                       "turn_id": int(snap.values.get("turn_id", 0)),
                                       "player_inputs": list(snap.values.get("player_inputs", []))},
                                      config)
            if result.get("error") == "budget_paused":
                print_fn("本局预算仍不足（budget paused）。调高上限后重新运行 play。")
                return "paused"
            for line in render_narration(result.get("narration_segments", []), ctx.module):
                print_fn(line)
            interrupts = result.get("__interrupt__")
            if not interrupts:
                print_fn("（图执行结束）")
                return "quit"
            return play_loop(ctx.graph, config, ctx.module,
                             interrupts[0].value["turn_id"], input_fn, print_fn)
        print_fn("（本局已结束）")
        return "quit"

    # 全新开局：跑开场回合
    result = ctx.graph.invoke({"campaign_id": campaign.id,
                               "branch_id": campaign.active_branch_id,
                               "turn_id": 0, "player_inputs": []}, config)
    if result.get("error") == "budget_paused":
        print_fn("本局预算已熔断暂停（budget paused）。调高上限后重新运行 play。")
        return "paused"
    for line in render_narration(result.get("narration_segments", []), ctx.module):
        print_fn(line)
    interrupts = result.get("__interrupt__")
    if not interrupts:
        print_fn("（图执行结束）")
        return "quit"
    return play_loop(ctx.graph, config, ctx.module,
                     interrupts[0].value["turn_id"], input_fn, print_fn)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ensemble", description="Ensemble 单机跑团 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="新建战役与默认角色")
    p_new.add_argument("module_path", help="模组 YAML 路径，如 ../modules/misty_hollow.yaml")
    p_new.add_argument("title", help="战役名")

    p_play = sub.add_parser("play", help="开跑 / 断点续玩")
    p_play.add_argument("campaign_id")
    p_play.add_argument("module_path")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "new":
        ctx = assemble(settings, args.module_path)
        campaign = ctx.repo.create_campaign(ctx.module.meta.id, args.title)
        char = make_default_character(PLAYER_ID, "调查员")
        ctx.repo.append_character(campaign.id, campaign.active_branch_id, 0,
                                  char.id, asdict(char))
        print(f"战役已创建：{campaign.id}（模组 {ctx.module.meta.id}）")
        print(f"开跑：python -m app.cli play {campaign.id} {args.module_path}")
        return 0

    ctx = assemble(settings, args.module_path)
    run_play(ctx, args.campaign_id)
    if ctx.queue is not None:
        ctx.queue.flush(2.0)      # 退出前尽力收尾摘要（丢任务无害：watermark 下次提交自愈）
    return 0


if __name__ == "__main__":
    sys.exit(main())
