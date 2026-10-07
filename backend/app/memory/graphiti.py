"""L3 二阶段：Graphiti 时序图谱适配器（可选依赖）。

设计要点：
- 事件始终落 L2 事件表（权威来源），图谱只做增强——写失败只记日志、不回滚回合；
- 检索优先图谱事实，图谱不可用/报错时回退 JournalMemory 关键词检索；
- graphiti-core 是可选的异步库：延迟导入（extra: graph），
  `_GraphitiAdapter` 用后台线程独占事件循环把异步 API 桥接为同步 GraphClient。
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Protocol

from app.memory.base import MemoryEvent, MemoryHit
from app.memory.journal import JournalMemory

logger = logging.getLogger("ensemble.memory")


class GraphClient(Protocol):
    def add_episode(self, name: str, body: str, group_id: str,
                    reference_time: str) -> None: ...
    def search_facts(self, query: str, group_id: str, limit: int) -> list[str]: ...
    def close(self) -> None: ...


class GraphitiMemory:
    """MemoryService 实现：JournalMemory 为底座，时序图谱为增强。"""

    def __init__(self, repo, graph_client: GraphClient | None = None,
                 summarizer: Callable | None = None):
        self._repo = repo
        self._graph = graph_client
        self._journal = JournalMemory(repo, summarizer)

    @staticmethod
    def _group_id(campaign_id: str, branch_id: str) -> str:
        return f"{campaign_id}:{branch_id}"

    def write_event(self, campaign_id: str, branch_id: str, event: MemoryEvent) -> None:
        self._journal.write_event(campaign_id, branch_id, event)
        if self._graph is None:
            return
        try:
            self._graph.add_episode(
                name=f"{event.type}:t{event.turn_id}", body=event.text,
                group_id=self._group_id(campaign_id, branch_id),
                reference_time=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logger.warning("graphiti add_episode failed: %s", exc)

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
                             and after.turn_id == before.turn_id):
            return                                   # 未产生新摘要
        try:
            self._graph.add_episode(
                name=f"summary:t{turn_id}", body=after.content,
                group_id=self._group_id(campaign_id, branch_id),
                reference_time=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logger.warning("graphiti summary mirror failed: %s", exc)


class _GraphitiAdapter:
    """graphiti-core 异步 API → 同步 GraphClient（后台 daemon 线程独占事件循环）。"""

    def __init__(self, graphiti, timeout_seconds: int = 60):
        self._graphiti = graphiti
        self._timeout = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()

    def _serve_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(self._timeout)

    def add_episode(self, name: str, body: str, group_id: str, reference_time: str) -> None:
        from graphiti_core.nodes import EpisodeType
        self._call(self._graphiti.add_episode(
            name=name, episode_body=body, source=EpisodeType.text,
            source_description="ensemble turn event",
            reference_time=datetime.fromisoformat(reference_time),
            group_id=group_id))

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
    """真实图谱客户端；graphiti-core 未安装 / 密码缺失时抛异常（由 build_memory 回退）。"""
    from graphiti_core import Graphiti          # 可选依赖：延迟导入
    if not settings.neo4j_password:
        raise RuntimeError("NEO4J_PASSWORD 未配置")
    graphiti = Graphiti(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    return _GraphitiAdapter(graphiti)


def build_memory(settings, repo, summarizer=None):
    """按配置装配 L3：journal（默认）| graphiti（初始化失败优雅回退并告警）。

    summarizer 由装配层传入（Task 18b 摘要接线：LLMSummarizer），透传给底层 JournalMemory。
    """
    if settings.memory_backend == "graphiti":
        try:
            graph = make_graphiti_client(settings)
            logger.info("L3 memory backend: graphiti")
            return GraphitiMemory(repo, graph_client=graph, summarizer=summarizer)
        except Exception as exc:
            logger.warning("Graphiti 不可用，回退 JournalMemory：%s", exc)
    return JournalMemory(repo, summarizer=summarizer)
