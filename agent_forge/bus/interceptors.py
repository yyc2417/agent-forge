"""Human-in-the-Loop 拦截器

基于 MessageBus 的 MessageInterceptor 基础设施，实现人工确认拦截。

拦截规则：
    - 可配置拦截的 intent 列表（默认拦截 REQUEST）
    - 可配置拦截的 role 列表（默认拦截所有）
    - 拦截时打印消息摘要，等待用户输入 y/n
    - y → 放行，n → 阻断（返回 None，消息不会到达订阅者）

使用场景：
    - Demo 中展示 HITL 能力
    - 生产环境中用于关键操作审批
    - 例如：Agent 要执行 rm 命令，先暂停让人工确认

使用方式：
    interceptor = HumanApprovalInterceptor(
        intercept_intents=[MessageIntent.REQUEST],
        intercept_roles=["coder"],  # 只拦截发给 coder 的 REQUEST
    )
    bus.add_interceptor(interceptor)
"""

from agent_forge.bus.bus import MessageInterceptor
from agent_forge.bus.message import Message, MessageIntent
from agent_forge.utils import safe_print


class HumanApprovalInterceptor(MessageInterceptor):
    """人工确认拦截器 —— 拦截特定消息，等待用户确认后放行或阻断。

    Attributes:
        _intercept_intents: 需要拦截的消息意图集合。
        _intercept_roles: 需要拦截的角色集合。None 表示拦截所有角色。
        _auto_approve: 自动批准模式（不暂停，直接放行）。用于测试。
    """

    def __init__(
        self,
        intercept_intents: list[MessageIntent] | None = None,
        intercept_roles: list[str] | None = None,
        auto_approve: bool = False,
    ) -> None:
        """初始化人工确认拦截器。

        Args:
            intercept_intents: 需要拦截的消息意图列表。
                              默认拦截 REQUEST。
            intercept_roles: 需要拦截的角色列表。
                            None 表示拦截所有角色的匹配消息。
            auto_approve: 自动批准模式。True 时不暂停，直接放行。
                         用于自动化测试场景。
        """
        self._intercept_intents = set(
            intercept_intents or [MessageIntent.REQUEST]
        )
        self._intercept_roles = set(intercept_roles) if intercept_roles else None
        self._auto_approve = auto_approve

    def intercept(self, message: Message) -> Message | None:
        """拦截消息，判断是否需要人工确认。

        Args:
            message: 待拦截的消息。

        Returns:
            Message: 放行（原消息不变）。
            None: 阻断（用户拒绝）。
        """
        if not self._should_intercept(message):
            return message

        if self._auto_approve:
            safe_print(f"  [HITL] 自动批准: {message.role} → {message.intent.value}")
            return message

        return self._ask_user(message)

    # ─── 内部方法 ──────────────────────────────────────────

    def _should_intercept(self, message: Message) -> bool:
        """判断消息是否应该被拦截。

        条件：intent 在拦截列表中 AND (角色在拦截列表中 OR 角色列表为 None)。
        """
        if message.intent not in self._intercept_intents:
            return False
        if self._intercept_roles and message.role not in self._intercept_roles:
            return False
        return True

    def _ask_user(self, message: Message) -> Message | None:
        """打印消息摘要，等待用户确认。

        Returns:
            Message（放行）或 None（阻断）。
        """
        payload_preview = str(message.payload)[:150]
        safe_print(f"\n{'─' * 50}")
        safe_print("  [人工确认] 拦截到消息:")
        safe_print(f"    发送方: {message.role}")
        safe_print(f"    意图:   {message.intent.value}")
        safe_print(f"    内容:   {payload_preview}")
        safe_print(f"{'─' * 50}")

        try:
            answer = input("  批准此操作？(y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            safe_print("\n  [人工确认] 输入中断，默认拒绝")
            return None

        if answer in ("y", "yes"):
            safe_print("  [人工确认] 已批准")
            return message
        else:
            safe_print("  [人工确认] 已拒绝")
            return None
