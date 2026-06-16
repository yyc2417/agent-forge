# 阶段 1学习笔记：Agent 抽象与消息总线

> **日期**：2026-06-07
> **学习范围**：Agent 基类设计、消息协议、Pub/Sub 通信模式

---

## 从 Demo 到基类：提取通用模式

阶段 0的 `phase0_agent_demo.py` 有 682 行代码，三个 Step 之间有大约 70% 的重复代码。重复的部分就是"通用模式"：

| 重复代码 | 提取为 |
|----------|--------|
| `AgentState(TypedDict)` 定义 | `BaseAgent` 类中保留 |
| `agent_node` 函数 | `BaseAgent.agent_node()` 方法 |
| `tool_node` 函数 | `BaseAgent.tool_node()` 方法 |
| `should_continue` 函数 | `BaseAgent.should_continue()` 方法 |
| StateGraph 构建 + 编译 | `BaseAgent._build_graph()` 方法 |
| SystemMessage 注入 | `BaseAgent.run()` 方法 |
| `safe_print` 等工具函数 | `agent_forge/utils.py` 模块 |

**提取后的效果**：创建一个完整的 Agent 从 ~100 行降到 3 行：

```python
# phase0_demo Step 3：~100 行手动构建
# phase1 Step 1：3 行
agent = BaseAgent(name="assistant", role="通用助手", tools=ALL_TOOLS)
result = agent.run("写一个排序函数")
```

**哪些没有提取？**
- `create_react_agent`（Step 1 的预构建方案）：这是 LangGraph 的高层 API，不适合封装进基类
- 交互循环（`run_interactive_loop`）：这是 Demo 的 UI 层，不是 Agent 的核心逻辑
- 具体的 SystemMessage 内容：通过 `get_system_prompt()` 方法让子类定制

---

## 消息协议设计中的权衡

### 为什么 payload 用 `dict[str, Any]` 而不是泛型？

Python 的 `dataclass` 不支持泛型字段（不像 TypeScript 的 `Message<T>`）。如果用泛型：

```python
# 理想但不支持
@dataclass
class Message(Generic[T]):
    payload: T
```

需要引入 `typing.Generic` + 运行时类型检查，增加了复杂度。当前阶段不同 Agent 传不同结构的 payload，用 `dict` 保持灵活性。

如果后续需要严格的 payload 验证，可以考虑：
- 在 `publish()` 时加 schema 检查（JSON Schema 验证）
- 切换到 pydantic 的 `BaseModel`，支持字段验证和类型检查

### 为什么 `role` 用 `str` 而不是 Enum？

Agent 的角色是动态的。阶段 2 Orchestrator 会在运行时根据任务需要动态创建 Specialist Agent，角色名在编写代码时无法预知。如果 `role` 是 Enum，每次新增角色都要改枚举定义——这违反了开闭原则。

### `reply_to` 的局限性

当前 `reply_to` 只是元数据标记，不做自动配对。Agent A 发出 REQUEST 后不会"等待" Agent B 的 RESPONSE——同步模型下没有"等待"机制。

REQUEST-RESPONSE 的编排由调用方手动管理（Demo Step 3 中人工控制流程）。阶段 2引入 Orchestrator 后，由 Orchestrator 负责请求-响应的自动编排。

---

## 为什么 Agent 不直接互相调用？

这是一个关键的设计问题。直觉上，Coder Agent 完成后直接调用 Reviewer Agent 似乎更简单：

```python
# 点对点：简单但耦合
coder_result = coder.run(task)
review_result = reviewer.run(f"审查: {coder_result}")
```

问题在于：

1. **Coder 必须知道 Reviewer 的存在**。如果后来需要加一个 Tester Agent，就要改 Coder 的代码。
2. **消息不可追踪**。Coder 直接调 Reviewer，中间发生了什么只有两个 Agent 知道，Dashboard 看不到。
3. **无法拦截**。如果想让人工确认 Coder 的产出，需要在 Coder 和 Reviewer 之间插入确认逻辑——改两个 Agent 的代码。

通过 Message Bus：

```python
# 通过 Bus：解耦且可观测
coder_result = coder.run(task)
bus.publish(Message(role="coder", intent=REQUEST, payload={"result": coder_result}))
# Reviewer 通过订阅自动收到，Coder 完全不知道 Reviewer 的存在
```

**代价**是增加了一层中间件，代码稍微多一点。但对于多 Agent 系统，这个代价是值得的——因为 Agent 数量会增长，而耦合度必须控制住。

---

## Pub/Sub vs 点对点：如果只有 2 个 Agent 还需要 Bus 吗？

即使只有 2 个 Agent，Bus 也提供了价值：

1. **可观测性**：`bus.get_history()` 可以看到完整的消息链
2. **拦截器**：不需要改 Agent 代码就能添加人工确认
3. **扩展准备**：加第 3 个 Agent 时零成本（只需订阅）

当然，如果只是写一个脚本测试 2 个 Agent 的交互，直接调用也完全可以。Bus 是为系统级设计准备的，不是为临时脚本准备的。

---

## 思考题回答

### 如果 Orchestrator 挂了，其他 Agent 还能继续工作吗？

当前设计中，Orchestrator（阶段 2实现）负责编排 Agent 的执行顺序。如果 Orchestrator 挂了：
- 正在执行中的 Agent 不受影响（它们有自己的 StateGraph 循环）
- 但不会有新的 Agent 被调度
- 这是一个"中心化编排 + 去中心化执行"的架构

更理想的方案是"完全去中心化"——Agent 之间直接通过 Bus 协商谁来做下一步，不依赖 Orchestrator。但这增加了复杂性（需要协商协议、冲突解决），阶段 2先用中心化方案，后续探索去中心化。

### 消息顺序乱了怎么办？

当前是同步实现，`publish()` 是阻塞的——前一条消息的所有 handler 执行完后才会 publish 下一条。因此消息顺序天然有序（按 timestamp 排序）。

如果升级为异步，需要考虑：
- 消息 ID（UUID）保证唯一性
- timestamp 保证排序
- 如果需要严格的顺序保证，可以引入序列号（sequence_number）字段

### 为什么选 Pub/Sub 而不是点对点？

见上面的详细分析。核心原因：解耦 + 可观测 + 可扩展。详见 `docs/adr/002-message-bus-design.md`。

---

## 本周收获

1. **抽象不是目的，复用才是**。从 Demo 提取 BaseAgent 不是为了"面向对象"，而是因为 3 个 Step 之间有 70% 的重复代码。
2. **消息协议是系统的骨骼**。统一的消息格式让 Agent 的添加、删除、替换都在同一条路径上，而不是散落在各种 dict 和 tuple 中。
3. **可观测性应该是"免费"的**。通过 Bus + 拦截器，不需要改 Agent 代码就能看到内部运转。这比在每个 Agent 里手写日志好得多。

---

> **最后更新**：2026-06-07
