# ADR-001：选择 LangGraph 作为 Agent 编排框架

> **状态**：已采纳
> **日期**：2026-06-06
> **决策者**：宇诚
> **影响范围**：整个 AgentForge 项目的 Agent 编排方式

---

## 背景

AgentForge 是一个多 Agent 协作框架，核心需求是：

1. **灵活的任务编排**：不同 Demo 场景需要不同的协作流程（软件开发需要严格工序，研究报告需要并行搜集），不能写死在线性流水线里
2. **动态路由**：Agent 应该根据当前状态决定下一步——哪个 specialist 来处理？任务拆完了吗？需要人工确认吗？
3. **可展示性**：技术选型本身要能体现架构设计能力，而不仅仅是"我用过这个框架"
4. **生态稳定**：不能选一个下周就 breaking change 的框架

---

## 备选方案

### 方案 A：CrewAI

**概述**：高层封装的多 Agent 框架，定义角色（Agent）+ 任务（Task）+ 团队（Crew），自动编排。

**优点**：
- 上手极快——三个类就能跑通多 Agent 协作
- 文档友好，有大量示例

**缺点**：
- **封装太厚**：内部的协作流程对开发者不可见，难以展示对底层原理的理解
- **线性流水线**：协作模式是预定义的顺序执行，不支持动态分支和条件路由
- **扩展性受限**：要自定义一个"运行时判断该找谁"的路由逻辑，几乎要 hack 框架内部

**决策**：❌ 不选。原因——在技术讨论中，别人更想听你解释 Agent 循环怎么实现的，而不是"我调了个 API"。

---

### 方案 B：AutoGen（微软）

**概述**：微软研究院出品的对话式多 Agent 框架，Agent 之间通过消息传递协作。

**优点**：
- 对话式多 Agent 设计思路新颖，天然适合多轮交互
- 微软背书，社区活跃度高
- 支持 Human-in-the-Loop 内建

**缺点**：
- **版本迭代太快**：API 不稳定性是已知问题，从 0.2 → 0.4 经历了多次 breaking change
- **学习曲线陡峭**：概念模型复杂（ConversableAgent, GroupChat, GroupChatManager...）
- **长期维护风险**：社区版本（pyautogen）和 Microsoft 内部的 AutoGen 分裂，未来方向不明

**决策**：❌ 不选。对于一个需要稳跑 4 周的项目，框架稳定性优先级高于新奇性。

---

### 方案 C：LangGraph（LangChain 生态）

**概述**：用状态图（StateGraph）来建模 Agent 的工作流，本质是 DAG/FSM。

**优点**：
- **状态图驱动**：Agent 协作被建模为节点和边的有向图，这是展示架构设计能力的好素材——你会用图论建模问题
- **灵活度最高**：条件边、并行分支、子图嵌套——想怎么路由就怎么路由
- **生态成熟**：LangChain 生态的一部分，文档、社区、工具链完善
- **可控性**：状态图的每一步都是显式的，调试和观测都非常直观
- **通用性**：LangGraph 在 AI Agent 领域是"安全牌"——大家大概率听说过

**缺点**：
- 学习曲线稍陡：需要理解图、节点、边、状态、Reducer 的概念
- API 仍在迭代：需要锁定版本避免意外

**决策**：✅ **选择 LangGraph。**

---

## 决定的理由

选择 LangGraph 不是因为它"最好"，而是因为它**最适合当前场景**：

1. **设计可展示性 > 开发速度**：我们用两周搭基础架构，是为了让项目有清晰的架构可讲。LangGraph 的状态图模型就是最好的"可讲素材"。

2. **灵活度匹配需求**：场景一（软件研发）需要顺序+分支，场景二（研究报告）需要并行搜集。只有状态图原生支持这些模式。

3. **兜底方案**：如果 LangGraph 后续出现严重 bug，可以通过 `langchain-openai` 直接退回到纯 Function Calling + 手写循环——因为我们理解了原理。

---

## 风险与缓解

| 风险 | 可能性 | 缓解措施 |
|------|--------|----------|
| LangGraph API breaking change | 中 | 锁定版本 `>=0.2.0,<0.4.0`，升级前阅读 CHANGELOG |
| 状态图建模过于复杂 | 低 | 阶段 0从最简单的两节点图开始，逐步增加复杂度 |
| DeepSeek 对 Function Calling 支持不稳定 | 低 | DeepSeek 兼容 OpenAI 格式，已多次验证 |

---

## 参考资料

- [LangGraph 官方文档 — Concept Guide](https://langchain-ai.github.io/langgraph/concepts/)
- [LangGraph Quick Start 教程](https://langchain-ai.github.io/langgraph/tutorials/introduction/)
- [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Lilian Weng — LLM Powered Autonomous Agents](https://lilianweng.github.io/posts/2023-06-23-agent/)

---

> **最后更新**：2026-06-06
