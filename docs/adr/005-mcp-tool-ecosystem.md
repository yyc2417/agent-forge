# ADR-005: MCP 工具生态接入（客户端侧）

> 状态：已采纳
> 日期：2026-09-12

## 背景

AgentForge 的工具系统目前只有四个内置工具（read_file / write_file /
run_shell / grep_search）。MCP（Model Context Protocol）已成为 Agent
工具生态的事实标准——文件系统、GitHub、浏览器、数据库等能力都有
现成的 MCP server。让 AgentForge 的 Agent 能消费 MCP 工具，
工具边界从"内置四个"扩展为"整个 MCP 生态"。

## 备选方案

### 方案 A：客户端侧接入（消费 MCP 工具）✅

通过 langchain-mcp-adapters 连接外部 MCP server，
把工具注册进 ToolRegistry。

**决策：选。** 理由：
1. 生态杠杆最大：一个集成点换来整个 MCP 生态的工具
2. 与现有权限模型无缝衔接：工具进 ToolRegistry，
   经 bind_tools 按权限过滤，天然复用阶段 1 的审批门
3. 实现成本低：桥接层约 200 行

### 方案 B：服务端侧（把 AgentForge 暴露为 MCP server）❌

**决策：不选，原因**——AgentForge 的核心价值是"多 Agent 编排"，
把它包装成单工具 server 属于本末倒置；且现有消费场景（本地 demo、
benchmark）不需要跨进程暴露。未来有需求再加。

### 方案 C：绕过 ToolRegistry 直连 MCP ❌

**决策：不选，原因**——MCP 工具是第三方代码，更需要权限门与
审批；绕过注册表会让"权限模型孤岛"问题复发。

## 关键决策

### 1. 安全默认：EXECUTE 权限 + 审批门默认开启

MCP 工具是第三方代码，且工具描述可能夹带提示注入
（tool poisoning）。因此：
- 注册时默认 `permission=EXECUTE`（按最高风险等级对待）
- 默认 `requires_approval=True`，配合 `registry.bind_tools`
  的审批回调实现 Human-in-the-Loop
- 工具描述截断到 500 字符，防止超长描述膨胀上下文或藏匿注入文本

### 2. 同步框架与异步 SDK 的桥接：常驻后台事件循环

MCP SDK 是 asyncio 优先的，AgentForge 全同步。不用每次调用
`asyncio.run()`（会反复重建 MCP 会话，慢且易碎），而是用 daemon
线程跑常驻事件循环，工具调用经 `run_coroutine_threadsafe` 提交，
会话在 loop 生命周期内复用。同步侧带超时（默认 120 秒），
异步调用不会无限阻塞框架。

### 3. 版本兼容：适配 adapters 0.0.x / 0.1.x 两种 API 形态

- 0.1.x：`get_tools()` 是 async context manager，
  工具在每次调用时自建会话（stdio = 每次调用拉起 server 子进程）
- 0.0.x：`get_tools()` 是普通协程，会话持久在 client 内

检测方式：调用后判断返回对象是否为协程（不能用 `hasattr(__aenter__)`
——0.1.0 保留了抛 NotImplementedError 的 `__aenter__`）。

### 4. 可选依赖，不拖累核心

`mcp` 相关包放 `[project.optional-dependencies].mcp`，
核心库 import 路径不触碰它；未安装时报错带安装指引。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 第三方工具执行破坏性操作 | 默认审批门 + EXECUTE 权限按最高等级对待 |
| 工具描述注入 | 描述截断；后续可加描述来源标注 |
| stdio 传输每次调用拉起子进程（0.1.x 行为） | demo 可接受；生产建议 HTTP 传输长连接 |
| 挂起的 MCP 调用阻塞框架 | 同步侧调用超时 120 秒 |

## 未来方向

- Bus REQUEST 点对点路由（配合 MCP 的 progress/resource 通知）
- 工具描述来源标注与更严格的注入过滤
- benchmark 增加 MCP 类别任务
