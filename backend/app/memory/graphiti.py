"""L3 二阶段：Graphiti 时序图谱适配器（可选依赖）。

设计要点：
- 事件始终落 L2 事件表（权威来源），图谱只做增强——写失败只记日志、不回滚回合；
- 检索优先图谱事实，图谱不可用/报错时回退 JournalMemory 关键词检索；
- graphiti-core 是可选的异步库：延迟导入（extra: graph），
  `_GraphitiAdapter` 用后台线程独占事件循环把异步 API 桥接为同步 GraphClient。
"""
import asyncio
import logging
import queue
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from app.memory.base import MemoryEvent, MemoryHit
from app.memory.journal import JournalMemory

logger = logging.getLogger("ensemble.memory")


class GraphClient(Protocol):
    def add_episode(self, name: str, body: str, group_id: str,
                    reference_time: str) -> None: ...
    def search_facts(self, query: str, group_id: str, limit: int) -> list[str]: ...
    def close(self) -> None: ...


class _MirrorQueue:
    """单 daemon 线程 FIFO：图谱镜像串行写入（保序、不阻塞回合主链）。

    best-effort 语义：进程退出时未排空的任务自然丢弃（L2 事件表为权威来源）；
    未 start() 时同步直跑，便于测试与单次脚本探测。
    """

    def __init__(self, handler: Callable[[Any], None]):
        self._handler = handler
        self._items: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop,
                                        name="ensemble-graph-mirror", daemon=True)
        self._thread.start()

    def submit(self, item) -> None:
        if self._thread is None:
            self._handle(item)
            return
        self._items.put(item)

    def join(self) -> None:
        if self._thread is not None:
            self._items.join()

    def _loop(self) -> None:
        while True:
            self._handle(self._items.get())
            self._items.task_done()

    def _handle(self, item) -> None:
        try:
            self._handler(item)
        except Exception as exc:
            logger.warning("graphiti mirror failed: %s", exc)


class GraphitiMemory:
    """MemoryService 实现：JournalMemory 为底座，时序图谱为增强。"""

    def __init__(self, repo, graph_client: GraphClient | None = None,
                 summarizer: Callable | None = None):
        self._repo = repo
        self._graph = graph_client
        self._journal = JournalMemory(repo, summarizer)
        self._mirror = _MirrorQueue(self._mirror_episode)

    def start(self) -> None:
        """启动后台镜像线程（生产装配调用）；未调用时镜像同步直跑（测试）。"""
        self._mirror.start()

    def drain(self) -> None:
        """等待镜像队列排空（测试/优雅退出用）；未启动时无操作。"""
        self._mirror.join()

    def _mirror_episode(self, item: tuple[str, str, str, str]) -> None:
        name, body, group_id, reference_time = item
        self._graph.add_episode(name=name, body=body, group_id=group_id,
                                reference_time=reference_time)

    @staticmethod
    def _group_id(campaign_id: str, branch_id: str) -> str:
        # graphiti 组名约束：仅字母数字/连字符/下划线；branch_id 形如 "{cid}@main" 需净化
        return re.sub(r"[^A-Za-z0-9_-]", "_", f"{campaign_id}_{branch_id}")

    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None:
        self._journal.write_event(campaign_id, branch_id, event)
        if self._graph is None:
            return
        self._mirror.submit((f"{event.type}:t{event.turn_id}", event.text,
                             self._group_id(campaign_id, branch_id),
                             datetime.now(timezone.utc).isoformat()))

    def search(self, campaign_id: str, branch_id: str, query: str,
               limit: int = 5) -> list[MemoryHit]:
        if self._graph is not None:
            try:
                facts = self._graph.search_facts(
                    query, self._group_id(campaign_id, branch_id), limit)
                return [MemoryHit(text=f, turn_id=0) for f in facts]   # 图谱事实无回合归属，回填 0
            except Exception as exc:
                logger.warning("graphiti search failed, fallback to journal: %s", exc)
        return self._journal.search(campaign_id, branch_id, query, limit)

    def get_context(self, campaign_id: str, branch_id: str, budget_chars: int = 1200) -> str:
        return self._journal.get_context(campaign_id, branch_id, budget_chars)

    def update_summaries(self, campaign_id: str, branch_id: str, turn_id: int) -> None:
        before = self._repo.latest_summary(campaign_id, branch_id)
        self._journal.update_summaries(campaign_id, branch_id, turn_id)
        if self._graph is None:
            return
        after = self._repo.latest_summary(campaign_id, branch_id)
        if after is None or (before is not None and after.content == before.content
                             and after.upto_turn == before.upto_turn):
            return                                   # 未产生新摘要
        self._mirror.submit((f"summary:t{turn_id}", after.content,
                             self._group_id(campaign_id, branch_id),
                             datetime.now(timezone.utc).isoformat()))


