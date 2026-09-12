"""BusCollector —— Dashboard 数据采集层

订阅 MessageBus 的所有消息，分类存储，为 Dashboard 提供结构化数据。

设计思路：
    Dashboard 需要实时展示 Agent 的运行状态，但不能直接在 Agent 代码中
    插入 UI 更新逻辑（违反单一职责）。BusCollector 作为数据采集层，
    通过订阅 Bus 的 "*" 通配符事件，被动接收所有消息并结构化存储。

    Dashboard 通过定期调用 get_messages() / get_agent_states() / get_stats()
    来获取最新数据，实现"拉取"式的数据更新。

线程安全：
    Agent 在后台线程运行，BusCollector 的 _on_message 回调在该线程中被触发。
    Streamlit 在主线程中读取数据。因此所有读写操作都在 threading.Lock 内执行。

    返回数据使用深拷贝（copy.deepcopy），防止 Streamlit 读取时数据被并发修改。

与 LoggingInterceptor 的区别：
    - LoggingInterceptor：实时打印每条消息的摘要，用于终端调试
    - BusCollector：结构化存储所有消息 + 推导 Agent 状态 + 提供统计接口
    - 两者互补：LoggingInterceptor 是"实时流"，BusCollector 是"结构化存储"

使用方式：
    bus = MessageBus()
    collector = BusCollector()
    collector.attach(bus)

    # Agent 在后台线程运行...
    # Dashboard 定期调用：
    events = collector.get_events()
    states = collector.get_agent_states()
    stats = collector.get_stats()
"""

import copy
import threading
import time
from dataclasses import dataclass

from agent_forge.bus import Message, MessageBus, MessageIntent

# ─── Agent 状态常量 ──────────────────────────────────────────

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_THINKING = "thinking"
STATUS_CALLING_TOOL = "calling_tool"
STATUS_COMPLETED = "completed"

# event_type → Agent 状态映射
_EVENT_STATUS_MAP = {
    "agent.started": STATUS_RUNNING,
    "agent.thinking": STATUS_THINKING,
    "agent.tool_request": STATUS_CALLING_TOOL,
    "agent.tool_result": STATUS_THINKING,
    "agent.completed": STATUS_IDLE,
    # Orchestrator 事件
    "orchestrator.started": STATUS_RUNNING,
    "orchestrator.decomposing": STATUS_THINKING,
    "orchestrator.dispatching": STATUS_RUNNING,
    "orchestrator.reviewing": STATUS_THINKING,
    "orchestrator.aggregating": STATUS_THINKING,
    "orchestrator.completed": STATUS_COMPLETED,
}


# ─── Agent 状态快照 ─────────────────────────────────────────

@dataclass
class AgentSnapshot:
    """Agent 当前状态快照。

    Attributes:
        name: Agent 名称。
        status: 当前状态（idle/thinking/calling_tool/running/completed）。
        current_tool: 当前调用的工具名（仅 calling_tool 状态时有值）。
        message_count: 该 Agent 发出的消息总数。
        last_event_type: 最后一个事件类型。
        last_active: 最后活动时间戳。
    """
    name: str
    status: str = STATUS_IDLE
    current_tool: str = ""
    message_count: int = 0
    last_event_type: str = ""
    last_active: float = 0.0


# ─── BusCollector ───────────────────────────────────────────

