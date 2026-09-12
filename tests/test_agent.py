"""BaseAgent 单元测试（包含真实 API 调用，标记为 slow）。"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent_forge.agents import BaseAgent
from agent_forge.tools import ALL_TOOLS, read_file


@pytest.mark.slow
class TestBaseAgentSlow:
    """需要真实 LLM API 的 BaseAgent 测试。"""

    def test_run_returns_nonempty(self):
        agent = BaseAgent(name="test", role="测试助手", tools=ALL_TOOLS)
        result = agent.run("回复'你好'两个字即可")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_run_without_tools(self):
        agent = BaseAgent(name="chat", role="聊天助手", tools=[])
        result = agent.run("回复'OK'即可")
        assert isinstance(result, str)
        assert len(result) > 0


class TestBaseAgentInit:
    """不需要 API 的 BaseAgent 初始化测试。"""

    def test_init_basic(self):
        agent = BaseAgent(name="test", role="测试", tools=[])
        assert agent.name == "test"
        assert agent.role == "测试"

    def test_get_system_prompt_includes_role(self):
        agent = BaseAgent(name="coder", role="Python 专家", tools=[])
        prompt = agent.get_system_prompt()
        assert "coder" in prompt
        assert "Python 专家" in prompt

    def test_get_system_prompt_includes_tools(self):
        agent = BaseAgent(name="test", role="test", tools=ALL_TOOLS)
        prompt = agent.get_system_prompt()
        assert "read_file" in prompt or "工具" in prompt


def _tool_call_msg(name: str = "read_file", call_id: str = "c1") -> AIMessage:
    """构造一条带工具调用的 AIMessage。"""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"path": "a.py"}, "id": call_id}],
    )


class TestLoopProtection:
    """循环保护：max_turns 只统计本轮（最后一条 HumanMessage 之后）。"""

    def _agent(self) -> BaseAgent:
        return BaseAgent(name="t", role="r", tools=[read_file], max_turns=5)

    def test_memory_history_not_counted(self):
        """修复验证：记忆历史中的 AIMessage 不再计入 max_turns。

        旧行为：历史 8 条 AIMessage + 本轮 1 条 > 5 → 首轮即强制终止，
        启用记忆的 Agent 完全无法工作。
        """
        agent = self._agent()
        messages: list = []
        for i in range(8):  # 模拟记忆注入的历史对话
            messages.append(HumanMessage(content=f"旧输入 {i}"))
            messages.append(AIMessage(content=f"旧回复 {i}"))
        messages.append(HumanMessage(content="新任务"))
        messages.append(_tool_call_msg())

        assert agent.should_continue({"messages": messages}) == "tools"

    def test_max_turns_still_enforced_this_turn(self):
        """本轮 AIMessage 超限仍会被终止（保护本身不失效）。"""
        agent = self._agent()
        messages: list = [HumanMessage(content="任务")]
        for i in range(6):  # 本轮已经思考 6 轮 > max_turns=5
            messages.append(_tool_call_msg(call_id=f"c{i}"))
            messages.append(AIMessage(content=f"工具结果 {i}"))
        messages.append(_tool_call_msg(call_id="c_last"))

        assert agent.should_continue({"messages": messages}) == "__end__"

    def test_no_tools_always_ends(self):
        agent = BaseAgent(name="t", role="r", tools=[], max_turns=5)
        messages = [HumanMessage(content="hi"), AIMessage(content="答")]
        assert agent.should_continue({"messages": messages}) == "__end__"
