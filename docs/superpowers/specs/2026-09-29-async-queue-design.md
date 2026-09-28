# 异步后台队列设计（摘要异步化与 Graphiti 复用）

> 日期：2026-09-29 ｜ 状态：待评审（批准后落为 backend-core 计划 **Task 18b**）
> 关联：`2026-09-24-ensemble-design.md`（主规格 §5/§9）、`2026-09-24-ensemble-backend-core.md`（T13 / T21 / T24）、`2026-09-24-ensemble-enhancements.md`（M5-1 Graphiti）

## 1. 背景与问题

- 后端当前为全同步执行模型：LangGraph 节点均为 `def`，以 `.invoke()` 驱动；`post_turn` 节点同步调用 `memory.update_summaries(...)`（`backend/app/graph/nodes/turn.py`）。
- 计数口径澄清：`SUMMARY_TRIGGER_EVENTS = 12` 数的是**事件条数**而非回合数。每回合写入 turn_start、check×n、narration 等 2~4 条事件，实际触发间隔约 4~6 回合；首次摘要（无历史）在开场回合即生成。
- `JournalMemory` 的 `summarizer` 从未接线（生产装配 `JournalMemory(repo)` 不传 summarizer），当前"摘要"实为模板拼接 + 截断 300 字。一旦真接线，触发回合的收尾将**同步阻塞一次 LLM 调用 + 落库**。
- 未来 M5-1 Graphiti 的 episode 摄取（LLM 实体抽取 + 向量化 + Neo4j 写入）是更重的慢操作，同样不能阻塞回合。

结论：落地一套"提交即返回、后台执行"的通用队列机制；摘要为首个消费者，M5 Graphiti 摄取直接复用同一实现、不改 M2 代码。

## 2. 目标与非目标

**目标**

1. 回合收尾零阻塞——主线程只做入队（无 DB 读、无网络）。
2. 机制通用——Graphiti 摄取复用同一队列类。
3. 测试确定性——队列可不启线程、支持同步处理（`run_pending()`）。
4. 对既有体系零侵入——不改 `MemoryService` 协议语义、不改图节点签名、不影响现有测试路径（T20/T21/T23 继续用同步 `JournalMemory`）。

**非目标（YAGNI，明确不做）**

- 不建持久化消息队列、多 worker、优先级、限流、重试退避（丢弃自愈已覆盖，见 §3）；
- 不引入 asyncio（全库同步模型；Graphiti 自身 async 桥接封装在 M5 适配器内部，与队列线程互不耦合）；
- 摘要暂不受 BudgetGuard 熔断管辖（量小且用量照常记账；M5 再议）。

## 3. 核心语义：watermark 追赶任务

队列存的是**追赶目标**而非"一次性动作"：

> 任务 = (key, watermark)。处理器语义固定为"把 key 追赶到 watermark"，
> 且必须**可从持久层重算**（不做增量假设）。

由此获得三条免费性质：

- **合并**：同一 key 多次提交只保留最大 watermark（最新票胜出），重算天然覆盖旧任务；
- **丢弃无害**：失败 / 退出 / 重启丢失任务 → 下一次提交自动补齐；
- **幂等**：处理器以水位限定范围重算（摘要用 `upto_turn=watermark`），晚到数据不串入已定稿段落。

具体映射：

| 消费者 | key | watermark | 处理器语义 |
|---|---|---|---|
| 摘要（M2，本文） | `{campaign_id}@{branch_id}`（复用 thread_id 格式） | turn_id | `update_summaries(c, b, upto_turn=t)`：不足阈值 no-op，够则 LLM 压缩 + append_summary |
| Graphiti 摄取（M5-1） | 同 thread_id | turn_id | 摄取截至 turn 的未入图事件（以入库水位为准） |

边界：**无法从持久层重算**的副作用型任务不适用本队列；当前与未来已知消费者均满足。

## 4. 组件与接口

