"""工具注册中心 —— 动态注册 + 权限模型

替代当前的 ALL_TOOLS 硬编码列表，提供：
1. 动态注册/注销工具
2. 三级权限模型（READ / WRITE / EXECUTE）
3. 按权限级别过滤获取工具列表

设计理念：
    不同的 Agent 应该有不同的工具权限。例如：
    - Reviewer Agent 只需要 READ 权限（读代码审查）
    - Coder Agent 需要 READ + WRITE 权限（读写文件）
    - 全权限 Agent 还需要 EXECUTE 权限（运行命令）

    权限模型遵循最小权限原则：每个 Agent 只拥有完成任务所需的最小工具集。
    这防止了 Agent 越权操作（如 Reviewer 不应该能修改代码）。

向后兼容：
    ALL_TOOLS 保持不变（仍然是 list），从默认 Registry 导出。
    现有代码 from agent_forge.tools import ALL_TOOLS 完全不受影响。

与 OpenAI Function Calling 的关系：
    LangChain 的 @tool 装饰器已经生成了 JSON Schema。
    ToolRegistry 在此基础上增加权限元数据。
    bind_tools() 仍然接收工具列表，权限检查在 Agent 构建时完成
    （只给 Agent 绑定其权限范围内的工具）。
"""

from enum import Enum


class ToolPermission(str, Enum):
    """工具权限级别。

    三级权限模型，级别递增：
    - READ:    只读操作（read_file, grep_search）
    - WRITE:   写入操作（write_file）
    - EXECUTE: 执行操作（run_shell）

    使用 str + Enum 双继承（与 MessageIntent 保持一致风格）：
    - str: 可 JSON 序列化
    - Enum: 类型安全，IDE 自动补全

    get_tools(max_permission) 返回该级别及以下权限的工具：
    - get_tools(READ)    → 只读工具
    - get_tools(WRITE)   → 只读 + 写入工具
    - get_tools(EXECUTE) → 所有工具
    """
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


# 权限级别的数值映射（用于比较）
_PERMISSION_LEVELS = {
    ToolPermission.READ: 1,
    ToolPermission.WRITE: 2,
    ToolPermission.EXECUTE: 3,
}


class ToolRegistry:
    """工具注册中心 —— 动态注册、发现、权限管理。

    使用方式：
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.register(write_file, ToolPermission.WRITE)
        registry.register(run_shell, ToolPermission.EXECUTE)

        # 获取只读工具
        read_tools = registry.get_tools(ToolPermission.READ)

        # 获取所有工具
        all_tools = registry.get_all_tools()
    """

    def __init__(self) -> None:
        # name -> (tool, permission)
        self._tools: dict[str, tuple] = {}

    def register(self, tool, permission: ToolPermission) -> None:
        """注册一个工具及其权限级别。

        如果工具名已存在，则覆盖。

        Args:
            tool: LangChain @tool 函数。
            permission: 权限级别。
        """
        name = tool.name if hasattr(tool, "name") else str(tool)
        self._tools[name] = (tool, permission)

    def unregister(self, tool_name: str) -> None:
        """注销一个工具。

        Args:
            tool_name: 工具名称。
        """
        self._tools.pop(tool_name, None)

    def get_tools(self, max_permission: ToolPermission) -> list:
        """获取指定权限级别及以下的工具列表。

        例如 get_tools(WRITE) 返回 READ + WRITE 权限的工具。

        Args:
            max_permission: 最大权限级别。

        Returns:
            符合条件的工具列表。
        """
        max_level = _PERMISSION_LEVELS[max_permission]
        return [
            tool
            for tool, perm in self._tools.values()
            if _PERMISSION_LEVELS[perm] <= max_level
        ]

    def get_all_tools(self) -> list:
        """获取所有已注册的工具列表。"""
        return [tool for tool, _ in self._tools.values()]

    def get_permission(self, tool_name: str) -> ToolPermission | None:
        """查询工具的权限级别。

        Args:
            tool_name: 工具名称。

        Returns:
            权限级别，或 None（工具不存在）。
        """
        entry = self._tools.get(tool_name)
        return entry[1] if entry else None

    def has_tool(self, tool_name: str) -> bool:
        """检查工具是否已注册。"""
        return tool_name in self._tools

    def list_tools(self) -> list[dict]:
        """列出所有已注册工具的名称和权限。

        Returns:
            [{"name": str, "permission": str}] 列表。
        """
        return [
            {"name": name, "permission": perm.value}
            for name, (_, perm) in self._tools.items()
        ]

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={len(self._tools)})"
