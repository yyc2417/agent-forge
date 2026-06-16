"""Orchestrator 单元测试（包含真实 API 调用，标记为 slow）。"""

import pytest

from agent_forge.agents import CoderAgent, Orchestrator, ReviewerAgent


@pytest.mark.slow
class TestOrchestratorSlow:
    """需要真实 LLM API 的 Orchestrator 测试。"""

    def test_run_basic_task(self):
        coder = CoderAgent()
        reviewer = ReviewerAgent()
        orch = Orchestrator(
            specialists={"coder": coder, "reviewer": reviewer},
        )
        result = orch.run("写一个 Python 函数 add(a, b) 返回 a + b，写入 add.py")
        assert isinstance(result, str)
        assert len(result) > 0


class TestOrchestratorInit:
    """不需要 API 的 Orchestrator 初始化测试。"""

    def test_init(self):
        coder = CoderAgent()
        reviewer = ReviewerAgent()
        orch = Orchestrator(
            specialists={"coder": coder, "reviewer": reviewer},
        )
        assert orch.name == "orchestrator"
        assert "coder" in orch._specialists
        assert "reviewer" in orch._specialists

    def test_parse_plan_valid_json(self):
        orch = Orchestrator(specialists={"coder": CoderAgent()})
        plan = orch._parse_plan(
            '{"analysis": "test", "subtasks": [{"id": 1, "agent": "coder", "description": "do it"}]}'
        )
        assert len(plan) == 1
        assert plan[0]["agent_type"] == "coder"

    def test_parse_plan_with_markdown(self):
        orch = Orchestrator(specialists={"coder": CoderAgent()})
        plan = orch._parse_plan(
            '```json\n{"subtasks": [{"id": 1, "agent": "coder", "description": "task"}]}\n```'
        )
        assert len(plan) == 1

    def test_parse_plan_fallback(self):
        orch = Orchestrator(specialists={"coder": CoderAgent()})
        plan = orch._parse_plan("this is not valid json at all")
        assert len(plan) >= 1  # fallback 计划

    def test_parse_review_result_pass(self):
        orch = Orchestrator(specialists={"coder": CoderAgent()})
        assert orch._parse_review_result("【通过】代码质量良好") is True

    def test_parse_review_result_fail(self):
        orch = Orchestrator(specialists={"coder": CoderAgent()})
        assert orch._parse_review_result("【不通过】存在严重问题") is False
