# 阶段 3学习笔记：记忆系统与工具增强

> **日期**：2026-06-12
> **学习范围**：ShortTermMemory、LongTermMemory、ToolRegistry、Hooks、Token 追踪

---

## 两层记忆的设计取舍

### 为什么分两层？

| 维度 | 短期记忆 | 长期记忆 |
|------|----------|----------|
| 生命周期 | 单次会话 | 跨会话持久化 |
| 管理方式 | 自动（滑动窗口） | 手动（Agent 显式 store/recall） |
| 存储内容 | 对话消息 | 结构化知识（key-value） |
| 检索方式 | 按时间顺序 | 按 key 精确匹配或关键词搜索 |

分开的原因：对话上下文和结构化知识的使用模式完全不同。对话上下文是"自动累积、自动过期"，结构化知识是"显式存储、显式检索"。

### 摘要压缩的 prompt 调优

第一版摘要 prompt 生成的摘要太长（>500 字），加了"不超过200字"的限制后效果好很多。
另一个经验：在 prompt 中加入"当前累积摘要"字段，让 LLM 基于已有摘要做增量更新，而不是每次从头生成。

### LLM 为 None 的降级策略

如果 ShortTermMemory 没有传入 LLM，压缩退化为简单截断（直接丢弃最早的消息）。
这在不关心历史信息保留质量的场景下足够用，且避免了额外的 LLM 调用成本。

---

## 闭包工厂 vs 全局变量

`create_memory_tools(memory)` 使用闭包将 memory 实例绑定到工具函数中。

为什么不用全局变量？
- 全局变量导致所有 Agent 共享同一个 memory 实例，无法隔离
- 闭包保证每个 Agent 可以有独立的 memory（或显式共享同一个）

为什么不用类方法？
- LangChain 的 `@tool` 装饰器要求工具是函数，不是方法
- 闭包是在函数和方法之间的优雅折中

---

## ToolRegistry 的思考

### 权限检查在哪里执行？

当前设计：权限检查在 **Agent 构建时** 执行（只给 Agent 绑定其权限范围内的工具）。
不是运行时检查（不是 tool_node 中检查权限）。

好处：简单、高效，LLM 根本不知道有超出权限的工具存在。
风险：如果动态添加工具，需要重新 bind_tools()。

### grep_search 为什么用纯 Python 实现？

- 不依赖系统 grep 命令（Windows 上没有 grep）
- pathlib.rglob() + re.search() 足够快（对于项目级搜索）
- 自动跳过 .git/__pycache__/.venv 等目录

---

## 生命周期 Hooks 的价值

Hooks 让外部代码能在 Agent 执行过程中"插入"逻辑，而不需要修改 Agent 的核心代码。

最直接的用例：
1. **日志**：pre_llm_call 记录每次 LLM 调用
2. **成本统计**：post_llm_call 采集 token usage
3. **调试**：pre_tool_use 打印工具参数
4. **监控**：post_tool_use 检查工具输出是否异常

### 为什么不用 MessageBus 替代 Hooks？

- MessageBus 是 Agent 间通信（粗粒度）
- Hooks 是 Agent 内部生命周期事件（细粒度）
- 例如"LLM 调用前的消息列表"这种内部状态，不适合发到 Bus 上

---

## Token 追踪的采集点

从 `response.response_metadata.get('token_usage', {})` 提取。

注意：不是所有 LLM Provider 都返回 token_usage。DeepSeek（OpenAI 兼容 API）会返回，但本地模型可能不会。所以采集代码做了防御性检查。

---

## 思考题回答

### Agent A 产生的中间结果，Agent B 怎么高效获取？

当前方案：plan 条目是唯一事实源——`OrchestratorState.plan` 每条携带 `{id, description, agent_type, status, result}`，Orchestrator 执行下一步时把上一步产出拼入该 Agent 的 prompt。
这适合顺序执行的工作流。如果是并行执行，需要更复杂的共享机制（如 SharedMemory 对象）。
（**2026-09 校准**：早期设想的独立 `results` 字段未采用；顺序执行架构见 ADR-003。）

### 什么时候应该让 Agent "忘记"？

- 短期记忆：超过滑动窗口的消息自动被压缩为摘要（信息损失换 token 节省）
- 长期记忆：可通过 recall_memory / list_memories 审视过时信息（**2026-09 校准**：`create_memory_tools` 实际只暴露 store/recall/list 三个工具，delete 未开放给 Agent——防止 Agent 自作主张删除记忆）
- 会话切换：新建会话时，之前的对话上下文不自动带入

---

## 本周收获

1. **两层记忆覆盖两种需求**：对话上下文（自动）+ 结构化知识（手动）
2. **闭包工厂是 LangChain 工具绑定的最佳实践**：避免全局状态，支持多实例
3. **权限检查在构建时而非运行时**：简单高效，LLM 不知道超出权限的工具
4. **Hooks 是观察者模式的实战应用**：Agent 核心逻辑不关心谁在监听

---

> **最后更新**：2026-06-12（2026-09-29 校准状态传递与记忆工具注记）
