"""Orchestrator 单元测试（包含真实 API 调用，标记为 slow）。"""

import pytest
from langchain_core.messages import AIMessage

from agent_forge.agents import CoderAgent, Orchestrator, ReviewerAgent
from tests.fakes import FakeToolCallingLLM


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

    def test_parse_review_result_negative_variants_fail(self):
        """修复验证：否定变体不再被误判为通过。

        旧的 `"通过" in and "不通过" not in` 判定会把含"通过"字样
        但不含【不通过】标记的文本误判为 PASS。
        """
        orch = Orchestrator(specialists={"coder": CoderAgent()})
        assert orch._parse_review_result("未通过编译，存在语法错误") is False
        assert orch._parse_review_result("无法通过审查") is False
        assert orch._parse_review_result("代码不完整") is False
        assert orch._parse_review_result("") is False


# ─── 状态模型：plan 单一事实源 ────────────────────────────

class _StubAgent:
    """鸭子类型的假 Specialist：记录调用、返回预置产出。"""

    def __init__(self, name: str = "coder", outputs: list | None = None):
        self.name = name
        self.role = "测试角色"
        self._outputs = list(outputs or [])
        self.calls: list[str] = []

    def run(self, task: str) -> str:
        self.calls.append(task)
        return self._outputs.pop(0) if self._outputs else "默认产出"


def _make_orch(outputs: list) -> tuple[Orchestrator, _StubAgent]:
    stub = _StubAgent(name="coder", outputs=outputs)
    return Orchestrator(specialists={"coder": stub}), stub


def _run_two_steps(orch: Orchestrator, stub: _StubAgent) -> dict:
    """驱动 _execute_node 执行两步 coder 计划。"""
    state = {
        "task": "写函数",
        "plan": [
            {"id": 1, "agent_type": "coder", "description": "编码",
             "status": "pending", "result": ""},
            {"id": 2, "agent_type": "coder", "description": "修复",
             "status": "pending", "result": ""},
        ],
        "current_step": 0,
        "retry_count": 0,
    }
    for _ in range(2):
        state.update(orch._execute_node(state))
    return state


class TestPlanAsSourceOfTruth:
    """plan 是唯一事实源：同类多步骤产出不再互相覆盖。"""

    def test_two_coder_steps_both_preserved(self):
        """修复验证：旧版 results[agent_type] 会用第二步覆盖第一步。"""
        orch, stub = _make_orch(["第一次产出", "第二次产出"])
        state = _run_two_steps(orch, stub)
        plan = state["plan"]
        assert plan[0]["result"] == "第一次产出"
        assert plan[1]["result"] == "第二次产出"
        assert plan[0]["status"] == "done" and plan[1]["status"] == "done"

    def test_aggregate_shows_all_steps(self):
        orch, stub = _make_orch(["第一次产出", "第二次产出"])
        state = _run_two_steps(orch, stub)
        final = orch._aggregate_node(state)["final_output"]
        assert "第一次产出" in final
        assert "第二次产出" in final
        assert "步骤 1" in final and "步骤 2" in final

    def test_context_includes_same_type_prior_step(self):
        """修复验证：coder 第 2 步能看到第 1 步的产出（旧版排除同类型）。"""
        orch, stub = _make_orch(["print('hello')", "修复后的代码"])
        state = _run_two_steps(orch, stub)
        context = orch._build_context(state["plan"][1], state["plan"], 1)
        assert "print('hello')" in context
        # 分发任务时上下文包含前序产出
        assert "print('hello')" in stub.calls[1]

    def test_unknown_agent_marks_error(self):
        orch, _ = _make_orch(["x"])
        state = {
            "task": "t",
            "plan": [{"id": 1, "agent_type": "ghost", "description": "?",
                      "status": "pending", "result": ""}],
            "current_step": 0,
            "retry_count": 0,
        }
        state.update(orch._execute_node(state))
        assert state["plan"][0]["status"] == "error"
        assert "未知 Agent 类型" in state["plan"][0]["result"]

    def test_reviewer_step_skipped_not_double_called(self):
        """修复验证：plan 中的 reviewer 步骤不再真正调用 reviewer
        （审查由 review 节点统一执行，避免每轮两次调用）。"""
        reviewer = _StubAgent(name="reviewer", outputs=["【通过】"])
        orch = Orchestrator(specialists={"reviewer": reviewer})
        state = {
            "task": "t",
            "plan": [{"id": 1, "agent_type": "reviewer", "description": "审查",
                      "status": "pending", "result": ""}],
            "current_step": 0,
            "retry_count": 0,
        }
        state.update(orch._execute_node(state))
        assert reviewer.calls == []  # 未被调用
        assert state["plan"][0]["status"] == "done"

    def test_fallback_plan_has_no_reviewer(self):
        """修复验证：兜底计划只含 coder（审查交给审查门）。"""
        orch = Orchestrator(specialists={"coder": _StubAgent()})
        plan = orch._fallback_plan("任务")
        assert len(plan) == 1
        assert plan[0]["agent_type"] == "coder"


