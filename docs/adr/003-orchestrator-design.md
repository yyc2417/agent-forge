# ADR-003：Orchestrator 设计决策

> **状态**：已采纳
> **日期**：2026-06-07
> **决策者**：宇诚
> **影响范围**：AgentForge 多 Agent 编排架构

---

## 背景

AgentForge 需要一个编排层来协调多个 Specialist Agent 协作完成任务。核心需求：

1. **任务拆解**：将用户的高层任务分解为可执行的子任务
2. **Agent 路由**：将子任务分配给合适的 Specialist
3. **条件回退**：审查不通过时自动回退重新执行
4. **可扩展**：支持新增 Specialist 类型，支持自定义工作流

---

## 决策 1：继承 BaseAgent 而非组合

### 备选方案

**方案 A：继承 BaseAgent（我们的选择）**
- Orchestrator 覆盖 `_build_graph()` 构建编排工作流图
- 复用 LLM、Bus、init 等基础设施

**方案 B：组合模式（持有 BaseAgent）**
- Orchestrator 内部持有一个 BaseAgent 用于 LLM 推理
- 编排逻辑完全独立

**方案 C：完全独立**
- Orchestrator 不继承任何类，自己管理 LLM 和 Bus

### 决定

选择方案 A。理由：
- `_build_graph()` 的设计初衷就是"子类可以覆盖以添加额外节点"
- 复用基础设施减少重复代码
- 体现模板方法模式的设计价值

### 风险

Orchestrator 不使用 `tool_node`（tools=[]），部分 BaseAgent 方法被浪费。但这是可接受的代价。

---

## 决策 2：直接调用 + Bus 事件发布

### 备选方案

**方案 A：纯 Bus 通信**
- Orchestrator publish REQUEST → Specialist handler 收到 → publish RESPONSE
- 完全解耦

**方案 B：纯直接调用**
- `specialist.run(task)` 直接调用
- 控制流最简单

**方案 C：直接调用 + Bus 事件发布（我们的选择）**
- 调用 `specialist.run(task)` 获取结果
- 同时通过 Bus 发布 REQUEST/RESPONSE 事件
- 控制流清晰 + 可观测性

### 决定

选择方案 C。理由：
- 当前 MessageBus 是同步阻塞的，纯 Bus 模式下 REQUEST-RESPONSE 配对需要引入队列/回调机制，复杂度高
- Bus handler 中不应调用 `agent.run()`（会导致递归）
- 直接调用 + Bus 事件让 Demo 中 `bus.get_history()` 能看到完整的任务分发链路

### 风险

不是"真正的"通过 Bus 通信，Bus 只用于观测。但当前阶段可观测性比通信解耦更重要。

---

## 决策 3：LLM 拆解 + 三层防护

### 方案

Orchestrator 用 LLM 将用户任务拆解为 JSON 格式的子任务列表。三层防护确保拆解不会失败：

1. **正则提取 JSON**：LLM 输出可能包含多余文本，用 `\{.*\}` 正则提取
2. **json.loads 解析**：JSON 格式可能不对，try/except 捕获
3. **fallback 计划**：解析失败时使用默认的 `coder` 单步计划

### 决定

选择 LLM 拆解 + 三层防护。理由：
- 动态拆解比硬编码工作流灵活得多
- 三层防护保证"宁可降级运行，不可崩溃"
- 兜底的 coder 单步计划对大多数编程任务足够

---

## 决策 4：审查判定采用双条件

### 方案

Reviewer 的 system prompt 要求输出【通过】或【不通过】。判定逻辑：

```python
passed = "通过" in result and "不通过" not in result
```

### 为什么用双条件？

- 单条件 `"通过" in result` 会误判 "不通过" 为通过（因为 "通过" 是 "不通过" 的子串）
- 双条件同时检查正反两面，大幅减少误判
- 加上 max_retries 兜底，即使误判也不会无限循环

---

## 参考资料

- [LangGraph Multi-Agent 文档](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [Anthropic - Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)

---

> **最后更新**：2026-06-07
