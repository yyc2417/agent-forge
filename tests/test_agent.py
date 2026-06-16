"""BaseAgent 单元测试（包含真实 API 调用，标记为 slow）。"""

import pytest

from agent_forge.agents import BaseAgent
from agent_forge.tools import ALL_TOOLS


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