class TestDecomposeObservability:
    """拆解调用接入 hooks 与 cost_tracker（旧版绕过导致少算成本）。"""

    def test_decompose_triggers_hooks_and_records_cost(self):
        hooks_kwargs: list[tuple] = []

        class _Hooks:
            def trigger(self, event, **kw):
                hooks_kwargs.append((event, kw))

        class _Cost:
            def __init__(self):
                self.records = []

            def record(self, agent_name, prompt_tokens=0, completion_tokens=0):
                self.records.append((agent_name, prompt_tokens, completion_tokens))

        fake_llm = FakeToolCallingLLM(responses=[
            AIMessage(
                content='{"analysis": "a", "subtasks": '
                        '[{"id": 1, "agent": "coder", "description": "d"}]}',
                response_metadata={"token_usage": {
                    "prompt_tokens": 10, "completion_tokens": 5,
                }},
            ),
        ])
        orch = Orchestrator(
            specialists={"coder": _StubAgent()},
            llm=fake_llm,
            hooks=_Hooks(),
            cost_tracker=_Cost(),
        )
        state = {"task": "写一个函数"}
        out = orch._decompose_node(state)

        assert out["plan"][0]["agent_type"] == "coder"
        events = [e for e, _ in hooks_kwargs]
        assert "pre_llm_call" in events and "post_llm_call" in events
        cost = orch._cost_tracker
        assert cost.records and cost.records[0][0] == "orchestrator"
        assert cost.records[0][1] == 10 and cost.records[0][2] == 5


# ─── 复杂度门控：simple 单步任务免审查（快速路径）──────────

class TestComplexityGate:
    """complexity=single-step 快速路径：缺失/多步一律保守走审查。"""

    @staticmethod
    def _review_state(complexity, steps=1):
        return {
            "task": "创建文件 hello.py",
            "complexity": complexity,
            "retry_count": 0,
            "plan": [
                {"id": i + 1, "agent_type": "coder", "description": "编码",
                 "status": "done", "result": f"print(1)  # 第{i + 1}步"}
                for i in range(steps)
            ],
        }

    def test_parse_complexity_simple(self):
        orch = Orchestrator(specialists={"coder": _StubAgent()})
        assert orch._parse_complexity('{"complexity": "simple", "subtasks": []}') == "simple"

    def test_parse_complexity_defaults_to_complex(self):
        """缺失 / 非法 JSON / 非 simple 值 → 保守按 complex。"""
        orch = Orchestrator(specialists={"coder": _StubAgent()})
        assert orch._parse_complexity('{"subtasks": []}') == "complex"
        assert orch._parse_complexity('{"complexity": " SIMPLE "}') == "complex"
        assert orch._parse_complexity("这不是 JSON") == "complex"
        assert orch._parse_complexity("") == "complex"

    def test_simple_single_step_skips_review(self):
        reviewer = _StubAgent(name="reviewer", outputs=["【通过】"])
        orch = Orchestrator(specialists={"coder": _StubAgent(),
                                         "reviewer": reviewer})
        out = orch._review_node(self._review_state("simple", steps=1))
        assert out["review_passed"] is True
        assert reviewer.calls == []  # 审查未被调用

    def test_simple_multi_step_still_reviews(self):
        """标 simple 但计划多步 → 保守走完整审查（防绕过质量门）。"""
        reviewer = _StubAgent(name="reviewer", outputs=["【通过】"])
        orch = Orchestrator(specialists={"coder": _StubAgent(),
                                         "reviewer": reviewer})
        out = orch._review_node(self._review_state("simple", steps=2))
        assert out["review_passed"] is True
        assert len(reviewer.calls) == 1  # 审查被调用

    def test_missing_complexity_reviews(self):
        reviewer = _StubAgent(name="reviewer", outputs=["【通过】"])
        orch = Orchestrator(specialists={"coder": _StubAgent(),
                                         "reviewer": reviewer})
        out = orch._review_node(self._review_state(None, steps=1))
        assert out["review_passed"] is True
        assert len(reviewer.calls) == 1

    def test_decompose_propagates_complexity(self):
        """拆解节点把 LLM 输出的 complexity 写入状态。"""
        fake_llm = FakeToolCallingLLM(responses=[
            AIMessage(content='{"analysis": "a", "complexity": "simple", '
                              '"subtasks": [{"id": 1, "agent": "coder", '
                              '"description": "d"}]}'),
        ])
        orch = Orchestrator(specialists={"coder": _StubAgent()}, llm=fake_llm)
        out = orch._decompose_node({"task": "写一个函数"})
        assert out["complexity"] == "simple"
        assert len(out["plan"]) == 1


# ─── 审查交接：Reviewer 读真实文件而非截断文本 ────────────

class TestReviewHandoff:
    """_call_reviewer 交接改造：完整产出 + 文件路径 + 读取指令。"""

    def test_extract_artifact_paths_dedup_and_order(self):
        orch = Orchestrator(specialists={"coder": _StubAgent()})
        output = (
            "先写 src/utils.py，然后更新 src/utils.py 的测试 "
            "tests/test_utils.py，配置见 config.json"
        )
        assert orch._extract_artifact_paths(output) == [
            "src/utils.py", "tests/test_utils.py", "config.json",
        ]

    def test_extract_artifact_paths_cap_at_8(self):
        orch = Orchestrator(specialists={"coder": _StubAgent()})
        output = " ".join(f"f{i}.py" for i in range(20))
        assert len(orch._extract_artifact_paths(output)) == 8

    def test_call_reviewer_prompt_has_paths_and_full_output(self):
        """prompt 必须含文件路径、读取指令，且产出不再截断到 2000。"""
        reviewer = _StubAgent(name="reviewer", outputs=["【通过】"])
        orch = Orchestrator(specialists={"coder": reviewer})
        long_output = "写入 safe_divide.py\n" + "x = 1\n" * 1300 + "TAIL_MARKER_超出旧版2000截断"
        review = orch._call_reviewer(reviewer, "实现安全除法", long_output)

        assert review == "【通过】"
        prompt = reviewer.calls[0]
        assert "safe_divide.py" in prompt
        assert "read_file" in prompt
        # 旧版 [:2000] 会截掉的尾部，现在保留
        assert "TAIL_MARKER_超出旧版2000截断" in prompt
