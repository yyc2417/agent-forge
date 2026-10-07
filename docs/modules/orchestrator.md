# Orchestrator 模块文档

> **状态**：阶段 2已实现 | **最后更新**：2026-10-07

---

## 概述

Orchestrator 是 AgentForge 的多 Agent 编排器，负责：

1. **任务拆解**：用 LLM 将用户任务拆解为子任务列表
2. **Agent 路由**：将子任务分发给对应的 Specialist Agent
3. **条件回退**：审查不通过时自动回退重新执行
4. **结果汇总**：聚合所有 Specialist 的产出为最终报告

Orchestrator 继承 BaseAgent，覆盖 `_build_graph()` 构建编排工作流图（而非 ReAct 循环图）。这体现了模板方法模式的价值——同一个基类，两种图结构。

---

## 架构

```
Orchestrator (继承 BaseAgent)
    │
    ├── _decompose_node   ← LLM 拆解任务为 SubTask 列表
    ├── _execute_node     ← 路由到 Specialist 执行
    ├── _review_node      ← Reviewer 审查 + 条件回退
    └── _aggregate_node   ← 汇总所有产出
```

### StateGraph 工作流

```
decompose → execute → [all_done?] → review → [passed?]
              ↑         │ yes        │         │ yes
              └─────────┘            │         ↓
              (retry, not passed) ←──┘     aggregate → END
```

### OrchestratorState

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | `list` | LLM 推理历史（add_messages reducer） |
| `task` | `str` | 用户原始任务 |
| `plan` | `list` | SubTask 列表（唯一事实源，每条携带完整产出） |
| `current_step` | `int` | 当前执行到第几个子任务 |
| `review_result` | `str` | 审查门的审查意见文本 |
| `review_passed` | `bool` | 审查是否通过 |
| `final_output` | `str` | 最终汇总报告 |
| `retry_count` | `int` | 回退重试计数 |

---

## Specialist Agents

| Agent | 角色 | 工具集 | 说明 |
|-------|------|--------|------|
| `CoderAgent` | 编码专家 | read_file, grep_search, write_file, run_shell | 负责代码实现 |
| `ReviewerAgent` | 审查专家 | read_file, grep_search | 审查代码，输出【通过】/【不通过】 |

Specialist 继承 BaseAgent，只定制 `name`、`role`、`tools` 和 `get_system_prompt()`。

> **工具对等**（2026-10-07，ADR-006）：硬编码工具列表与 registry 路径
> （`bind_tools(max_permission)` 对默认注册表的过滤结果）保持一致——
> 此前 Coder/Reviewer 硬编码路径缺 grep_search，导致 benchmark 单/多
> 模式工具不对等。

---

## 使用方式

### 基本用法

```python
from agent_forge.agents import CoderAgent, ReviewerAgent, Orchestrator
from agent_forge.bus import MessageBus, LoggingInterceptor

bus = MessageBus()
bus.add_interceptor(LoggingInterceptor())

coder = CoderAgent(bus=bus)
reviewer = ReviewerAgent(bus=bus)

orchestrator = Orchestrator(
    specialists={"coder": coder, "reviewer": reviewer},
    bus=bus,
    max_retries=2,
)

result = orchestrator.run("帮我写一个排序函数")
print(result)
```

### 自定义 Specialist

```python
from agent_forge.agents import BaseAgent

class TesterAgent(BaseAgent):
    def __init__(self, bus=None, llm=None):
        super().__init__(
            name="tester",
            role="测试工程师",
            tools=[read_file, run_shell],
            bus=bus, llm=llm,
        )

    def get_system_prompt(self) -> str:
        return "你是测试工程师。请为给定的代码编写测试用例。"

# 加入 Orchestrator
orchestrator = Orchestrator(
    specialists={"coder": coder, "reviewer": reviewer, "tester": tester},
    bus=bus,
)
```

---

## 关键设计决策

详见 `docs/adr/003-orchestrator-design.md`：

1. **继承 BaseAgent 而非组合**：复用 LLM/Bus/init 基础设施
2. **直接调用 + Bus 事件发布**：控制流清晰 + 可观测性
3. **LLM 拆解 + fallback**：三层防护确保拆解不会失败
4. **双条件审查判定**：`"通过" in r and "不通过" not in r` 减少误判
5. **审查节点职责分离**：`_review_node` 拆分为 5 个子方法，主方法仅做流程编排

### 审查节点的职责分离

`_review_node` 承担审查流程的编排，具体逻辑委托给 5 个独立子方法：

| 子方法 | 职责 | 可独立测试 |
|--------|------|----------|
| `_should_skip_review` | 前置检查（无产出/无 Reviewer → 跳过） | ✅ |
| `_should_force_pass` | 重试控制（达到上限 → 强制通过） | ✅ |
| `_call_reviewer` | 构建 prompt + 调用 Reviewer + Bus 事件 | ✅ |
| `_parse_review_result` | 双条件判定（通过/不通过） | ✅ |
| `_reset_execution_state` | 重置 plan/current_step/retry_count | ✅ |

---

## 代码位置

- `agent_forge/agents/orchestrator.py` — Orchestrator 实现
- `agent_forge/agents/specialists.py` — CoderAgent + ReviewerAgent
- `agent_forge/agents/base.py` — BaseAgent 基类
- `demos/phase2_agent_demo.py` — 三步渐进式 Demo

---

> **最后更新**：2026-10-07（Specialist 工具表对齐 ADR-006）