| 文件 | 类型 | 职责 |
|---|---|---|
| `backend/app/tasks.py` | 新增 | 通用队列机制 `BackgroundQueue` |
| `backend/app/memory/scheduler.py` | 新增 | 摘要适配器 `BackgroundSummaries`（队列的第一个消费者） |
| `backend/app/memory/summarizer.py` | 新增 | `LLMSummarizer`：LLMClient → 摘要器（"真接线"） |
| `backend/app/memory/journal.py` | 修改 | summarizer 签名携带 `(campaign_id, branch_id, turn_id)` |
| `backend/app/storage/db.py` | 修改 | `PRAGMA journal_mode=WAL` + `busy_timeout` |

### 4.1 BackgroundQueue（通用机制）

```python
class BackgroundQueue:
    """单 daemon 工作线程 + 按 key 合并（最大 watermark 胜出）。
    失败捕获丢弃，由下一次 submit 自愈；不 start() 时用 run_pending() 同步跑（测试）。"""

    def __init__(self, handler: Callable[[str, Any], None], name: str = "bg"): ...
    def submit(self, key: str, payload: Any) -> None: ...  # 覆盖式合并 + 唤醒
    def start(self) -> None: ...                          # 生产：起 daemon 线程
    def run_pending(self) -> int: ...                     # 测试模式：同步处理全部待办
    def flush(self, timeout: float = 2.0) -> bool: ...    # 等待队列清空（退出收尾）
    def stop(self) -> None: ...                           # 停线程（先 flush 再 stop）
```

实现要点：

- 合并字典 + `threading.Condition`（没有"逐条"语义，不用 `queue.Queue`）；
- 处理中的 key 收到新提交 → 本轮结束后再跑一轮（不丢最新票）；
- 线程名 `ensemble-{name}`，`daemon=True`；
- 处理器异常一律捕获记日志，worker 永不退出。

### 4.2 BackgroundSummaries（摘要适配器）

```python
class BackgroundSummaries:
    def __init__(self, inner: JournalMemory, queue: BackgroundQueue): ...
    def update_summaries(self, campaign_id, branch_id, turn_id) -> None:
        self._queue.submit(f"{campaign_id}@{branch_id}", (campaign_id, branch_id, turn_id))
    # write_event / search / get_context：透传 inner
```

- 图节点继续持有"同一个 memory 对象"：`update_summaries` 从同步变为入队，**post_turn / memory_query 节点代码零改动**；
- handler 形如 `lambda key, payload: inner.update_summaries(*payload)`。

### 4.3 LLMSummarizer（真接线）与 journal.py 签名

```python
class LLMSummarizer:
    def __init__(self, client: LLMClient): ...
    def __call__(self, campaign_id, branch_id, turn_id, messages) -> str:
        return self._client.chat("extractor", messages,
                                 LlmContext(campaign_id, branch_id, turn_id))
```

- 走 `extractor` 角色（`Settings.extractor_model`，`config/pricing.yaml` 已覆盖该模型）→ usage 经 `LLMClient` 统一记账（role=extractor）；
- `journal.py` 的 `_summarizer` 调用签名由 `(messages)` 变为 `(campaign_id, branch_id, turn_id, messages)`（构造 `LlmContext` 需要 ids）；T13 的两个测试同步更新；
- 行为变更：生产摘要从"模板拼接 + 截断 300 字"升级为真实 LLM 压缩；模板兜底仅保留给未接线场景（如单测直接构造 `JournalMemory(repo)`）。

## 5. 时序

```
回合 N（主线程）
  post_turn ─ update_summaries(c,b,N) ─▶ BackgroundSummaries
                                          └ submit(thread_id, (c,b,N))   ← 仅入队，立即返回
                                                                          │
后台线程 ensemble-summary                                                 ▼
  循环取 key ─▶ JournalMemory.update_summaries(c,b,N)
                ├─ 不足阈值 → no-op
                └─ 触发 → LLMSummarizer（extractor 角色）
                          → append_summary(upto_turn=N) + usage 记账
```

- 阈值判定同样在后台线程完成：主线程零 DB 读；
- 下一回合 `memory_query` 读到的摘要可能落后一轮——【近期事件】兜底新鲜度（已知取舍，§9）。

