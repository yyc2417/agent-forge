# Agent 基类设计

> **状态**：阶段 1已实现 | **最后更新**：2026-06-07

---

## 设计理念

Agent 的核心公式：

```
Agent = LLM + 规划 + 工具 + 记忆
          ↑      ↑      ↑      ↑
        大脑    策略    双手   上下文
```

### 当前阶段（阶段 3）的聚焦范围

| 组件 | 状态 | 说明 |
|------|------|------|
| LLM | ✅ 已实现 | `agent_forge/llm/providers.py` — DeepSeek 工厂函数 |
| 规划 | ✅ 已封装 | `agent_forge/agents/base.py` — BaseAgent 内置 ReAct 循环 |
| 工具 | ✅ 已实现 | `agent_forge/tools/` — 文件读写 + Shell 执行 + 搜索 + ToolRegistry |
| 通信 | ✅ 已实现 | `agent_forge/bus/` — Message Bus + 统一消息协议 |
| 记忆 | ✅ 已实现 | `agent_forge/memory/` — 短期记忆 + 长期记忆 + 会话管理 |

阶段 1的核心产出是 BaseAgent 基类和 Message Bus。BaseAgent 从 phase0_demo 中提取了 ReAct 循环的通用模式（agent_node / tool_node / should_continue / StateGraph 构建），使得创建新 Agent 从 ~100 行代码降到 3 行。Message Bus 提供了 Agent 间的解耦通信，支持 Pub/Sub 路由和拦截器链。

---

## BaseAgent 基类架构

BaseAgent 封装了 ReAct 循环的完整实现，从 phase0_demo Step 3 提取：

```
  BaseAgent.__init__()
    │
    ├─ 创建/接收 LLM
    ├─ bind_tools()（如果有工具）
    ├─ _build_graph()  →  编译 StateGraph
    └─ 注册到 Message Bus（如果有）

  BaseAgent.run(user_input)
    │
    ├─ 构建消息列表（SystemMessage + HumanMessage）
    ├─ _compiled.invoke()  →  执行 ReAct 循环
    │    │
    │    ├─ agent_node()       ← LLM 推理
    │    ├─ should_continue()  ← 条件路由
    │    │    ├─ 有 tool_calls → tool_node() → 回到 agent_node
    │    │    └─ 无 tool_calls → END
    │    └─ tool_node()        ← 工具执行
    │
    └─ 提取最终 AIMessage.content
```

---

## 关键设计决策

### 决策 1：temperature = 0.0

**为什么**：Agent 场景中，LLM 的每次决策都会放大误差。一个随机的工具选择可能让整个任务偏离轨道。0.0 的 temperature 保证可复现性——同样的输入产生同样的决策。

**例外情况**：创意生成类任务（如写文案）可以适当提高 temperature。后续在 Agent 基类中会支持按任务类型动态设置。

---

### 决策 2：bind_tools() 而非手写 prompt

**为什么**：LangChain 的 `bind_tools()` 会自动将工具的 type hints 和 docstring 转换为 OpenAI Function Calling 格式的 JSON Schema。这比手写 prompt 描述工具有几个优势：

1. **类型安全**：Schema 由代码自动生成，不存在"prompt 和代码不一致"的问题
2. **结构化输出**：LLM 返回的 tool_calls 是结构化的（name + args dict），不需要解析自由文本
3. **兼容性**：OpenAI/DeepSeek/Qwen 都支持这套格式

---

### 决策 3：安全第一 —— Shell 工具黑名单

**为什么**：不能假设 LLM 永远不会调用危险命令。黑名单是纵深防御的第一层：

```
黑名单（本工具） → 超时保护（30s） → 输出截断（10K chars）
       ↑                ↑                    ↑
   防破坏操作        防死循环/卡死        防上下文溢出
```

这不是最终的安全方案——生产环境还需要 Docker sandbox 和权限系统（阶段 3 Tool System 会涉及）。

---

### 决策 4：防无限循环 —— 双重保护

| 保护层 | 机制 | 位置 |
|--------|------|------|
| StateGraph 级 | `recursion_limit=10~15` | `agent.invoke(config={...})` |
| 业务逻辑级 | `ai_count > 5 → 强制终止` | `should_continue()` |

单靠 `recursion_limit` 不够：如果 Agent 在一个"不需要调工具但反复思考"的循环里，`recursion_limit` 不会触发（因为没有新增节点）。业务逻辑级的保护可以兜底。

---

## 后续扩展方向

| 周 | 扩展内容 |
|----|----------|
| ~~阶段 1~~ | ~~Agent 基类 + Message Bus~~ ✅ 已完成 |
| ~~阶段 2~~ | ~~Orchestrator Agent——多 Agent 编排~~ ✅ 已完成 |
| 阶段 3 | Memory 系统接入——跨轮次上下文保持 |
| 阶段 4 | 与 Dashboard 集成——实时查看 Agent 状态和消息流 |

---

## 代码位置

- `agent_forge/agents/base.py` — BaseAgent 基类（已实现）
- `agent_forge/bus/` — Message Bus（已实现）
- `agent_forge/llm/providers.py` — LLM 工厂函数
- `agent_forge/tools/` — 工具实现
- `agent_forge/utils.py` — 通用工具函数
- `demos/phase0_agent_demo.py` — 阶段 0演示（单 Agent，三步渐进式）
- `demos/phase1_agent_demo.py` — 阶段 1演示（基类 + Bus，三步渐进式）

---

> **最后更新**：2026-06-07
