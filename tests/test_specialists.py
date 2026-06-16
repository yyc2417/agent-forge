"""Specialist Agents 单元测试（不依赖 LLM API）。"""

from agent_forge.agents import AnalystAgent, CoderAgent, ReviewerAgent, WriterAgent


class TestCoderAgent:
    def test_name_and_role(self):
        agent = CoderAgent()
        assert agent.name == "coder"
        assert "工程师" in agent.role or "编码" in agent.role

    def test_tools(self):
        agent = CoderAgent()
        tool_names = [t.name for t in agent._tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "run_shell" in tool_names

    def test_system_prompt(self):
        agent = CoderAgent()
        prompt = agent.get_system_prompt()
        assert "编码" in prompt or "代码" in prompt


class TestReviewerAgent:
    def test_name_and_role(self):
        agent = ReviewerAgent()
        assert agent.name == "reviewer"
        assert "审查" in agent.role

    def test_tools_read_only(self):
        agent = ReviewerAgent()
        tool_names = [t.name for t in agent._tools]
        assert "read_file" in tool_names
        assert "write_file" not in tool_names
        assert "run_shell" not in tool_names

    def test_system_prompt_contains_pass_fail(self):
        agent = ReviewerAgent()
        prompt = agent.get_system_prompt()
        assert "通过" in prompt
        assert "不通过" in prompt


class TestAnalystAgent:
    def test_name_and_role(self):
        agent = AnalystAgent()
        assert agent.name == "analyst"
        assert "分析" in agent.role

    def test_tools(self):
        agent = AnalystAgent()
        tool_names = [t.name for t in agent._tools]
        assert "read_file" in tool_names
        assert "grep_search" in tool_names


class TestWriterAgent:
    def test_name_and_role(self):
        agent = WriterAgent()
        assert agent.name == "writer"
        assert "文档" in agent.role or "报告" in agent.role

    def test_tools(self):
        agent = WriterAgent()
        tool_names = [t.name for t in agent._tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "run_shell" not in tool_names
