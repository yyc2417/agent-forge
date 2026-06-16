# Tool System 模块文档

> **状态**：阶段 3已实现 | **最后更新**：2026-06-12

---

## 概述

工具系统为 Agent 提供操作外部世界的能力。阶段 3新增：

- **ToolRegistry**：动态注册 + 三级权限模型
- **grep_search**：文本搜索工具
- **生命周期 Hooks**：Agent 执行过程的 5 个事件钩子
- **Token 成本追踪**：按 Agent 维度汇总 LLM 调用成本

---

## ToolRegistry

### 权限模型

| 级别 | 枚举值 | 包含权限 | 典型工具 |
|------|--------|----------|----------|
| READ | `"read"` | 只读 | read_file, grep_search |
| WRITE | `"write"` | 只读 + 写入 | write_file |
| EXECUTE | `"execute"` | 只读 + 写入 + 执行 | run_shell |

`get_tools(max_permission)` 返回该级别及以下的工具。

### API

```python
from agent_forge.tools import ToolRegistry, ToolPermission, read_file, write_file, run_shell

registry = ToolRegistry()
registry.register(read_file, ToolPermission.READ)
registry.register(write_file, ToolPermission.WRITE)
registry.register(run_shell, ToolPermission.EXECUTE)

read_tools = registry.get_tools(ToolPermission.READ)    # [read_file]
write_tools = registry.get_tools(ToolPermission.WRITE)   # [read_file, write_file]
all_tools = registry.get_all_tools()                     # [read_file, write_file, run_shell]
```

### 向后兼容

`ALL_TOOLS` 保持不变，从默认 Registry 导出：
```python
from agent_forge.tools import ALL_TOOLS  # 仍然可用
```

---

## grep_search

```python
from agent_forge.tools import grep_search

# 搜索 Python 文件中的 "class" 定义
result = grep_search.invoke({"pattern": "class.*Agent", "path": ".", "file_pattern": "*.py"})
```

自动跳过 `.git`、`__pycache__`、`.venv` 等目录，最多返回 50 条结果。

---

## 生命周期 Hooks

### 5 个标准事件

| 事件 | 触发时机 | kwargs |
|------|----------|--------|
| `pre_llm_call` | LLM 调用前 | agent, messages |
| `post_llm_call` | LLM 调用后 | agent, response |
| `pre_tool_use` | 工具执行前 | agent, tool_name, tool_args |
| `post_tool_use` | 工具执行后 | agent, tool_name, output |
| `on_message_received` | 收到 Bus 消息 | agent, message |

### API

```python
from agent_forge.hooks import HookManager

hooks = HookManager()
hooks.register("pre_llm_call", lambda **kw: print(f"[{kw['agent']}] 思考中..."))
hooks.register("post_tool_use", lambda **kw: print(f"工具 {kw['tool_name']} 完成"))

agent = BaseAgent(name="coder", hooks=hooks, ...)
```

---

## Token 成本追踪

### API

```python
from agent_forge.cost import CostTracker

tracker = CostTracker(cost_per_1k_prompt=0.001, cost_per_1k_completion=0.002)
agent = BaseAgent(name="coder", cost_tracker=tracker, ...)
agent.run("写一个排序函数")
tracker.print_report()
```

### 报告输出示例

```
══════════════════════════════════════════════════════
  Token 成本报告
══════════════════════════════════════════════════════
  Agent          Calls   Prompt    Compl    Total     Cost
  ────────────── ───── ──────── ──────── ──────── ────────
  coder              3    3,200    1,500    4,700   ¥0.006
  reviewer           1    1,800      600    2,400   ¥0.003
  ────────────── ───── ──────── ──────── ──────── ────────
  合计               4    5,000    2,100    7,100   ¥0.009
══════════════════════════════════════════════════════
```

---

## 代码位置

- `agent_forge/tools/registry.py` — ToolRegistry + ToolPermission
- `agent_forge/tools/search_tools.py` — grep_search
- `agent_forge/hooks.py` — HookManager
- `agent_forge/cost.py` — CostTracker + TokenRecord
- `demos/phase3_agent_demo.py` — Step 2 演示

---

> **最后更新**：2026-06-12
