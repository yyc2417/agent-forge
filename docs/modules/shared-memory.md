# Shared Memory 模块文档

> **状态**：阶段 3已实现 | **最后更新**：2026-06-12

---

## 概述

记忆系统为 Agent 提供跨轮次、跨会话的信息保持能力。采用两层架构：

- **短期记忆（ShortTermMemory）**：滑动窗口 + LLM 摘要压缩，管理多轮对话上下文
- **长期记忆（LongTermMemory）**：JSON 文件持久化的 key-value 存储，管理跨会话知识
- **会话管理（SessionManager）**：会话生命周期管理（创建/保存/加载/列出）

---

## ShortTermMemory

### 核心机制

1. **滑动窗口**：保留最近 `max_messages`（默认 20）条消息
2. **摘要压缩**：超过窗口时，取前半部分消息用 LLM 生成 ~200 字摘要
3. **降级策略**：LLM 为 None 时退化为简单截断（不摘要）

### API

```python
from agent_forge.memory import ShortTermMemory

memory = ShortTermMemory(max_messages=20, llm=None)
memory.add(message)           # 添加消息（超窗口自动压缩）
memory.get_messages() -> list # 获取窗口内消息
memory.get_summary() -> str   # 获取累积摘要
memory.save(path)             # 序列化到 JSON
memory.load(path)             # 从 JSON 恢复
memory.clear()                # 清空
```

### 集成到 BaseAgent

```python
agent = BaseAgent(
    name="assistant",
    memory=ShortTermMemory(max_messages=15),
)
# run() 自动注入摘要 + 历史消息，运行后自动存入记忆
```

---

## LongTermMemory

### 核心机制

- JSON 文件持久化（`.agentforge/memory/long_term.json`）
- 关键词搜索（遍历 key/value/tags 子串匹配）
- 通过闭包工厂 `create_memory_tools()` 创建绑定的 Agent 工具

### API

```python
from agent_forge.memory import LongTermMemory, create_memory_tools

ltm = LongTermMemory(file_path=".agentforge/memory/long_term.json")
ltm.store(key, value, tags)    # 存储记忆
ltm.recall(key) -> str         # 精确检索
ltm.search(query) -> str       # 关键词搜索
ltm.list_memories() -> str     # 列出所有记忆
ltm.delete(key) -> str         # 删除记忆

# 创建 Agent 工具
tools = create_memory_tools(ltm)  # [store_memory, recall_memory, list_memories]
agent = BaseAgent(name="assistant", tools=tools)
```

---

## SessionManager

### 存储结构

```
.agentforge/sessions/
├── index.json                     # 会话索引
├── session_20260612_143022.json   # 会话数据
└── session_20260612_150100.json
```

### API

```python
from agent_forge.memory import SessionManager

mgr = SessionManager(base_dir=".agentforge/sessions")
sid = mgr.create_session("coder")
mgr.save_session(sid, memory)
mgr.load_session(sid, memory) -> bool
mgr.list_sessions() -> list[dict]
mgr.get_latest_session("coder") -> str | None
mgr.delete_session(sid) -> bool
```

---

## 代码位置

- `agent_forge/memory/short_term.py` — ShortTermMemory
- `agent_forge/memory/long_term.py` — LongTermMemory + create_memory_tools
- `agent_forge/memory/session.py` — SessionManager
- `demos/phase3_agent_demo.py` — Step 1 演示

---

> **最后更新**：2026-06-12
