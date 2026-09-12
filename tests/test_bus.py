"""MessageBus 单元测试。"""

from agent_forge.bus import (
    LoggingInterceptor,
    Message,
    MessageBus,
    MessageIntent,
    MessageInterceptor,
)


class TestMessageBus:
    """MessageBus 核心功能测试。"""

    def test_subscribe_and_publish(self, bus):
        received = []
        bus.subscribe("intent.request", lambda msg: received.append(msg))
        bus.publish(Message(role="a", intent=MessageIntent.REQUEST, payload={"x": 1}))
        assert len(received) == 1
        assert received[0].payload == {"x": 1}

    def test_wildcard_subscribe(self, bus):
        received = []
        bus.subscribe("*", lambda msg: received.append(msg))
        bus.publish(Message(role="a", intent=MessageIntent.REQUEST))
        bus.publish(Message(role="b", intent=MessageIntent.EVENT))
        assert len(received) == 2

    def test_role_subscribe(self, bus):
        received = []
        bus.subscribe("role.coder", lambda msg: received.append(msg))
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT))
        bus.publish(Message(role="reviewer", intent=MessageIntent.EVENT))
        assert len(received) == 1

    def test_multiple_handlers(self, bus):
        count = [0, 0]
        bus.subscribe("*", lambda msg: count.__setitem__(0, count[0] + 1))
        bus.subscribe("*", lambda msg: count.__setitem__(1, count[1] + 1))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert count == [1, 1]

    def test_unsubscribe(self, bus):
        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe("*", handler)
        bus.unsubscribe("*", handler)
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert len(received) == 0

    def test_handler_exception_isolation(self, bus):
        """单个 handler 异常不影响其他 handler。"""
        received = []
        bus.subscribe("*", lambda msg: 1 / 0)  # 会抛异常
        bus.subscribe("*", lambda msg: received.append(msg))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert len(received) == 1

    def test_get_history(self, bus):
        bus.publish(Message(role="a", intent=MessageIntent.REQUEST))
        bus.publish(Message(role="b", intent=MessageIntent.EVENT))
        bus.publish(Message(role="a", intent=MessageIntent.RESPONSE))
        history = bus.get_history()
        assert len(history) == 3

    def test_get_history_with_role_filter(self, bus):
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        bus.publish(Message(role="b", intent=MessageIntent.EVENT))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        history = bus.get_history(role="a")
        assert len(history) == 2

    def test_get_history_with_intent_filter(self, bus):
        bus.publish(Message(role="a", intent=MessageIntent.REQUEST))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        history = bus.get_history(intent=MessageIntent.REQUEST)
        assert len(history) == 1

    def test_get_history_limit(self, bus):
        for i in range(10):
            bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        history = bus.get_history(limit=3)
        assert len(history) == 3

    def test_clear_history(self, bus):
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        bus.clear_history()
        assert len(bus.get_history()) == 0


class TestInterceptor:
    """拦截器测试。"""

    def test_interceptor_passthrough(self, bus):
        bus.add_interceptor(LoggingInterceptor())
        received = []
        bus.subscribe("*", lambda msg: received.append(msg))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert len(received) == 1

    def test_interceptor_block(self, bus):
        class BlockAll(MessageInterceptor):
            def intercept(self, message):
                return None  # 阻断所有消息

        bus.add_interceptor(BlockAll())
        received = []
        bus.subscribe("*", lambda msg: received.append(msg))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert len(received) == 0

    def test_interceptor_chain(self, bus):
        """拦截器链按添加顺序执行。"""
        order = []

        class First(MessageInterceptor):
            def intercept(self, message):
                order.append("first")
                return message

        class Second(MessageInterceptor):
            def intercept(self, message):
                order.append("second")
                return message

        bus.add_interceptor(First())
        bus.add_interceptor(Second())
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert order == ["first", "second"]

    def test_interceptor_exception_isolated(self):
        """修复验证：单个拦截器异常不再炸掉整个 publish。"""
        from agent_forge.bus import MessageBus

        bus = MessageBus()

        class Exploding(MessageInterceptor):
            def intercept(self, message):
                raise RuntimeError("boom")

        bus.add_interceptor(Exploding())
        received = []
        bus.subscribe("*", lambda msg: received.append(msg))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        # 拦截器挂了，但订阅者仍收到消息（拦截器被跳过）
        assert len(received) == 1


class TestHistorySemantics:
    """消息历史语义：limit 边界 + 深拷贝 + 有界滚动。"""

    def test_limit_zero_returns_empty(self):
        """修复验证：limit=0 返回空列表（旧版 [-0:] 意外返回全部）。"""
        bus = MessageBus()
        for i in range(5):
            bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert bus.get_history(limit=0) == []

    def test_limit_none_returns_all(self):
        bus = MessageBus(history_limit=100)
        for i in range(60):
            bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert len(bus.get_history(limit=None)) == 60

    def test_default_limit_keeps_latest(self):
        bus = MessageBus()
        for i in range(10):
            bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        history = bus.get_history(limit=3)
        assert len(history) == 3
        assert history[-1].payload == {}

    def test_deep_copy_protects_history(self):
        """修复验证：修改返回消息的嵌套 payload 不再穿透 _history。"""
        bus = MessageBus()
        bus.publish(Message(role="a", intent=MessageIntent.EVENT,
                            payload={"nested": {"v": 1}}))
        history = bus.get_history(limit=None)
        history[0].payload["nested"]["v"] = 999
        fresh = bus.get_history(limit=None)
        assert fresh[0].payload["nested"]["v"] == 1

    def test_history_bounded(self):
        """修复验证：_history 有界滚动，不无限增长。"""
        bus = MessageBus(history_limit=10)
        for i in range(50):
            bus.publish(Message(role="a", intent=MessageIntent.EVENT))
        assert len(bus._history) == 10
        assert len(bus.get_history(limit=None)) == 10