class NoopCrossEncoder:
    """DashScope 兼容端点不支持 OpenAI 判别式重排（logit_bias/logprobs），保持原顺序。"""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(p, 0.0) for p in passages]


class _GraphitiAdapter:
    """graphiti-core 异步 API → 同步 GraphClient（后台 daemon 线程独占事件循环）。

    构造也必须在专用循环内执行：graphiti 驱动会把"建索引"任务调度到构造时的 running loop，
    若在外部循环（如 uvicorn 主循环）构造，driver 会被两个事件循环混用。
    """

    EPISODE_TIMEOUT = 300      # add_episode 含多轮 LLM 抽取，真机实测远超默认 60s

    def __init__(self, factory: Callable[[], Any], timeout_seconds: int = 60):
        self._timeout = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()
        self._graphiti = self._call(self._construct(factory))

    async def _construct(self, factory: Callable[[], Any]):
        return factory()

    def _serve_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro, timeout: int | None = None):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(
            timeout or self._timeout)

    def build_indices(self) -> None:
        """幂等初始化全文/向量索引与约束（Neo4j 首次连库必需）。"""
        self._call(self._graphiti.build_indices_and_constraints())

    def add_episode(self, name: str, body: str, group_id: str, reference_time: str) -> None:
        from graphiti_core.nodes import EpisodeType
        self._call(self._graphiti.add_episode(
            name=name, episode_body=body, source=EpisodeType.text,
            source_description="ensemble turn event",
            reference_time=datetime.fromisoformat(reference_time),
            group_id=group_id), timeout=self.EPISODE_TIMEOUT)

    def search_facts(self, query: str, group_id: str, limit: int) -> list[str]:
        edges = self._call(self._graphiti.search(query=query, group_ids=[group_id],
                                                 num_results=limit))
        return [getattr(e, "fact", str(e)) for e in edges]

    def close(self) -> None:
        try:
            self._call(self._graphiti.close())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)


def make_graphiti_client(settings) -> GraphClient:
    """真实图谱客户端：LLM/embedding 走 DashScope 兼容端点（OpenAI 兼容接法）。

    graphiti-core 未安装 / NEO4J_PASSWORD 或 DASHSCOPE_API_KEY 缺失时抛异常（由 build_memory 回退）。
    """
    if not settings.neo4j_password:
        raise RuntimeError("NEO4J_PASSWORD 未配置")
    if not settings.qwen_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置（图谱抽取与 embedding 复用该密钥）")

    from graphiti_core import Graphiti                     # 可选依赖：延迟导入
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

    class _BoundNoopCrossEncoder(NoopCrossEncoder, CrossEncoderClient):
        """绑定 graphiti 的 ABC：GraphitiClients 是 pydantic 模型，对 cross_encoder 做实例校验。"""

    def build_graphiti() -> Any:
        """实例化 Graphiti（由 _GraphitiAdapter 在专用循环内调用，避免 driver 跨循环混用）。"""
        llm_config = LLMConfig(api_key=settings.qwen_api_key, base_url=settings.qwen_base_url,
                               model=settings.gm_model, small_model=settings.cheap_model)
        return Graphiti(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password,
            # 默认 json_schema 约束解码：DashScope 支持（含 $defs/$ref，实测通过），字段名由服务端强制
            llm_client=OpenAIGenericClient(config=llm_config),
            embedder=OpenAIEmbedder(config=OpenAIEmbedderConfig(
                api_key=settings.qwen_api_key, base_url=settings.qwen_base_url,
                embedding_model="text-embedding-v4")),
            cross_encoder=_BoundNoopCrossEncoder(),
        )

    adapter = _GraphitiAdapter(build_graphiti)
    adapter.build_indices()      # 首次连库建索引（幂等）；失败交由 build_memory 回退
    return adapter


def build_memory(settings, repo, summarizer=None):
    """按配置装配 L3：journal（默认）| graphiti（初始化失败优雅回退并告警）。

    summarizer 由装配层传入（Task 18b 摘要接线：LLMSummarizer），透传给底层 JournalMemory。
    """
    if settings.memory_backend == "graphiti":
        try:
            graph = make_graphiti_client(settings)
            memory = GraphitiMemory(repo, graph_client=graph, summarizer=summarizer)
            memory.start()                           # 镜像异步化：不阻塞回合主链
            logger.info("L3 memory backend: graphiti")
            return memory
        except Exception as exc:
            logger.warning("Graphiti 不可用，回退 JournalMemory：%s", exc)
    return JournalMemory(repo, summarizer=summarizer)
