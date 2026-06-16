# ADR-002：选择 Pub/Sub 消息总线作为 Agent 通信机制

> **状态**：已采纳
> **日期**：2026-06-07
> **决策者**：宇诚
> **影响范围**：整个 AgentForge 项目的 Agent 间通信方式

---

## 背景

AgentForge 是多 Agent 协作框架，Agent 之间需要传递任务、结果和状态信息。核心需求：

1. **解耦**：新增 Agent 不需要修改已有 Agent 的代码
2. **可观测**：所有消息可追踪、可回放，便于调试和 Dashboard 展示
3. **可扩展**：从单机多 Agent 到分布式部署，通信层可替换
4. **支持拦截**：关键操作可以暂停等待人工确认（Human-in-the-Loop）

---

## 备选方案

### 方案 A：点对点直接调用

Agent A 直接调用 Agent B 的方法（如 `agent_b.handle(task)`）。

**优点**：
- 实现最简单，无额外中间层
- 调用关系明确，调试直观

**缺点**：
- 强耦合：Agent A 必须持有 Agent B 的引用
- 难扩展：新增 Agent 需要修改所有相关 Agent
- 消息散落：无法统一追踪消息流
- 无拦截点：Human-in-the-Loop 需要在每个调用点手动添加

**决策**：不选。多 Agent 系统的核心挑战是"谁该处理什么"，点对点模式把这个决策硬编码在发送方中。

---

### 方案 B：共享状态（LangGraph State）

所有 Agent 读写同一个 LangGraph State 对象，通过状态变更来传递信息。

**优点**：
- LangGraph 原生支持，无需额外组件
- 状态变更自动被 LangGraph 的 reducer 处理

**缺点**：
- 仅适用于同一个 StateGraph 内的 Agent
- 不适合跨图通信（如独立的 Orchestrator 和多个 Specialist Graph）
- 状态冲突风险：多个 Agent 同时修改同一字段
- 消息语义不明确：状态变更不等于"消息"，缺少 intent/reply_to 等元数据

**决策**：不选作为主通信机制。State 适合同一工作流内的状态共享，但 Agent 间的任务委派和结果汇报需要更结构化的消息协议。

---

### 方案 C：消息队列（Redis/RabbitMQ/Kafka）

使用外部消息中间件，Agent 作为生产者/消费者。

**优点**：
- 天然支持分布式部署
- 内置持久化、消费者组、重试机制
- 生产级可靠性

**缺点**：
- 引入外部依赖（需要安装 Redis/RabbitMQ）
- 增加部署复杂度（Docker Compose 需要多容器）
- 对于单机多 Agent 场景过于重量
- 学习曲线陡（需要理解 AMQP/Kafka 协议）

**决策**：不选作为阶段 1实现。但我们的 MessageBus 接口设计参考了消息队列的 Pub/Sub 模式，未来可以无缝替换。

---

### 方案 D：进程内 Pub/Sub 消息总线（我们的选择）

单进程内的发布-订阅消息总线，统一消息格式，支持拦截器。

**优点**：
- 零外部依赖：纯 Python 实现，`pip install` 即可使用
- 解耦：发送方和接收方互不知道对方的存在
- 可观测：所有消息经过总线，统一追踪
- 可拦截：拦截器链支持 Human-in-the-Loop
- 可替换：接口与 Redis Pub/Sub 兼容，未来可升级

**缺点**：
- 仅限单进程（不支持跨机器通信）
- 无持久化（进程退出后消息丢失）
- 无重试机制（handler 失败不会自动重试）

**决策**：选择方案 D。

---

## 决定的理由

1. **匹配当前阶段**：项目处于 MVP 阶段，单机多 Agent 足够。引入 Redis 是过早优化。

2. **接口兼容未来升级**：MessageBus 的 `publish/subscribe` 接口与 Redis Pub/Sub 一致。升级到分布式时，只需替换内部实现：

   ```python
   # 当前：内存实现
   bus = MessageBus()

   # 未来：Redis 实现（接口不变）
   bus = RedisMessageBus(redis_url="redis://localhost:6379")
   ```

3. **可观测性是核心需求**：所有消息经过总线，天然支持日志、Dashboard、消息回放。这在点对点模式下几乎不可能实现。

4. **拦截器是 HITL 的基础**：Human-in-the-Loop 需要在消息到达 Agent 之前暂停确认。拦截器链是责任链模式的直接应用。

---

## 风险与缓解

| 风险 | 可能性 | 缓解措施 |
|------|--------|----------|
| 单进程限制，无法扩展到多机 | 中 | 接口设计兼容 Redis Pub/Sub，可无缝替换 |
| 同步阻塞：handler 执行慢会拖慢 publish | 中 | 当前阶段 handler 只做轻量操作；后续可升级为 async |
| 消息丢失（无持久化） | 低 | 单机场景下进程退出才丢失，可接受；后续可加文件持久化 |
| handler 递归调用导致栈溢出 | 低 | handler 中不应调用 agent.run()，由 Orchestrator 统一编排 |

---

## 参考资料

- [LangGraph Multi-Agent 文档](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [Enterprise Integration Patterns — Publish-Subscribe Channel](https://www.enterpriseintegrationpatterns.com/PublishSubscribeChannel.html)
- [AutoGen 对话式设计](https://microsoft.github.io/autogen/docs/topics/conversation-patterns)

---

> **最后更新**：2026-06-07
