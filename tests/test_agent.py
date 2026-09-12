"""BaseAgent 单元测试（包含真实 API 调用，标记为 slow）。"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from agent_forge.agents import BaseAgent
from agent_forge.tools import ALL_TOOLS, read_file
from tests.fakes import FakeToolCallingLLM


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


# ─── 死循环兜底四件套（阶段 6，全部使用假 LLM，无真实 API 调用）──────


def _tc(name: str = "read_file", path: str = "a.py", call_id: str = "c1") -> AIMessage:
    """构造一条带工具调用的 AIMessage。"""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"path": path}, "id": call_id}],
    )


class TestLoopDetection:
    """循环检测：相同 (工具, 参数) 连续 3 次被拦截。"""

    def _agent(self, responses, max_turns: int = 8) -> BaseAgent:
        return BaseAgent(
            name="t", role="r", tools=[read_file],
            llm=FakeToolCallingLLM(responses=responses),
            max_turns=max_turns,
        )

    def test_identical_calls_blocked_third_time(self):
        agent = self._agent([
            _tc("read_file", "x.py", "c1"),
            _tc("read_file", "x.py", "c2"),
            _tc("read_file", "x.py", "c3"),
            AIMessage(content="换了个方法完成了"),
        ])
        result = agent.run("任务")
        assert result == "换了个方法完成了"
        assert agent._loop_blocks == 1

    def test_persistent_loop_terminates_with_fallback(self):
        """连续拦截 2 轮后强制终止并返回兜底输出。"""
        agent = self._agent([_tc("read_file", "x.py", f"c{i}") for i in range(4)])
        result = agent.run("任务")
        assert "任务未完全完成" in result
        assert "重复工具调用" in result
        assert agent._terminated_reason == "tool_loop"

    def test_different_args_not_blocked(self):
        agent = self._agent([
            _tc("read_file", "a.py", "c1"),
            _tc("read_file", "b.py", "c2"),
            AIMessage(content="done"),
        ])
        result = agent.run("任务")
        assert result == "done"
        assert agent._loop_blocks == 0


class TestFailureCircuitBreaker:
    """连续失败熔断（轻量）：工具连续抛异常 3 次 → 终止 + 兜底输出。"""

    def test_consecutive_tool_failures_abort(self):
        @tool
        def boom(attempt: int = 0) -> str:
            """总是抛异常的测试工具（参数可变，避免触发循环检测）。"""
            raise RuntimeError(f"x{attempt}")

        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "boom", "args": {"attempt": i}, "id": f"c{i}"}],
            )
            for i in range(4)
        ]
        agent = BaseAgent(
            name="t", role="r", tools=[boom],
            llm=FakeToolCallingLLM(responses=responses),
            max_turns=10,
        )
        result = agent.run("任务")
        assert "任务未完全完成" in result
        assert "连续多次执行失败" in result
        assert agent._terminated_reason == "consecutive_failures"

    def test_llm_error_returns_fallback(self):
        class _ExplodingLLM(FakeToolCallingLLM):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                raise RuntimeError("api down")

        agent = BaseAgent(
            name="t", role="r", tools=[],
            llm=_ExplodingLLM(responses=[]),
            max_turns=3,
        )
        result = agent.run("任务")
        assert "任务未完全完成" in result
        assert "LLM 调用失败" in result


class TestMaxTurnsFallback:
    """max_turns 触发后返回结构化兜底输出（旧版静默返回空/半截内容）。"""

    def test_max_turns_returns_fallback(self):
        responses = [_tc("read_file", "x.py", f"c{i}") for i in range(5)]
        agent = BaseAgent(
            name="t", role="r", tools=[read_file],
            llm=FakeToolCallingLLM(responses=responses),
            max_turns=1,
        )
        result = agent.run("任务")
        assert "任务未完全完成" in result
        assert "思考轮数上限" in result
        assert agent._terminated_reason == "max_turns"

    def test_normal_completion_no_fallback(self):
        agent = BaseAgent(
            name="t", role="r", tools=[read_file],
            llm=FakeToolCallingLLM(responses=[AIMessage(content="正常答复")]),
            max_turns=3,
        )
        result = agent.run("任务")
        assert result == "正常答复"
        assert agent._terminated_reason == ""
