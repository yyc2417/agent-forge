"""统一消息协议 —— Agent 间通信的数据格式

为什么需要统一的消息协议？
    在多 Agent 系统中，如果每个 Agent 之间传递的都是随意的 dict，会出几个问题：
    1. 类型不透明：收到一个 dict，不知道里面有什么字段，全靠文档约定
    2. 序列化混乱：存日志、传网络、写数据库时，每次都要手动处理
    3. 扩展困难：加个"消息来源"字段，所有消费方都要改代码

    统一协议把所有消息约束在同一个 dataclass 中：
    - 发送方知道该填什么字段
    - 接收方知道能取什么字段
    - 序列化/反序列化统一在一个地方处理

    这也是为什么 HTTP 有 Request/Response 标准格式、
    gRPC 有 Protobuf schema —— 通信协议的标准化是系统可扩展的基础。

为什么用 dataclass 而不是 pydantic？
    - pydantic 提供运行时类型验证，但引入额外依赖
    - 当前阶段消息格式简单，标准库 dataclass 足够
    - 如果后续需要严格的 schema 验证（如分布式部署），可以无痛切换到 pydantic
    - 这是一个"最小依赖"策略：先简单，需要时再升级

消息的四个核心字段：
    ┌──────────┬──────────────────────────────────────────────┐
    │ 字段      │ 职责                                         │
    ├──────────┼──────────────────────────────────────────────┤
    │ role     │ 谁发的（Agent 的唯一标识，如 "coder"）         │
    │ intent   │ 想干什么（REQUEST/RESPONSE/BROADCAST/EVENT）   │
    │ payload  │ 具体内容（实际数据，结构由业务场景决定）         │
    │ metadata │ 附加信息（时间戳、追踪 ID 等，按需填充）        │
    └──────────┴──────────────────────────────────────────────┘

    额外字段（自动填充）：
    - message_id: 全局唯一 ID（UUID4），用于消息追踪和去重
    - timestamp: 创建时间戳，用于排序和超时判断
    - reply_to: 关联的请求消息 ID，用于 REQUEST-RESPONSE 配对
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ─── 消息意图枚举 ────────────────────────────────────────────

class MessageIntent(str, Enum):
    """消息意图 —— 标识这条消息"想干什么"。

    为什么用 str + Enum 双继承？
    - str: 让枚举值可以直接 JSON 序列化（str(MessageIntent.REQUEST) == "request"）
    - Enum: 提供类型安全，IDE 自动补全，防止拼写错误

    五种意图覆盖了 Agent 协作的主要场景：
    - REQUEST:   请求执行任务，期望收到 RESPONSE
    - RESPONSE:  对某个 REQUEST 的回复，通过 reply_to 关联
    - BROADCAST: 通知所有 Agent（如"任务完成"、"系统关闭"）
    - EVENT:     系统级事件（如"Agent 上线"、"错误告警"）
    - HEARTBEAT: Agent 存活检测（为后续 Dashboard 和分布式部署预留）
    """

    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    EVENT = "event"
    HEARTBEAT = "heartbeat"


# ─── 消息实体 ────────────────────────────────────────────────

@dataclass
class Message:
    """统一消息实体 —— Agent 间通信的唯一数据载体。

    所有 Agent 之间的信息传递都必须包装为 Message 对象。
    这不是过度设计——统一格式让消息的创建、传递、存储、回放都在同一条路径上，
    而不是散落在各种 dict 和 tuple 中。

    Attributes:
        role: 发送方的 Agent 标识。
              用 str 而非 Enum，因为 Agent 角色是动态的
              （阶段 2 Orchestrator 会在运行时动态创建 Specialist Agent）。
        intent: 消息意图，决定 MessageBus 如何路由这条消息。
        payload: 消息的实际内容。
                 用 dict[str, Any] 保持灵活性——不同 Agent 传不同结构。
                 后续如果需要严格验证，可以在 publish() 时加 schema 检查。
        metadata: 附加元数据，按需填充。
                  典型用法：{"source": "user_input", "priority": "high"}
        message_id: 全局唯一 ID，自动生成为 UUID4。
                    用于消息追踪、去重、以及 REQUEST-RESPONSE 配对。
                    为什么用 UUID 而不是自增 ID？
                    因为未来扩展到分布式时，自增 ID 需要中心节点协调，
                    而 UUID 可以在任何节点独立生成且保证全局唯一。
        timestamp: 消息创建时间（Unix 时间戳），自动填充。
                   用于排序、超时判断、Dashboard 时间线展示。
        reply_to: 关联的请求消息 ID。
                  当 intent=RESPONSE 时，填入对应的 REQUEST 的 message_id。
                  这让"Agent A 问了一个问题，Agent B 回答"成为一个可追溯的配对。
                  当 intent 不是 RESPONSE 时，保持为 None。
                  当前状态：预留字段，已在 Orchestrator._dispatch_to_agent 中填充，
                  用于消息历史追溯展示，尚未被业务逻辑消费。

    Example:
        >>> msg = Message(
        ...     role="coder",
        ...     intent=MessageIntent.REQUEST,
        ...     payload={"task": "写一个排序函数", "language": "python"},
        ... )
        >>> msg.message_id  # 自动生成 UUID
        'a1b2c3d4-...'
        >>> msg.to_dict()   # 可序列化
        {'role': 'coder', 'intent': 'request', ...}
    """

    # ── 必填字段 ──
    role: str
    intent: MessageIntent
    payload: dict[str, Any] = field(default_factory=dict)

    # ── 可选字段 ──
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str = ""
    timestamp: float = 0.0
    reply_to: str | None = None

    def __post_init__(self) -> None:
        """自动填充 message_id 和 timestamp。

        如果创建时显式传入了这两个值（如从 dict 反序列化），则保留原值。
        否则自动生成 UUID 和当前时间戳。
        """
        if not self.message_id:
            self.message_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = time.time()

    # ── 序列化方法 ──────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """将消息序列化为 dict。

        用途：
        - JSON 序列化后存储到文件/数据库
        - 通过网络传输给其他进程
        - Dashboard 展示消息详情
        - 日志记录

        Returns:
            包含所有字段的字典，intent 转为字符串值。
        """
        return {
            "role": self.role,
            "intent": self.intent.value,  # Enum → str
            "payload": self.payload,
            "metadata": self.metadata,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "reply_to": self.reply_to,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """从 dict 反序列化为 Message 对象。

        与 to_dict() 互为逆操作。用于：
        - 从 JSON 文件/数据库加载历史消息
        - 接收网络传输的消息
        - 消息回放（replay）

        Args:
            data: 包含消息字段的字典。
                  intent 可以是字符串（"request"）或 MessageIntent 枚举值。

        Returns:
            重建的 Message 对象。

        Raises:
            KeyError: 如果缺少必要字段（role, intent）。
            ValueError: 如果 intent 值不在枚举范围内。
        """
        # intent 可能是 str（从 JSON 加载）或 MessageIntent（从内存创建）
        intent = data["intent"]
        if isinstance(intent, str):
            intent = MessageIntent(intent)

        return cls(
            role=data["role"],
            intent=intent,
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
            message_id=data.get("message_id", ""),
            timestamp=data.get("timestamp", 0.0),
            reply_to=data.get("reply_to"),
        )

    # ── 可读表示 ────────────────────────────────────────────

    def __repr__(self) -> str:
        """简洁的消息表示，用于调试日志。"""
        payload_preview = str(self.payload)[:80]
        if len(str(self.payload)) > 80:
            payload_preview += "..."
        return (
            f"Message(role={self.role!r}, intent={self.intent.value}, "
            f"payload={payload_preview})"
        )
