# 阶段 0学习笔记：Agent 的本质

> **日期**：2026-06-06
> **前置阅读**：[Lilian Weng — LLM Powered Autonomous Agents](https://lilianweng.github.io/posts/2023-06-23-agent/)

---

## 一句话总结

> Agent 的本质是让 LLM 在循环中自主决策——感知环境、规划步骤、调用工具、根据反馈调整。单 Agent 的天花板是上下文窗口和注意力分散，多 Agent 通过角色分工解决这个问题。

---

## Agent 四组件理解

### 1. LLM —— Agent 的大脑

LLM 是 Agent 的核心驱动引擎。不同于传统软件中硬编码的 if-else 决策树，LLM 可以根据自然语言输入、当前上下文、可用工具的描述，自主决定"下一步做什么"。

**Agent 场景下 LLM 的特殊要求**：

- **确定性 > 创造性**：Agent 需要可复现的决策，所以 `temperature=0.0` 是标配。一个随机选择工具的 Agent 是不可靠的。
- **Function Calling 能力**：LLM 需要能理解 JSON Schema 格式的工具描述，并生成结构化的 tool_calls。这不是所有模型都支持的——DeepSeek 兼容 OpenAI 的 Function Calling 格式是个大优势。
- **上下文长度**：Agent 的对话历史会快速膨胀（用户消息 → AI 思考 → 工具调用 → 工具结果 → AI 再思考...），需要 LLM 有足够的上下文窗口。

---

### 2. 规划（Planning）—— Agent 的策略

规划决定了 Agent "怎么干"。两种主流模式：

| 模式 | 描述 | 代表实现 |
|------|------|----------|
| **ReAct** | 推理（Reasoning）和行动（Acting）交替进行，每轮思考一步做一步 | LangGraph Agent |
| **Plan-Execute** | 先制定完整计划，再逐步执行 | LangGraph 的 Plan-and-Execute |

阶段 0我们用的是 ReAct 模式。原因：
1. 实现简单——只需要一个循环 + 两个节点
2. 调试友好——每一步的思考和行动都在消息流中可见
3. 经典范式——ReAct 是 Agent 领域的基础，值得深入理解

ReAct 的局限性：对于需要长远规划的任务（如"开发一个完整的 Web 应用"），ReAct 容易陷入短视。阶段 2会在 Orchestrator 中引入 Plan-Execute 模式来弥补。

---

### 3. 工具调用（Tool Use）—— Agent 的双手

没有工具，LLM 只是"能说话"。有了工具，LLM 才"能做事"。

**Function Calling 的工作原理**：

```
1. 定义工具 → LangChain 自动生成 JSON Schema
   @tool
   def read_file(path: str) -> str:
       """读取文件内容"""
       ...

   → {"name": "read_file", "parameters": {"path": {"type": "string", ...}}}

2. bind_tools() → Schema 随请求发送给 LLM
   llm_with_tools = llm.bind_tools([read_file, write_file, run_shell])

3. LLM 推理 → 决定调用哪个工具，生成 tool_calls
   {"tool_calls": [{"name": "read_file", "args": {"path": "README.md"}}]}

4. 执行工具 → 结果包装为 ToolMessage 返回给 LLM

5. LLM 拿到结果 → 基于新信息继续推理
```

**工具设计的关键教训**：
- **docstring 就是 Schema**：LLM 通过你的 docstring 理解工具的用途，写得好=调用准确率高
- **错误要返回，不要抛出**：工具执行失败时，返回错误消息给 LLM（而非抛异常），LLM 可以根据错误信息调整策略
- **安全是设计的起点**：工具系统中的安全措施（黑名单、超时、截断）必须在第一天就考虑，不能"后面再加"

---

### 4. 记忆（Memory）—— Agent 的上下文

阶段 0 Agent 的"记忆"就是对话历史消息列表。这是最简单的短期记忆形式。

**当前形式的局限**：
- 每轮交互独立——关掉程序再打开，Agent 什么都不记得
- 上下文线性增长——对话越长，token 消耗越大，成本越高

阶段 3我们会实现：
- **短期记忆**：滑动窗口 + 摘要压缩
- **长期记忆**：向量数据库 + 语义检索（**2026-09 校准**：实际实现为 JSON 文件 KV + 关键词检索——当前任务规模下向量库的收益不足以抵消其复杂度，见 phase3 笔记）
- **共享记忆**：多个 Agent 之间的上下文共享

---

## 单 Agent Demo 的收获

### 从 create_react_agent 到 StateGraph

最大的收获是理解了"封装"和"原理"之间的差距。`create_react_agent` 一行搞定，但如果有人问"内部怎么工作的？"——答不上来就暴露了。

手写 StateGraph 之后才真正理解了：
1. **节点就是纯函数**：输入 state，返回 state 的部分更新
2. **条件边是核心**：`should_continue` 函数是 Agent 循环的决策点
3. **状态合并是自动的**：`add_messages` reducer 让消息列表的管理零心智负担

### 工具调用比你想象的脆弱

跑 Demo 时发现，LLM 对工具的"理解"取决于：
- 工具描述的清晰程度（docstring 质量）
- 参数命名的语义化程度（`path` 比 `p` 好得多）
- 当前上下文中是否有足够的信息来填充参数

工具调用的可靠性不是 LLM 一个人的事——工具设计者（我们）也承担了很大责任。

---

## 怎么给别人讲

**30 秒版**：
> "Agent 本质是 LLM 在循环中自主决策：推理、规划、调用工具、根据反馈调整。我的项目用 LangGraph 的 StateGraph 来建模这个循环——两个节点（agent + tools），一条条件边（should_continue），状态就是对话消息列表。"

**5 分钟版关键词**：
- ReAct 模式 vs Plan-Execute
- StateGraph = 节点 + 条件边 + 状态 reducer
- Function Calling = 工具 Schema + bind_tools + tool_calls 结构化输出
- 安全性 = 黑名单 + 超时 + 输出截断（纵深防御）
- 防无限循环 = recursion_limit + 轮数计数器（双重保护）

---

## 下一步：阶段 1

- 从 Demo 代码中提取可复用的 Agent 基类
- 实现 Agent 间消息协议（Message Bus 的前身）
- 思考：如果要让两个 Agent 协作完成一个任务，需要改哪些地方？

---

> **最后更新**：2026-06-06（2026-09-29 校准长期记忆技术路线注记）
