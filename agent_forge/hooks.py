"""生命周期 Hooks 管理器

提供 Agent 执行过程中的 5 个标准事件钩子，允许外部代码在关键节点
插入自定义逻辑（日志、监控、调试、成本统计等）。

5 个标准事件：
    - pre_llm_call:       LLM 调用前（可修改消息列表）
    - post_llm_call:      LLM 调用后（可检查响应）
    - pre_tool_use:       工具执行前（可拦截/修改参数）
    - post_tool_use:      工具执行后（可检查结果）
    - on_message_received: 收到 Bus 消息时

设计理念：
    Hooks 是观察者模式的实现——Agent 的核心逻辑不关心谁在监听，
    只负责在关键时刻触发事件。监听者可以自由注册/注销，互不影响。

    与 MessageBus 的区别：
    - MessageBus 是 Agent 间通信（跨 Agent）
    - Hooks 是 Agent 内部的生命周期事件（单 Agent 粒度更细）

使用方式：
    hooks = HookManager()
    hooks.register("pre_llm_call", lambda **kw: print(f"LLM 调用，消息数: {len(kw['messages'])}"))
    hooks.register("post_tool_use", lambda **kw: print(f"工具 {kw['tool_name']} 执行完成"))

    agent = BaseAgent(name="coder", hooks=hooks, ...)
"""

from collections import defaultdict
from typing import Callable, Literal

from agent_forge.utils import safe_print

# ─── 标准事件常量 ──────────────────────────────────────────

PRE_LLM_CALL = "pre_llm_call"
POST_LLM_CALL = "post_llm_call"
PRE_TOOL_USE = "pre_tool_use"
POST_TOOL_USE = "post_tool_use"
ON_MESSAGE_RECEIVED = "on_message_received"

ALL_EVENTS = [
    PRE_LLM_CALL,
    POST_LLM_CALL,
    PRE_TOOL_USE,
    POST_TOOL_USE,
    ON_MESSAGE_RECEIVED,
]

# 事件类型提示
HookEvent = Literal[
    "pre_llm_call",
    "post_llm_call",
    "pre_tool_use",
    "post_tool_use",
    "on_message_received",
]


class HookManager:
    """生命周期 Hooks 管理器 —— 注册和触发 Agent 执行过程中的事件回调。

    每个事件可以有多个回调函数，按注册顺序执行。
    单个回调的异常不会影响其他回调的执行（try/except 隔离）。

    回调函数签名：所有回调接收 **kwargs，忽略不需要的参数。
    这样未来新增 Hook 事件不会破坏已有回调。

    各事件的 kwargs 内容：
    - pre_llm_call:       agent=str, messages=list
    - post_llm_call:      agent=str, response=AIMessage
    - pre_tool_use:       agent=str, tool_name=str, tool_args=dict
    - post_tool_use:      agent=str, tool_name=str, output=str
    - on_message_received: agent=str, message=Message
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = defaultdict(list)

    def register(self, event: str, callback: Callable) -> None:
        """注册一个事件回调。

        Args:
            event: 事件名称（如 "pre_llm_call"）。
            callback: 回调函数，接收 **kwargs。
        """
        if event not in ALL_EVENTS:
            safe_print(f"  [HookManager] 警告: 未知事件 '{event}'，仍然注册")
        self._hooks[event].append(callback)

    def unregister(self, event: str, callback: Callable) -> None:
        """注销一个事件回调。

        Args:
            event: 事件名称。
            callback: 要注销的回调函数（必须是之前注册的同一个对象）。
        """
        hooks = self._hooks.get(event, [])
        if callback in hooks:
            hooks.remove(callback)

    def trigger(self, event: str, **kwargs) -> None:
        """触发一个事件，依次调用所有已注册的回调。

        每个回调用 try/except 包裹，单个回调的异常不会中断其他回调。

        Args:
            event: 事件名称。
            **kwargs: 传递给回调函数的参数（各事件不同）。
        """
        for callback in self._hooks.get(event, []):
            try:
                callback(**kwargs)
            except Exception as e:
                safe_print(
                    f"  [HookManager] 回调异常 ({event}): "
                    f"{type(e).__name__}: {e}"
                )

    def get_registered_events(self) -> list[str]:
        """返回当前有注册回调的所有事件名称。"""
        return [event for event, hooks in self._hooks.items() if hooks]

    def clear(self, event: str | None = None) -> None:
        """清空回调注册。

        Args:
            event: 指定事件名称只清空该事件。None 则清空所有事件。
        """
        if event:
            self._hooks[event] = []
        else:
            self._hooks.clear()