class BusCollector:
    """数据采集器 —— 订阅 Bus 的 "*" 事件，结构化存储所有消息。

    线程安全：所有公共方法都在 _lock 内执行。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: list[dict] = []       # 所有消息（序列化后的 dict）
        self._events: list[dict] = []         # 事件时间线（仅 EVENT intent）
        self._agent_states: dict[str, AgentSnapshot] = {}
        self._start_time: float = 0.0
        self._bus: MessageBus | None = None

    def attach(self, bus: MessageBus) -> None:
        """绑定到指定的 MessageBus，订阅 "*" 通配符事件。

        幂等：重复 attach 同一个 Bus 不会重复订阅
        （重复订阅会导致消息与计数全部翻倍）。

        Args:
            bus: 要绑定的消息总线。
        """
        if self._bus is bus:
            return
        self._bus = bus
        self._start_time = time.time()
        bus.subscribe("*", self._on_message)

    def detach(self) -> None:
        """从当前 Bus 解绑。"""
        if self._bus:
            self._bus.unsubscribe("*", self._on_message)
            self._bus = None

    # ── 回调 ──────────────────────────────────────────────

    def _on_message(self, message: Message) -> None:
        """Bus "*" 订阅回调：解析消息，更新内部状态。

        在 Agent 的后台线程中被触发，因此必须在 _lock 内执行。
        """
        msg_dict = message.to_dict()

        with self._lock:
            # 1. 存储原始消息
            self._messages.append(msg_dict)

            # 2. 如果是 EVENT 消息，存储到事件时间线
            if message.intent == MessageIntent.EVENT:
                self._events.append(msg_dict)

                # 3. 推导 Agent 状态
                event_type = message.payload.get("event_type", "")
                self._update_agent_state(message.role, event_type, message.payload)

            # 4. 更新消息计数
            role = message.role
            if role not in self._agent_states:
                self._agent_states[role] = AgentSnapshot(name=role)
            self._agent_states[role].message_count += 1
            self._agent_states[role].last_active = message.timestamp

    def _update_agent_state(
        self, role: str, event_type: str, payload: dict
    ) -> None:
        """根据事件类型更新 Agent 状态快照。

        Args:
            role: Agent 名称。
            event_type: 事件类型（如 "agent.started"）。
            payload: 事件 payload。
        """
        if role not in self._agent_states:
            self._agent_states[role] = AgentSnapshot(name=role)

        snapshot = self._agent_states[role]
        snapshot.last_event_type = event_type
        # last_active 统一由 _on_message 步骤 4 用 message.timestamp 写入

        # 状态映射
        new_status = _EVENT_STATUS_MAP.get(event_type)
        if new_status:
            snapshot.status = new_status

        # 工具调用特殊处理
        if event_type == "agent.tool_request":
            snapshot.current_tool = payload.get("tool_name", "")
        elif event_type == "agent.tool_result":
            snapshot.current_tool = ""

    # ── 数据读取（线程安全）────────────────────────────────

    def get_messages(self, limit: int = 0) -> list[dict]:
        """获取所有消息的深拷贝。

        Args:
            limit: 返回最新的 N 条消息。0 表示返回全部。

        Returns:
            消息 dict 列表（深拷贝）。
        """
        with self._lock:
            data = self._messages if limit <= 0 else self._messages[-limit:]
            return copy.deepcopy(data)

    def get_events(self, limit: int = 0) -> list[dict]:
        """获取事件时间线的深拷贝。

        Args:
            limit: 返回最新的 N 条事件。0 表示返回全部。

        Returns:
            事件 dict 列表（深拷贝）。
        """
        with self._lock:
            data = self._events if limit <= 0 else self._events[-limit:]
            return copy.deepcopy(data)

    def get_agent_states(self) -> dict[str, dict]:
        """获取所有 Agent 的当前状态快照。

        Returns:
            {agent_name: {name, status, current_tool, message_count,
                          last_event_type, last_active}} 字典。
        """
        with self._lock:
            return {
                name: {
                    "name": snap.name,
                    "status": snap.status,
                    "current_tool": snap.current_tool,
                    "message_count": snap.message_count,
                    "last_event_type": snap.last_event_type,
                    "last_active": snap.last_active,
                }
                for name, snap in self._agent_states.items()
            }

    def get_stats(self) -> dict:
        """获取统计摘要。

        Returns:
            {
                "total_messages": int,
                "total_events": int,
                "agent_count": int,
                "tool_calls": int,
                "request_count": int,
                "response_count": int,
                "duration_seconds": float,
            }
        """
        with self._lock:
            tool_calls = sum(
                1 for m in self._events
                if m.get("payload", {}).get("event_type") == "agent.tool_request"
            )
            request_count = sum(
                1 for m in self._messages
                if m.get("intent") == "request"
            )
            response_count = sum(
                1 for m in self._messages
                if m.get("intent") == "response"
            )
            duration = time.time() - self._start_time if self._start_time else 0.0

            return {
                "total_messages": len(self._messages),
                "total_events": len(self._events),
                "agent_count": len(self._agent_states),
                "tool_calls": tool_calls,
                "request_count": request_count,
                "response_count": response_count,
                "duration_seconds": round(duration, 1),
            }

    def clear(self) -> None:
        """清空所有采集数据。"""
        with self._lock:
            self._messages.clear()
            self._events.clear()
            self._agent_states.clear()
            self._start_time = time.time()

    def is_running(self) -> bool:
        """检查是否有 Agent 正在运行（非 idle/completed 状态）。"""
        with self._lock:
            return any(
                snap.status in (STATUS_RUNNING, STATUS_THINKING, STATUS_CALLING_TOOL)
                for snap in self._agent_states.values()
            )
