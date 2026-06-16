# 阶段 2学习笔记：LangGraph 工作流与多 Agent 编排

> **日期**：2026-06-07
> **学习范围**：Orchestrator 设计、StateGraph 多节点编排、条件回退

---

## StateGraph 不只是 Agent 循环

阶段 0学到的 StateGraph 用法是 ReAct 循环：

```
agent_node → should_continue → tool_node → agent_node → ...
```

这只有两个节点 + 一个条件边。阶段 2发现 StateGraph 可以建模更复杂的工作流：

```
decompose → execute → review → aggregate
               ↑         │
               └─(retry)─┘
```

四个节点 + 两个条件边 + 回退环。这是状态机的本质——任何可以用有限状态机描述的流程，都可以用 StateGraph 建模。

---

## ReAct 模式 vs Plan-and-Execute 模式

| 维度 | ReAct（第 0-1 周） | Plan-and-Execute（阶段 2） |
|------|-------------------|---------------------------|
| 决策者 | 单个 Agent 自己决定下一步 | Orchestrator 预先规划，分配给 Specialist |
| 灵活性 | 高——每步都可以调整策略 | 中——计划一旦制定就按序执行 |
| 可控性 | 低——LLM 可能走偏 | 高——拆解结果可审查 |
| 适用场景 | 简单任务、单 Agent | 复杂任务、多 Agent 协作 |

AgentForge 的设计是**混合模式**：
- Orchestrator 层用 Plan-and-Execute（拆解 → 执行）
- 每个 Specialist 内部用 ReAct（自主推理 + 工具调用）

---

## Orchestrator 的关键设计取舍

### 为什么不让 Agent 之间直接通信？

直觉上，Coder 完成后直接告诉 Reviewer "代码写好了" 似乎更简单。但问题是：
- Coder 必须知道 Reviewer 的存在
- 如果要加 Tester Agent，得改 Coder 的代码
- 消息流散落在各处调用中，无法统一追踪

通过 Orchestrator 集中调度：
- 每个 Agent 只和 Orchestrator 交互
- 新增 Agent 只需注册到 specialists 字典
- 所有消息通过 Bus，可追踪可回放

### LLM 拆解的可靠性问题

LLM 输出的 JSON 不一定格式正确。实际测试中发现：
- 有时 LLM 会在 JSON 外面包裹 ```json ``` 代码块
- 有时会添加解释性文字
- 偶尔字段名不一致

三层防护解决了这些问题：
1. 正则提取 `{...}` 块
2. try/except 解析
3. fallback 到默认计划

这个经验很有价值：**永远不要假设 LLM 输出格式完美，总是做降级处理**。

### 审查回退的终止条件

没有 max_retries 的回退可能无限循环：
- Coder 写代码 → Reviewer 说不行 → Coder 改 → Reviewer 还说不行 → ...

max_retries=2 是一个经验值：
- 大多数任务 1 次就通过了
- 2 次重试能覆盖大部分需要修改的情况
- 超过 2 次通常意味着 Reviewer 过于苛刻，强制通过更合理

---

## 思考题回答

### 什么情况下应该让 Agent 自己决定下一步，而不是按预设流程走？

当任务的步骤不可预测时。比如：
- 调试任务：Agent 需要根据错误信息动态决定"读日志/改代码/跑测试"的顺序
- 探索性任务：Agent 需要根据中间结果决定下一步做什么

AgentForge 的设计中，Specialist 内部的 ReAct 循环就是"Agent 自己决定"——Agent 自主选择调用哪个工具、调几次。Orchestrator 的 Plan-and-Execute 只控制宏观流程（谁做什么），不干预微观决策（怎么做）。

### 如何防止 Agent 陷入无限循环？

三层防线：
1. **max_turns**（BaseAgent 级）：限制单个 Agent 的思考轮数
2. **max_retries**（Orchestrator 级）：限制回退重试次数
3. **recursion_limit**（LangGraph 级）：限制整个 StateGraph 的递归深度

---

## 本周收获

1. **StateGraph 是通用的流程建模工具**，不只是 Agent 循环。任何"节点 + 条件边 + 状态"的流程都可以用它。
2. **混合模式（Plan-and-Execute + ReAct）** 比纯 ReAct 更可控，比纯 Plan-and-Execute 更灵活。
3. **永远对 LLM 输出做降级处理**——JSON 解析会失败，审查判定会误判，回退会无限循环。
4. **可观测性是"免费"的**——通过 Bus + LoggingInterceptor，不改 Agent 代码就能看到完整的事件流。

---

> **最后更新**：2026-06-07
