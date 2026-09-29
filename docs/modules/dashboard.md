# Dashboard 模块设计文档

> **状态**：✅ 阶段 4已完成
> **代码位置**：`agent_forge/dashboard/`
> **最后更新**：2026-09-29（校准 get_messages/get_events 语义，补 9 月增补的 HITL 审批门与结果信箱）

---

## 模块定位

Dashboard 是 AgentForge 的可观测性窗口。它将 Message Bus 中的事件流转化为可视化界面，让用户能实时观察 Agent 的决策过程、状态变化和成本消耗。

**核心价值**：
> "Dashboard 不只是展示——它是系统的可观测性窗口。每一轮 agent 决策、每条消息、每次工具调用都有全链路追踪。这让我能定量分析：哪个 agent 是瓶颈？哪类任务失败率高？token 消耗大头在哪？"

---

## 架构设计

### 两层架构

```
MessageBus ("*" 通配符)
    │
    ▼
BusCollector（数据采集层，线程安全）
    │
    ├── get_messages()      → 全部消息（含 EVENT）
    ├── get_events()        → 事件时间线（仅 EVENT intent）
    ├── get_agent_states()  → Tab 3: Agent 状态面板
    └── get_stats()         → Tab 1/4: 统计 + 成本
    │
    ▼
Streamlit App（展示层）
    ├── Tab 1: 任务总览（输入 + 执行 + 结果）
    ├── Tab 2: 消息流时间线（过滤 + 详情）
    ├── Tab 3: Agent 状态面板（卡片 + 状态灯）
    └── Tab 4: 成本分析（表格 + 指标）
```

### 为什么直连 Bus 而不走 API 层？

- **简单**：不需要 FastAPI/WebSocket 中间层，减少部署复杂度
- **够用**：演示场景下，单机直连完全满足需求
- **可升级**：如果未来需要远程访问，可以加一层 API，BusCollector 的代码不需要改

---

## BusCollector 设计

### 核心职责

订阅 MessageBus 的 `"*"` 通配符事件，被动接收所有消息并分类存储。

### 线程安全

Agent 在后台线程运行，BusCollector 的回调在该线程中被触发。Streamlit 在主线程中读取数据。因此：

- 所有读写操作在 `threading.Lock` 内执行
- 返回数据的深拷贝（`copy.deepcopy`），防止 Streamlit 读取时数据被并发修改

### Agent 状态推导

BusCollector 根据事件类型自动推导 Agent 当前状态：

| event_type | 推导状态 |
|------------|---------|
| `agent.started` | running |
| `agent.thinking` | thinking |
| `agent.tool_request` | calling_tool（记录工具名） |
| `agent.tool_result` | thinking |
| `agent.completed` | idle |
| `orchestrator.*` | 对应 orchestrator 状态 |

### 与 LoggingInterceptor 的区别

| 维度 | LoggingInterceptor | BusCollector |
|------|-------------------|--------------|
| 输出方式 | 实时打印到终端 | 结构化存储到内存 |
| 数据格式 | 纯文本 | dict（可序列化） |
| 查询能力 | 无 | 按 role/intent 过滤 + 统计 |
| 用途 | 开发调试 | Dashboard 数据源 |
| 线程安全 | 无状态，天然安全 | Lock + deepcopy |

---

## Streamlit App 设计

### session_state 管理

```python
st.session_state.collector      # BusCollector 实例
st.session_state.cost_tracker   # CostTracker 实例
st.session_state.thread         # threading.Thread 实例
st.session_state.task_result    # 任务最终结果
st.session_state.task_error     # 任务错误信息
st.session_state.auto_refresh   # 是否自动刷新
st.session_state.approval_broker # HITL 审批信箱（ApprovalBroker，超时 300s 自动拒绝）
```

### 自动刷新机制

```python
# 任务运行中，每 2 秒触发 rerun
if st.session_state.auto_refresh and thread.is_alive():
    time.sleep(2)
    st.rerun()
```

### 任务执行流程

```
用户输入任务 → 点击 [执行]
    ↓
创建后台线程 → target=_run_task(task)
    ↓
_run_task 内部：
    1. 创建 Bus + LoggingInterceptor
    2. collector.attach(bus)
    3. 创建 Orchestrator + Specialists（run_shell 经 ApprovalBroker 审批）
    4. orchestrator.run(task)
    5. 结果写入 _TaskRunResult 信箱（线程安全队列；
       后台线程不直接写 session_state——Streamlit 禁止跨线程访问）
    ↓
主线程：st.rerun() 每 2 秒刷新，每轮从信箱取回结果写回 session_state
    ↓
线程结束：展示最终结果
```

### HITL 审批门（2026-09-12 增补）

`run_shell` 调用前必须经人工批准（详见 [interview 修复故事](../planning/interview-stories.md) 与 commit `4a3f81e`）：

- `ApprovalBroker.request(tool_name, tool_args)` 阻塞后台线程，主脚本每轮 rerun 渲染审批卡片
- 批准/拒绝结果经线程安全信箱返回；**超时 300 秒自动拒绝**（fail-safe）

---

## 最小可运行示例

```python
from agent_forge.bus import MessageBus, LoggingInterceptor
from agent_forge.dashboard import BusCollector

bus = MessageBus()
bus.add_interceptor(LoggingInterceptor())

collector = BusCollector()
collector.attach(bus)

# Agent 运行后...
events = collector.get_events()
states = collector.get_agent_states()
stats = collector.get_stats()

print(f"事件数: {stats['total_events']}")
print(f"Agent 数: {stats['agent_count']}")
print(f"工具调用: {stats['tool_calls']}")
# stats 还包含 total_messages / request_count / response_count / duration_seconds
```

---

## 后续扩展方向

- **FastAPI + WebSocket**：将 BusCollector 数据通过 WebSocket 推送，支持远程访问
- **消息持久化**：将 Bus 历史消息写入 SQLite，支持离线回放
- **多会话管理**：在 Dashboard 中切换不同的会话/任务
- **图表可视化**：用 Streamlit 的 st.bar_chart / st.line_chart 展示 token 消耗趋势

---

> 最后更新：2026-09-29
