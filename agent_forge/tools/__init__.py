"""工具系统模块

提供基础工具和工具注册中心：
    - read_file:    读取文件内容
    - write_file:   写入文件
    - run_shell:    执行 Shell 命令
    - grep_search:  文本搜索

工具注册中心（ToolRegistry）：
    - 动态注册/注销工具
    - 三级权限模型（READ / WRITE / EXECUTE）
    - 按权限级别过滤获取工具列表

工具设计原则：
    1. 每个工具都是独立的 @tool 函数，单一职责
    2. 完整的 docstring（LangChain 用它生成 Function Calling 的 schema）
    3. 所有异常统一捕获，返回错误消息而非抛出异常
    4. 安全第一：Shell 工具有命令黑名单，防止意外破坏
"""

from .file_tools import read_file, write_file
from .registry import ToolPermission, ToolRegistry
from .search_tools import grep_search
from .shell_tools import run_shell

# ── 默认注册中心 ──
_default_registry = ToolRegistry()
_default_registry.register(read_file, ToolPermission.READ)
_default_registry.register(grep_search, ToolPermission.READ)
_default_registry.register(write_file, ToolPermission.WRITE)
_default_registry.register(run_shell, ToolPermission.EXECUTE)


def get_default_registry() -> ToolRegistry:
    """获取默认工具注册表。"""
    return _default_registry


def __getattr__(name: str):
    """模块级动态属性（PEP 562）。

    ALL_TOOLS 不再是 import 时的静态快照：每次通过
    agent_forge.tools.ALL_TOOLS 属性访问都会从默认注册表实时取值，
    动态注册的工具（如 MCP 工具）能立即出现。

    注意：`from agent_forge.tools import ALL_TOOLS` 仍在 import 时刻
    绑定值（Python 语义如此）；需要"始终最新"的场景请用
    get_default_registry().get_all_tools()。
    """
    if name == "ALL_TOOLS":
        return _default_registry.get_all_tools()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "read_file", "write_file", "run_shell", "grep_search",
    "ALL_TOOLS",
    "ToolRegistry", "ToolPermission", "get_default_registry",
]
