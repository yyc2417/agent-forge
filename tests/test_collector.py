"""BusCollector 单元测试。"""

from agent_forge.bus import Message, MessageIntent
from agent_forge.dashboard.collector import (
    STATUS_CALLING_TOOL,
    STATUS_IDLE,
    STATUS_THINKING,
    BusCollector,
)


class TestBusCollector:
    """BusCollector 核心功能测试。"""

    def test_attach_and_collect(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        messages = collector.get_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "coder"

    def test_events_filtered(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="a", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        bus.publish(Message(role="a", intent=MessageIntent.REQUEST,
                            payload={"task": "hello"}))
        events = collector.get_events()
        assert len(events) == 1  # 只有 EVENT 类型

    def test_agent_state_tracking(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.thinking"}))
        states = collector.get_agent_states()
        assert "coder" in states
        assert states["coder"]["status"] == STATUS_THINKING

    def test_tool_request_updates_state(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.tool_request",
                                     "tool_name": "read_file"}))
        states = collector.get_agent_states()
        assert states["coder"]["status"] == STATUS_CALLING_TOOL
        assert states["coder"]["current_tool"] == "read_file"

    def test_completed_resets_to_idle(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.completed"}))
        states = collector.get_agent_states()
        assert states["coder"]["status"] == STATUS_IDLE

    def test_get_stats(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="a", intent=MessageIntent.REQUEST))
        bus.publish(Message(role="b", intent=MessageIntent.RESPONSE))
        bus.publish(Message(role="a", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.tool_request",
                                     "tool_name": "x"}))
        stats = collector.get_stats()
        assert stats["total_messages"] == 3
        assert stats["request_count"] == 1
        assert stats["response_count"] == 1
        assert stats["tool_calls"] == 1
        assert stats["agent_count"] == 2

    def test_clear(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="a", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        collector.clear()
        assert len(collector.get_messages()) == 0
        assert len(collector.get_events()) == 0
        assert len(collector.get_agent_states()) == 0

    def test_is_running(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        assert not collector.is_running()
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        assert collector.is_running()
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.completed"}))
        assert not collector.is_running()

    def test_detach(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        collector.detach()
        bus.publish(Message(role="a", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        assert len(collector.get_messages()) == 0

    def test_message_count_per_agent(self, bus):
        collector = BusCollector()
        collector.attach(bus)
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        bus.publish(Message(role="coder", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.thinking"}))
        bus.publish(Message(role="reviewer", intent=MessageIntent.EVENT,
                            payload={"event_type": "agent.started"}))
        states = collector.get_agent_states()
        assert states["coder"]["message_count"] == 2
        assert states["reviewer"]["message_count"] == 1
