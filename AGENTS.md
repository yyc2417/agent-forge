# AGENTS.md — 操作指南

## 项目事实

- **语言**: Python 3.11+（CI 矩阵 3.11 / 3.12）
- **编排**: LangGraph StateGraph（ReAct + Plan-and-Execute）
- **LLM**: DeepSeek V4-Flash，`ChatOpenAI` 兼容适配（`agent_forge/llm/providers.py`）
- **依赖**: `pyproject.toml` + uv；可选组 `[dev]` `[dashboard]` `[mcp]`

## 命令速查

```bash
uv pip install -e ".[dev]"                                        # 安装（含开发依赖）
uv run ruff check agent_forge/ tests/ benchmark/ demos/           # Lint（line-length=120）
uv run ruff check --fix agent_forge/ tests/ benchmark/ demos/     # Lint 自动修复
uv run pytest tests/ -m "not slow" -v --tb=short                  # 快速测试（跳过 LLM，~8s）
uv run pytest tests/ -v                                           # 全量测试（需 .env）
python -m build                                                   # 构建
```

> 无 mypy 配置。

## 核心模式

### Agent 基类（模板方法）

`BaseAgent` 封装 ReAct 循环：`agent_node → should_continue → tool_node → 循环`。

```python
agent = BaseAgent(name="coder", role="工程师", tools=[read_file])
result = agent.run("写一个排序函数")

class MyAgent(BaseAgent):
    def get_system_prompt(self) -> str: ...
    def _build_graph(self): ...               # 添加审批/反思节点
```

**兜底四件套**：轮次上限（`max_turns`，默认 5）；连续工具失败 ≥3 次熔断；相同 `(tool, args)` 连续 3 次拦截（单轮累计 2 次强制终止）；异常终止时输出结构化兜底文案。

### 消息总线（Pub/Sub）

```python
bus.subscribe("intent.request", handler)   # 按意图订阅
bus.subscribe("role.coder", handler)       # 按发送方订阅
bus.subscribe("*", handler)                # 全量监听
```

路由键：`intent.{type}` / `role.{sender}` / `*`，无收件人字段（不支持点对点定向）。

### 工具注册（三级权限 + 审批门）

```python
from agent_forge.tools.registry import ToolRegistry, ToolPermission
registry = ToolRegistry()
registry.register(read_file, ToolPermission.READ)
registry.register(run_shell, ToolPermission.EXECUTE, requires_approval=True)
tools = registry.bind_tools(ToolPermission.WRITE, approval_callback=my_callback)
```

**审批门**：`requires_approval=True` 且无回调 → 默认全拒（fail-safe）。

## 风险控制
### Shell 安全（四层防线）

| 层 | 机制 | 位置 |
|----|--------|------|
| 1 | 命令黑名单（子串+正则） | `shell_tools.py` |
| 2 | 沙箱 cwd（`threading.local`） | `sandbox.py` |
| 3 | 超时 30s | `subprocess.run` |
| 4 | 输出截断 10k 字符 | `MAX_OUTPUT_CHARS` |

**残余风险**：`python -c "import shutil; ..."` 可绕过黑名单，生产须 Docker 隔离（ADR-004）。

### 沙箱与约定

- 路径锚定 `get_sandbox_root()`（默认 `Path.cwd()`），`..` 逃逸拒绝
- `.env*` 受保护，Agent 不可读写（防 API Key 泄漏）
- 工具用 `@tool` 装饰器，权限由 `ToolRegistry` 管理
- Bus handler **禁止**调用 `self.run()`（会递归）
- `benchmark/tasks/` 豁免 E501