## 6. 并发与存储

| 事实 | 现状 | 处置 |
|---|---|---|
| 仓储线程安全 | 每方法 `with Session(engine)` 独立会话；engine `check_same_thread=False` | 已满足，无需改动 |
| SQLite 双写者 | 主线程（事件/快照/检查点）与后台线程（摘要/usage）共写同一文件 | `make_engine` 连接时执行 `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`（WAL 为文件级属性、持久生效；busy_timeout 每连接显式化） |
| 摘要写并发 | 单 worker 串行处理 | 同战役摘要天然无并发写，无需额外锁 |

## 7. 失败与生命周期

- **失败**：worker 捕获异常、记日志、丢弃任务——**绝不降级写模板兜底垃圾**（拼接截断会污染后续摘要的 prior）；下一次 submit 自然重试（事件仍在 L2、last summary 未动）。
- **退出**：CLI 退出路径执行 `queue.flush(2.0)` 尽力收尾；丢任务无害（§3 自愈）。
- **测试**：构造队列不 `start()`，用 `run_pending()` 同步处理 → 行为断言确定性："submit 后内核未被调 → run_pending 后被调一次，且 payload 为最大 watermark"。

## 8. 对既有计划的集成点

| 计划位置 | 修改 |
|---|---|
| backend-core（T19 之前） | **插入 Task 18b**：`tasks.py` + `scheduler.py` + `summarizer.py` + `journal.py` 签名 + `db.py` pragma + 全部测试 |
| backend-core T24 + playable-web `_assemble` | `assemble()` / `SessionManager._assemble` 改为：`JournalMemory(repo, summarizer=LLMSummarizer(client))` → `BackgroundQueue(name="summary")` → `BackgroundSummaries` 包装传给图；`queue.start()`；`AppContext` 增加 queue 字段、CLI `main` 退出 `flush(2.0)`；会话 `close()` 逐 session `flush(2.0)+stop()`、切分支时旧队列 `stop()` |
| M5-1 Graphiti | `GraphitiMemory` 事件仍同步落 L2（权威）；图谱摄取以 `(thread_id, turn_id)` 提交到第二个队列实例（`BackgroundQueue` 复用，name="graph"）；`_GraphitiAdapter` 的异步桥接不变，仅在 worker 线程内被调用；检索保持同步（M5 范围） |

装配示意（T24 `assemble()` 目标形态；playable-web `_assemble` 同构，另在 `close()` 逐会话 `flush(2.0)+stop()`）：

```python
memory = JournalMemory(repo, summarizer=LLMSummarizer(client))
queue = BackgroundQueue(lambda key, payload: memory.update_summaries(*payload), name="summary")
queue.start()
bg_memory = BackgroundSummaries(memory, queue)
graph = build_game_graph(repo, module, bg_memory, client, guard, checkpointer)
```

## 9. 已知取舍

1. 摘要可能落后一轮（异步）→ 由 memory_query 的【近期事件】兜底新鲜度；
2. worker 不受 BudgetGuard 熔断管辖（记账照走、不拦截）→ M5 再议；
3. 队列不持久化 → 依赖"追赶 + 自愈"语义；若未来出现无法从持久层重算的任务类型，需另行设计。

## 10. 测试计划（TDD 红→绿）

- `backend/tests/test_tasks.py`（新）：合并只跑最大 watermark；处理器异常不崩、下次可再跑；`flush` 等待完成；`run_pending` 返回处理数；`stop` 后不再处理新提交。
- `backend/tests/memory/test_scheduler.py`（新）：submit 后内核未被调 → `run_pending()` 后恰好一次；`search / get_context / write_event` 透传。
- `backend/tests/memory/test_summarizer.py`（新）：role=="extractor"、`LlmContext` 三字段透传、usage 落库一行（FakeLLM + 假 sink 断言）。
- `backend/tests/memory/test_journal.py`（改）：两个 summarizer 测试改新签名。
- `backend/tests/storage/`（微增）：`journal_mode == "wal"`、`busy_timeout` 生效。
- 全量回归：现有 85 条全绿 + 新增。
