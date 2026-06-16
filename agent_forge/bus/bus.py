"""消息总线 —— 发布-订阅模式的 Agent 间通信中枢

为什么选 Pub/Sub（发布-订阅）而不是点对点？

    点对点通信（Agent A 直接调用 Agent B）：
    - 优点：简单直接，两个 Agent 之间没有中间层
    - 缺点：强耦合（A 必须知道 B 的存在和接口），难扩展（加新 Agent 要改旧代码）

    发布-订阅通信（Agent A 发布消息 → Bus → 订阅者收到）：
    - 优点：解耦（发送方不知道接收方是谁），易扩展（新 Agent 只需订阅）
    - 缺点：增加了一层中间件，调试时需要看 Bus 的路由逻辑

    我们选择 Pub/Sub，因为多 Agent 系统的核心挑战是"谁该处理这个任务"——
    这个决策不应该硬编码在发送方中，而应该由消息内容动态决定。
    Pub/Sub 天然支持这种"按内容路由"的模式。

    类比：
    - 点对点 ≈ 打电话（必须知道对方号码）
    - Pub/Sub ≈ 广播电台（主播只管播，谁在听不关心）

为什么当前是同步实现而不是异步？
    - LangGraph 的 graph.invoke() 是同步的，整个 Agent 循环在单线程内完成
    - 异步（asyncio）增加了理解复杂度，阶段 1聚焦架构设计而非并发模型
    - 当阶段 2 Orchestrator 需要并行调度多个 Agent 时，可以升级为异步
    - 升级路径：publish() → async publish()，handler → async handler

与消息队列的区别：
    - Redis/RabbitMQ/Kafka: 独立的进程，支持分布式、持久化、消费者组
    - 我们的 MessageBus: 单进程内存实现，适合单机多 Agent 协作
    - 如果未来需要分布式部署，可以将 MessageBus 的实现替换为 Redis Pub/Sub，
      接口保持不变——这正是抽象层的价值

拦截器机制（MessageInterceptor）：
    - 借鉴了 Web 框架的中间件模式（如 FastAPI 的 middleware）
    - 拦截器可以在消息到达订阅者之前：检查、修改、或阻断
    - 核心用途：Human-in-the-Loop（人工确认关键操作后再放行）
    - 拦截器链按添加顺序执行（责任链模式）
"""

import copy
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Callable

from agent_forge.utils import safe_print

from .message import Message, MessageIntent

# ─── 类型别名 ────────────────────────────────────────────────

# 订阅者处理器：接收一条消息，无需返回值
MessageHandler = Callable[[Message], None]


# ─── 拦截器抽象基类 ──────────────────────────────────────────

class MessageInterceptor(ABC):
    """消息拦截器 —— 在消息到达订阅者之前进行检查/修改/阻断。

    这是策略模式的应用：不同的拦截策略各自实现一个 Interceptor，
    通过 add_interceptor() 注册到 Bus 中，形成拦截器链。

    典型实现：
    - LoggingInterceptor: 记录所有消息（调试/观测用）
    - HumanApprovalInterceptor: 暂停等待人工确认（Human-in-the-Loop）
    - FilterInterceptor: 按规则过滤消息（如丢弃低优先级消息）

    执行顺序：按 add_interceptor() 的添加顺序，先添加的先执行。
    如果某个拦截器返回 None，消息被阻断，后续拦截器和订阅者都不会收到。
    """

    @abstractmethod
    def intercept(self, message: Message) -> Message | None:
        """拦截一条消息。

        Args:
            message: 即将发布的消息对象。

        Returns:
            Message: 放行（可以修改后的消息）
            None: 阻断消息（不会到达任何订阅者）
        """
        ...


class LoggingInterceptor(MessageInterceptor):
    """日志拦截器 —— 记录所有经过的消息，用于调试和观测。

    这是最简单的拦截器实现：不做任何修改，只打印日志然后放行。
    但它展示了一个重要的设计：可观测性是"免费"的——
    不需要修改 Agent 代码，只需要在 Bus 层添加一个拦截器。
    """

    def intercept(self, message: Message) -> Message:
        """打印消息摘要并放行。"""
        safe_print(
            f"  [BUS] {message.intent.value:>10} | "
            f"{message.role:<12} | "
            f"{str(message.payload)[:60]}"
        )
        return message  # 放行，不做修改


# ─── 消息总线 ────────────────────────────────────────────────

