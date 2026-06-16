"""Message 和 MessageIntent 单元测试。"""

import time

from agent_forge.bus.message import Message, MessageIntent


class TestMessageIntent:
    """MessageIntent 枚举测试。"""

    def test_enum_values(self):
        assert MessageIntent.REQUEST.value == "request"
        assert MessageIntent.RESPONSE.value == "response"
        assert MessageIntent.EVENT.value == "event"
        assert MessageIntent.BROADCAST.value == "broadcast"
        assert MessageIntent.HEARTBEAT.value == "heartbeat"

    def test_str_compatible(self):
        """str + Enum 双继承：.value 可以直接 JSON 序列化。"""
        assert MessageIntent.REQUEST.value == "request"


class TestMessage:
    """Message dataclass 测试。"""

    def test_create_basic(self):
        msg = Message(role="coder", intent=MessageIntent.REQUEST, payload={"task": "test"})
        assert msg.role == "coder"
        assert msg.intent == MessageIntent.REQUEST
        assert msg.payload == {"task": "test"}

    def test_auto_fill_message_id(self):
        msg = Message(role="test", intent=MessageIntent.EVENT)
        assert msg.message_id != ""
        assert len(msg.message_id) == 36  # UUID4 format

    def test_auto_fill_timestamp(self):
        before = time.time()
        msg = Message(role="test", intent=MessageIntent.EVENT)
        after = time.time()
        assert before <= msg.timestamp <= after

    def test_explicit_message_id(self):
        msg = Message(role="test", intent=MessageIntent.EVENT, message_id="custom-id")
        assert msg.message_id == "custom-id"

    def test_to_dict(self):
        msg = Message(
            role="coder",
            intent=MessageIntent.REQUEST,
            payload={"task": "hello"},
            message_id="test-id",
            timestamp=12345.0,
        )
        d = msg.to_dict()
        assert d["role"] == "coder"
        assert d["intent"] == "request"  # enum -> str
        assert d["payload"] == {"task": "hello"}
        assert d["message_id"] == "test-id"
        assert d["timestamp"] == 12345.0

    def test_from_dict(self):
        d = {
            "role": "reviewer",
            "intent": "response",
            "payload": {"result": "ok"},
            "message_id": "msg-1",
            "timestamp": 99999.0,
            "reply_to": "msg-0",
        }
        msg = Message.from_dict(d)
        assert msg.role == "reviewer"
        assert msg.intent == MessageIntent.RESPONSE
        assert msg.reply_to == "msg-0"

    def test_roundtrip_serialization(self):
        original = Message(
            role="orchestrator",
            intent=MessageIntent.BROADCAST,
            payload={"event": "shutdown"},
        )
        d = original.to_dict()
        restored = Message.from_dict(d)
        assert restored.role == original.role
        assert restored.intent == original.intent
        assert restored.payload == original.payload
        assert restored.message_id == original.message_id

    def test_reply_to_none_by_default(self):
        msg = Message(role="test", intent=MessageIntent.REQUEST)
        assert msg.reply_to is None

    def test_metadata_default_empty(self):
        msg = Message(role="test", intent=MessageIntent.EVENT)
        assert msg.metadata == {}
