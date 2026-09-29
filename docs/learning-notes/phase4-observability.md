# 阶段 4学习笔记：可观测性与 Dashboard 设计

> **日期**：2026-06-16
> **学习范围**：BusCollector 数据采集、Streamlit Dashboard、threading 并发模型

---

## 可观测性三支柱

在软件工程中，可观测性有三个支柱：日志（Logs）、指标（Metrics）、链路追踪（Traces）。AgentForge 在阶段 4前已经具备了这三个能力的基础，但分散在不同模块中：

| 支柱 | AgentForge 实现 | 阶段 4前的问题 |
|------|----------------|---------------|
| **日志** | LoggingInterceptor 实时打印 | 只有文本流，无法过滤和统计 |
| **指标** | CostTracker 的 token 统计 | 只在 Demo 结束时打印，无法实时查看 |
| **链路追踪** | Bus 消息历史 + event_type | 存储在内存中，没有可视化界面 |

Dashboard 的价值在于：将这三根支柱统一到一个界面中，从"能看到"升级为"能分析"。

---

## BusCollector 的设计取舍

### 为什么用"拉取"而不是"推送"？

Streamlit 的运行模型是"每次交互都重新执行整个脚本"。这意味着：
- 不能在 Streamlit 脚本中启动长运行的监听器
- 数据必须在多次 rerun 之间持久存在（通过 session_state）

因此 BusCollector 采用"拉取"模式：
1. 回调函数 `_on_message` 被动接收消息并存入内部列表
2. Streamlit 定期调用 `get_messages()` / `get_agent_states()` 拉取最新数据
3. 通过 `st.rerun()` + `time.sleep(2)` 实现定时刷新

### 线程安全的代价

Agent 在后台线程运行（IO 密集型 LLM 调用），BusCollector 的回调在该线程中被触发，Streamlit 在主线程读取数据。这要求：

- 所有公共方法在 `threading.Lock` 内执行
- 返回数据使用 `copy.deepcopy`，防止读取时数据被并发修改
- 深拷贝有性能开销，但在当前规模（几十条消息）下可以忽略

### 状态推导而非状态存储

BusCollector 不存储"Agent 当前状态"这个字段——它根据事件类型推导：

```
agent.started      → running
agent.thinking     → thinking
agent.tool_request → calling_tool
agent.completed    → idle
```

这种设计的优势：
- 不需要 Agent 代码显式上报状态（减少耦合）
- 事件序列本身就是完整的状态变化历史
- 新增事件类型只需更新映射表，不需要改 Agent 代码

---

## Streamlit + threading 的心得

### Streamlit 的"陷阱"

Streamlit 最大的特点是**每次交互都重新执行整个脚本**。这意味着：

1. 顶层代码会重复执行——所以 `st.session_state` 的初始化必须用 `if not in` 守卫
2. 不能用 `while True` 循环——会阻塞 Streamlit 的交互模型
3. `st.rerun()` 是"重新运行脚本"，不是"刷新页面"——所有变量都会重新初始化

### threading 在 IO 密集场景下够用

Python 的 GIL（全局解释器锁）让多线程在 CPU 密集型任务中无效。但 LLM 调用是网络 IO：

```
主线程（Streamlit）     后台线程（Agent）
    │                       │
    │ st.rerun()            │ LLM API 请求（释放 GIL）
    │ 读取 collector        │ 等待响应（GIL 空闲）
    │ 展示数据              │ 收到响应，解析结果
    │                       │ 工具调用（subprocess，释放 GIL）
    │                       │ ...
```

GIL 在 IO 等待时释放，所以 threading 在这个场景下是有效的。

### session_state 的线程边界

`st.session_state` 不是线程安全的。我们的策略是：

- 后台线程只写 `st.session_state.task_result` 和 `task_error`（两个简单的字符串赋值）
- 所有复杂数据通过 `BusCollector` 自己的 Lock 保护
- 主线程通过 `collector.get_*()` 读取数据（已加锁）

**校准（2026-09-29）**：上面的"后台线程直接写字符串赋值"方案后来被证明不可行——Streamlit 的
`session_state` 绑定脚本会话，后台线程写入会抛 `NoSessionContext` 或静默丢数据。修复（commit
`39188f7` / `4a3f81e`）：后台线程只写线程安全的 `_TaskRunResult` 结果信箱，主脚本每轮 rerun
从信箱取回并写回 session_state（发生在主线程内）；HITL 审批同样走 `ApprovalBroker` 信箱。

---

## 思考题回答

### Dashboard 和 LoggingInterceptor 的关系是什么？

它们是互补的：
- **LoggingInterceptor** 是"实时流"——在消息经过时立即打印，适合开发调试
- **BusCollector** 是"结构化存储"——将消息分类存储，支持事后查询和统计
- Dashboard 通过 BusCollector 获取数据，LoggingInterceptor 继续在终端打印日志

实际使用中，两者同时开启：终端看实时日志，浏览器看结构化 Dashboard。

### 什么时候需要真正的 WebSocket 推送？

当满足以下条件时，应该升级到 WebSocket：
1. 需要远程访问（Dashboard 和 Agent 不在同一台机器）
2. 需要多个客户端同时观察（如多人协同观看）
3. 需要亚秒级的实时性（当前 2 秒轮询不够快）

当前阶段不需要——演示时单机运行，2 秒轮询足够。

---

## 本周收获

1. **可观测性是"免费"的**——通过 Bus + LoggingInterceptor + BusCollector，不改 Agent 代码就能获得完整的事件流
2. **threading 在 IO 密集场景下够用**——LLM 调用是网络 IO，GIL 不是瓶颈
3. **Streamlit 的限制也是优势**——"每次重跑"的模型迫使你思考状态管理，代码反而更清晰
4. **直连 Bus vs API 层的取舍**——MVP 阶段直连更简单，API 层可以后面加，BusCollector 的代码不需要改

---

> **最后更新**：2026-06-16（2026-09-29 校准线程边界注记）