class MessageBus:
    """消息总线 —— 所有 Agent 间通信的中枢。

    核心机制：发布-订阅（Pub/Sub）

    路由规则：
        每条消息发布时，Bus 会为它生成多个"事件键"，
        订阅者可以订阅任意一个事件键来接收消息。

        事件键格式：
        - "intent.{type}"  → 按意图订阅（如 "intent.request"）
        - "role.{name}"    → 按角色订阅（如 "role.coder"）
        - "*"              → 通配符，接收所有消息

        示例：
            bus.subscribe("intent.request", handler)   # 只收到 REQUEST 消息
            bus.subscribe("role.reviewer", handler)    # 只收到 reviewer 的消息
            bus.subscribe("*", handler)                # 收到所有消息

    使用方式：
        bus = MessageBus()
        bus.add_interceptor(LoggingInterceptor())

        def on_request(msg: Message):
            print(f"收到请求: {msg.payload}")

        bus.subscribe("intent.request", on_request)
        bus.publish(Message(role="coder", intent=MessageIntent.REQUEST, payload={...}))

    线程安全说明：
        当前实现不是线程安全的。单进程单线程场景下没有问题。
        如果后续需要多线程/多进程，需要：
        - 给 _subscribers 加锁（threading.Lock）
        - 或升级为 asyncio.Queue + async handler
    """

    def __init__(self) -> None:
        # 订阅表：event_type → [handler, ...]
        # 同一个 event_type 可以有多个 handler（一对多广播）
        self._subscribers: dict[str, list[MessageHandler]] = defaultdict(list)

        # 消息历史：所有已发布消息的有序记录
        # 用于 Dashboard 展示、消息回放、Agent 回顾历史
        self._history: list[Message] = []

        # 拦截器链：按添加顺序执行
        self._interceptors: list[MessageInterceptor] = []

    # ── 订阅/取消订阅 ──────────────────────────────────────

    def subscribe(self, event_type: str, handler: MessageHandler) -> None:
        """订阅特定事件类型。

        Args:
            event_type: 事件键，格式见路由规则说明。
            handler: 收到匹配消息后调用的回调函数。
        """
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: MessageHandler) -> None:
        """取消订阅。

        Args:
            event_type: 事件键。
            handler: 要移除的回调函数（必须是之前 subscribe 时传入的同一个对象）。
        """
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    # ── 发布消息 ──────────────────────────────────────────

    def publish(self, message: Message) -> None:
        """发布消息到总线。

        执行流程：
        1. 记录到 _history（不管是否有人订阅）
        2. 经过所有拦截器（任何一个返回 None 则阻断）
        3. 根据消息内容生成所有匹配的事件键
        4. 逐个调用匹配的 handler

        Args:
            message: 要发布的消息对象。
        """
        # 1. 记录历史
        self._history.append(message)

        # 2. 拦截器链
        current_message: Message | None = message
        for interceptor in self._interceptors:
            if current_message is None:
                return  # 被拦截器阻断
            current_message = interceptor.intercept(current_message)

        if current_message is None:
            return

        # 3. 生成事件键并路由
        event_keys = self._get_event_keys(current_message)
        for key in event_keys:
            for handler in self._subscribers.get(key, []):
                try:
                    handler(current_message)
                except Exception as e:
                    # handler 异常不应影响其他 handler 或 Bus 的运行
                    safe_print(f"  [BUS] handler 异常: {type(e).__name__}: {e}")

    def _get_event_keys(self, message: Message) -> list[str]:
        """为消息生成所有匹配的事件键。

        一条消息可以同时匹配多个事件键：
        - intent 维度：所有 REQUEST 消息都匹配 "intent.request"
        - role 维度：role="coder" 的消息都匹配 "role.coder"
        - 通配符：所有消息都匹配 "*"

        Returns:
            事件键列表（去重）。
        """
        return [
            f"intent.{message.intent.value}",
            f"role.{message.role}",
            "*",
        ]

    # ── 拦截器管理 ─────────────────────────────────────────

    def add_interceptor(self, interceptor: MessageInterceptor) -> None:
        """添加消息拦截器（追加到链尾）。

        拦截器按添加顺序执行，先添加的先拦截。
        """
        self._interceptors.append(interceptor)

    # ── 消息历史查询 ──────────────────────────────────────

    def get_history(
        self,
        role: str | None = None,
        intent: MessageIntent | None = None,
        limit: int = 50,
    ) -> list[Message]:
        """查询消息历史（支持按 role/intent 过滤）。

        用于：
        - Dashboard 展示消息流时间线
        - Agent 回顾历史做决策
        - 调试时回放消息序列
        - /history 命令（Demo 中）

        Args:
            role: 按发送方过滤（如 "coder"）。None 表示不过滤。
            intent: 按意图过滤（如 MessageIntent.REQUEST）。None 表示不过滤。
            limit: 返回消息的最大数量，取最新的 N 条。

        Returns:
            匹配条件的消息列表，按时间顺序排列（旧的在前）。
        """
        filtered = self._history

        if role is not None:
            filtered = [m for m in filtered if m.role == role]
        if intent is not None:
            filtered = [m for m in filtered if m.intent == intent]

        # 取最新的 limit 条
        # 返回浅拷贝：防止调用方修改返回的 Message 对象影响 _history 中的原始数据
        return [copy.copy(m) for m in filtered[-limit:]]

    def clear_history(self) -> None:
        """清空消息历史。"""
        self._history.clear()
