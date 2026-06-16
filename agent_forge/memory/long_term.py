"""长期记忆 —— JSON 文件持久化的 key-value 存储

提供跨 Agent、跨会话的持久化知识存储。
Agent 通过记忆工具（store_memory / recall_memory / list_memories）显式操作。

与短期记忆的区别：
    - 短期记忆：自动管理，Agent 运行过程中自动存取，用于多轮对话上下文
    - 长期记忆：手动管理，Agent 通过工具显式 store/recall，用于跨会话知识

为什么不用向量数据库？
    - 当前阶段不需要语义检索（那是 RAG 的范畴，Phase 2 再加）
    - JSON key-value 足够满足"Agent A 存一个结果，Agent B 取出来用"
    - 保持零外部依赖原则，不引入 chromadb/faiss 等

为什么用闭包工厂函数 create_memory_tools()？
    - 每个 Agent 可以有独立的 LongTermMemory 实例（或共享同一个）
    - 闭包保证工具与实例的 1:1 绑定，没有全局状态污染
    - @tool 装饰器在函数定义时提取 docstring 生成 JSON Schema

使用方式：
    # 直接操作
    memory = LongTermMemory()
    memory.store("project_lang", "Python 3.11")
    result = memory.recall("project_lang")

    # 通过工具（Agent 使用）
    tools = create_memory_tools(memory)
    agent = BaseAgent(name="assistant", tools=tools, ...)
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.tools import tool as tool_decorator

from agent_forge.utils import safe_print

# ─── 记忆条目 ──────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """长期记忆条目。

    Attributes:
        key: 记忆的唯一标识（如 "project_language"）。
        value: 记忆的内容文本。
        tags: 标签列表，用于分类和过滤。
        created_at: 创建时间戳。
        access_count: 被检索的次数。
        last_accessed: 最近一次被检索的时间戳。
    """
    key: str
    value: str
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = 0.0


# ─── 长期记忆 ──────────────────────────────────────────────

class LongTermMemory:
    """长期记忆 —— JSON 文件持久化的 key-value 存储。

    存储位置默认为 `.agentforge/memory/long_term.json`。
    每次 store/delete 操作后自动持久化到文件。
    """

    def __init__(self, file_path: str = ".agentforge/memory/long_term.json") -> None:
        """初始化长期记忆。

        Args:
            file_path: JSON 持久化文件路径。
        """
        self._file_path = Path(file_path)
        self._store: dict[str, MemoryEntry] = {}
        self._load()

    # ─── 核心操作 ──────────────────────────────────────────

    def store(self, key: str, value: str, tags: str = "") -> str:
        """存储一条记忆。

        如果 key 已存在，则更新 value 和 tags。

        Args:
            key: 记忆的唯一标识。
            value: 记忆的内容文本。
            tags: 逗号分隔的标签字符串（如 "config,project"）。

        Returns:
            操作结果描述。
        """
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        if key in self._store:
            self._store[key].value = value
            self._store[key].tags = tag_list
            self._persist()
            return f"已更新记忆 '{key}'"
        else:
            self._store[key] = MemoryEntry(
                key=key, value=value, tags=tag_list
            )
            self._persist()
            return f"已存储记忆 '{key}'"

    def recall(self, key: str) -> str:
        """按 key 精确检索记忆。

        Args:
            key: 记忆的标识。

        Returns:
            记忆内容，或 "未找到" 提示。
        """
        entry = self._store.get(key)
        if entry:
            entry.access_count += 1
            entry.last_accessed = time.time()
            self._persist()
            return entry.value
        return f"未找到 key 为 '{key}' 的记忆"

    def search(self, query: str) -> str:
        """按关键词搜索记忆（遍历 key/value/tags）。

        简单的子串匹配，不引入向量检索。
        搜索范围：key、value、tags 中任意一个包含 query 的条目。

        Args:
            query: 搜索关键词。

        Returns:
            格式化的搜索结果，或 "无匹配" 提示。
        """
        query_lower = query.lower()
        results = []

        for key, entry in self._store.items():
            # 检查 key / value / tags
            if (
                query_lower in key.lower()
                or query_lower in entry.value.lower()
                or any(query_lower in tag.lower() for tag in entry.tags)
            ):
                entry.access_count += 1
                entry.last_accessed = time.time()
                # 截断过长的 value
                preview = entry.value[:200]
                if len(entry.value) > 200:
                    preview += "..."
                results.append(f"- {key}: {preview}")

        if not results:
            return f"未找到包含 '{query}' 的记忆"

        self._persist()
        return f"找到 {len(results)} 条匹配：\n" + "\n".join(results)

    def list_memories(self) -> str:
        """列出所有记忆的 key 和摘要。

        Returns:
            格式化的记忆列表，或 "记忆库为空" 提示。
        """
        if not self._store:
            return "记忆库为空"

        lines = [f"共 {len(self._store)} 条记忆："]
        for key, entry in self._store.items():
            preview = entry.value[:80].replace("\n", " ")
            if len(entry.value) > 80:
                preview += "..."
            tags_str = f" [{', '.join(entry.tags)}]" if entry.tags else ""
            lines.append(f"- {key}{tags_str}: {preview}")

        return "\n".join(lines)

    def delete(self, key: str) -> str:
        """删除一条记忆。

        Args:
            key: 记忆的标识。

        Returns:
            操作结果描述。
        """
        if key in self._store:
            del self._store[key]
            self._persist()
            return f"已删除记忆 '{key}'"
        return f"未找到 key 为 '{key}' 的记忆"

    # ─── 持久化 ───────────────────────────────────────────

    def _persist(self) -> None:
        """将当前存储持久化到 JSON 文件。"""
        data = {
            key: {
                "key": entry.key,
                "value": entry.value,
                "tags": entry.tags,
                "created_at": entry.created_at,
                "access_count": entry.access_count,
                "last_accessed": entry.last_accessed,
            }
            for key, entry in self._store.items()
        }
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        """从 JSON 文件加载存储。"""
        if not self._file_path.exists():
            return
        try:
            data: dict[str, Any] = json.loads(
                self._file_path.read_text(encoding="utf-8")
            )
            for key, entry_data in data.items():
                self._store[key] = MemoryEntry(
                    key=entry_data.get("key", key),
                    value=entry_data.get("value", ""),
                    tags=entry_data.get("tags", []),
                    created_at=entry_data.get("created_at", 0.0),
                    access_count=entry_data.get("access_count", 0),
                    last_accessed=entry_data.get("last_accessed", 0.0),
                )
        except (json.JSONDecodeError, KeyError) as e:
            safe_print(f"  [LongTermMemory] 加载失败: {e}，从空存储开始")

    def clear(self) -> None:
        """清空所有记忆。"""
        self._store.clear()
        self._persist()

    def __repr__(self) -> str:
        return f"LongTermMemory(entries={len(self._store)}, file={self._file_path})"


# ─── 记忆工具工厂 ──────────────────────────────────────────

def create_memory_tools(memory: LongTermMemory) -> list:
    """为 LongTermMemory 实例创建绑定的工具列表。

    使用闭包将 memory 实例绑定到每个工具函数中，
    Agent 调用工具时无需知道 memory 的存在。

    Args:
        memory: LongTermMemory 实例。

    Returns:
        [store_memory, recall_memory, list_memories] 三个 @tool 函数。
    """

    @tool_decorator
    def store_memory(key: str, value: str, tags: str = "") -> str:
        """存储一条记忆到长期记忆库。其他 Agent 可以通过 recall_memory 检索。

        Args:
            key: 记忆的唯一标识（如 "project_language"）。
            value: 记忆的内容文本。
            tags: 逗号分隔的标签（如 "config,project"），用于分类。
        """
        return memory.store(key, value, tags)

    @tool_decorator
    def recall_memory(query: str) -> str:
        """从长期记忆库中检索记忆。支持精确 key 匹配和关键词搜索。

        Args:
            query: 记忆的 key 或搜索关键词。
        """
        # 先尝试精确匹配
        result = memory.recall(query)
        if "未找到" not in result:
            return result
        # 精确匹配失败，尝试关键词搜索
        return memory.search(query)

    @tool_decorator
    def list_memories() -> str:
        """列出长期记忆库中所有记忆的 key 和摘要。"""
        return memory.list_memories()

    return [store_memory, recall_memory, list_memories]
