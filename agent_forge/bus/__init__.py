"""消息总线模块

提供 Agent 间通信的统一协议和路由机制。

设计思路：
    多 Agent 系统中，Agent 之间需要传递任务、结果、状态等信息。
    如果让 Agent 直接互相调用（点对点），会导致：
    - 强耦合：Agent A 必须知道 Agent B 的存在
    - 难扩展：新增 Agent 需要修改已有 Agent 的代码
    - 难观测：消息散落在各处调用中，无法统一追踪

    因此我们引入 Message Bus（消息总线）—— 所有 Agent 通过总线通信，
    发送方不需要知道接收方是谁，接收方也不需要知道消息来自哪里。
    这类似于计算机网络中的总线拓扑，或者 GUI 框架中的事件系统。

核心导出：
    - Message: 统一消息格式（role / intent / payload / metadata）
    - MessageIntent: 消息意图枚举
    - MessageBus: 发布-订阅消息总线
    - MessageInterceptor: 消息拦截器抽象基类
    - LoggingInterceptor: 日志拦截器实现
    - HumanApprovalInterceptor: 人工确认拦截器（Human-in-the-Loop）

与业界的对比：
    - CrewAI: Agent 之间通过 Task 对象传递，没有独立的消息层
    - AutoGen: Agent 之间直接对话（对话式），消息格式隐含在对话内容中
    - LangGraph: Agent 通过共享 State 传递，适合单图内协作，不适合跨图通信
    - AgentForge: 独立的消息层 + 统一协议，支持未来扩展到分布式场景
"""

from .bus import LoggingInterceptor, MessageBus, MessageInterceptor
from .interceptors import HumanApprovalInterceptor
from .message import Message, MessageIntent

__all__ = [
    "Message",
    "MessageIntent",
    "MessageBus",
    "MessageInterceptor",
    "LoggingInterceptor",
    "HumanApprovalInterceptor",
]
