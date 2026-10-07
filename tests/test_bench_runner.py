"""Benchmark runner / judge 单元测试（fake agent，不发真实 LLM 请求）。"""

import re
import time
from pathlib import Path

from agent_forge.bus import MessageBus
from agent_forge.cost import CostTracker
from benchmark.judge import Judge
from benchmark.runner import BenchmarkRunner
from benchmark.tasks import TaskDefinition


def _make_task(**overrides) -> TaskDefinition:
    defaults = dict(
        id="test-01",
        name="测试任务",
        description="做一个测试",
        difficulty="easy",
        judge_config={"type": "contains", "values": ["DONE"]},
    )
    defaults.update(overrides)
    return TaskDefinition(**defaults)


def _fake_factory(output: str = "DONE 一切正常"):
    """返回一个固定输出的假 agent 工厂。"""
    class _FakeAgent:
        name = "fake"

        def run(self, task: str) -> str:
            return output

    def factory(mode: str, bus: MessageBus, cost: CostTracker):
        return _FakeAgent()

    return factory


class TestRunnerTimeout:
    """任务级超时（P1 修复验证：timeout 参数曾经完全未实现）。"""

    def test_timeout_records_error_and_continues(self, tmp_path):
        def slow_setup():
            time.sleep(2)

        task = _make_task(setup_fn=slow_setup, timeout=1)
        # 注入 fake 工厂：超时后的孤儿线程不会发起真实 LLM 调用
        runner = BenchmarkRunner(runs=1, timeout=1, report_dir=str(tmp_path),
                                 agent_factory=_fake_factory())
        metrics = runner._run_single(task, "single", 0)

        assert metrics.success is False
        assert any("task timeout after 1s" in e for e in metrics.errors)

    def test_fast_task_not_affected(self, tmp_path):
        task = _make_task()
        runner = BenchmarkRunner(runs=1, timeout=5,
                                 report_dir=str(tmp_path),
                                 agent_factory=_fake_factory())
        metrics = runner._run_single(task, "single", 0)
        assert metrics.success is True
        assert metrics.errors == []


class TestRunnerRobustness:
    """单任务失败不拖垮整轮 + judge 错误可归因。"""

    def test_factory_error_recorded(self, tmp_path):
        """工厂异常进入 errors（不再无声消失在 worker 线程里）。"""
        def bad_factory(mode, bus, cost):
            raise RuntimeError("boom")

        task = _make_task()
        runner = BenchmarkRunner(runs=1, report_dir=str(tmp_path),
                                 agent_factory=bad_factory)
        metrics = runner._run_single(task, "single", 0)
        assert metrics.success is False
        assert any("agent factory failed" in e for e in metrics.errors)

    def test_judge_exception_attributed(self, tmp_path):
        """修复验证：judge 自身异常不再被 catch-all 吞掉。"""
        def bad_judge(output, work_dir):
            raise ValueError("judge bug")

        task = _make_task(judge_config={"type": "custom"}, judge_fn=bad_judge)
        runner = BenchmarkRunner(runs=1, report_dir=str(tmp_path),
                                 agent_factory=_fake_factory())
        metrics = runner._run_single(task, "single", 0)
        assert metrics.success is False
        assert any("judge error" in e and "ValueError" in e for e in metrics.errors)

    def test_run_all_survives_per_run_failure(self, tmp_path):
        """单次运行异常不中断整轮，报告仍会生成。"""
        task = _make_task()
        runner = BenchmarkRunner(runs=2, timeout=10, report_dir=str(tmp_path),
                                 agent_factory=_fake_factory())
        _, _, report_path = runner.run_all([task])
        assert Path(report_path).exists()

    def test_run_all_empty_tasks(self, tmp_path):
        runner = BenchmarkRunner(report_dir=str(tmp_path))
        single, multi, path = runner.run_all([])
        assert single == [] and multi == []


class TestJudge:
    """Judge 评判语义。"""

    def test_file_exists_empty_config_is_false(self, tmp_path):
        """修复验证：空 files 配置不再恒为 True。"""
        task = _make_task(judge_config={"type": "file_exists"})
        assert Judge.evaluate(task, "x", tmp_path) is False

    def test_file_exists_with_file(self, tmp_path):
        (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
        task = _make_task(judge_config={"type": "file_exists", "file": "a.txt"})
        assert Judge.evaluate(task, "x", tmp_path) is True

    def test_regex_compile_error_raises(self, tmp_path):
        """坏正则抛异常（由 runner 归因），而非静默 False。"""
        task = _make_task(judge_config={"type": "regex", "pattern": "([bad"})
        try:
            Judge.evaluate(task, "x", tmp_path)
            raised = False
        except re.error:
            raised = True
        assert raised

    def test_custom_judge_two_arg_signature(self, tmp_path):
        def judge2(output: str, work_dir: Path) -> bool:
            return (work_dir / "f.txt").exists() and "DONE" in output

        (tmp_path / "f.txt").write_text("x", encoding="utf-8")
        task = _make_task(judge_fn=judge2)
        assert Judge.evaluate(task, "DONE", tmp_path) is True

    def test_custom_judge_one_arg_signature_still_works(self, tmp_path):
        def judge1(output: str) -> bool:
            return "DONE" in output

        task = _make_task(judge_fn=judge1)
        assert Judge.evaluate(task, "DONE", tmp_path) is True


class TestTaskFixes:
    """easy-03 恒真 judge 与 hard 任务可满足性修复。"""

    def test_easy_03_setup_and_judge(self, tmp_path):
        from benchmark.tasks.easy import task_03_file_count as t3

        t3.setup(tmp_path)
        actual = len(list(tmp_path.glob("*.py")))
        assert actual == 7
        # 输出中的数字必须等于真实文件数
        assert t3.judge("当前目录共有 7 个 .py 文件", tmp_path) is True
        # 旧版 regex \d+ 下恒为真的噪音输出，现在判失败
        assert t3.judge("运行环境是 Python 3.11， Everything 正常", tmp_path) is False
        assert t3.judge("数出来是 5 个", tmp_path) is False

    def test_hard_02_setup_copies_cost_py(self, tmp_path):
        from benchmark.tasks.hard import task_02_enhanced_cost as t2

        t2.setup(tmp_path)
        assert (tmp_path / "cost.py").exists()

    def test_hard_04_setup_creates_project_tree(self, tmp_path):
        """修复验证：hard-04 描述要求分析 agent_forge/ 目录，setup 必须先构造它。"""
        from benchmark.tasks.hard import task_04_project_report as t4

        t4.setup(tmp_path)
        # 样例项目的 agent_forge/ 树存在，任务才可满足
        assert (tmp_path / "agent_forge" / "agents" / "base.py").exists()
        assert len(list(tmp_path.rglob("*.py"))) > 0
        # 任务级超时已放宽（120s 默认预算下双模式均超时）
        assert t4.TASK["timeout"] == 240
        # judge 对满足条件的合成报告通过，对缺失/空报告拒绝
        report = tmp_path / "code_stats_report.md"
        report.write_text(
            "# 代码统计报告\n\n共 5 个文件，base.py 7 行，2 个类，3 个函数。\n",
            encoding="utf-8",
        )
        assert t4.judge("", tmp_path) is True

        # 报告缺失 → 失败分支
        report.unlink()
        assert t4.judge("", tmp_path) is False

    def test_medium_07_judge_accepts_flexible_formats(self, tmp_path):
        """修复验证：medium-07 改期望值 custom judge，替代格式敏感的 regex。"""
        from benchmark.tasks.medium import task_07_shell_pipeline as t7

        t7.setup(tmp_path)
        top5 = t7._expected_top5(tmp_path)
        assert len(top5) == 5

        # 期望值即真实行数，可反推每个文件的"文件名+行数"输出行
        def _entry(i, template):
            name, counts = top5[i]
            return template.format(name=name, count=max(counts))

        # 三种常见表述混合：`7 base.py` / `specialists.py: 9` / `file_tools.py（11 行）`
        ok_output = "\n".join([
            "行数最多的 5 个文件：",
            _entry(0, "{count} {name}"),
            _entry(1, "{name}: {count}"),
            _entry(2, "{name}（{count} 行）"),
            _entry(3, "{name} - {count} lines"),
            _entry(4, "{count:<6}{name}"),
        ])
        assert t7.judge(ok_output, tmp_path) is True
        assert t7.TASK["judge"]["type"] == "custom"

        # 行数错误（数字被错误计数污染）→ 失败
        name0, _ = top5[0]
        wrong = ok_output.replace(f"{max(top5[0][1])} {name0}", f"999 {name0}")
        assert t7.judge(wrong, tmp_path) is False

        # 漏报任一文件 → 失败
        missing_one = "\n".join(ok_output.splitlines()[:-1])
        assert t7.judge(missing_one, tmp_path) is False

        # 空输出 → 失败
        assert t7.judge("", tmp_path) is False

    def test_hard_01_judge_rejects_broken_syntax(self, tmp_path):
        """修复验证：hard-01 现在真的 import 验证（docstring 与实现一致）。"""
        from benchmark.tasks.hard import task_01_stack_class as t1

        good = tmp_path / "stack.py"
        good.write_text(
            "class Stack:\n"
            "    def push(self, item): pass\n"
            "    def pop(self): pass\n"
            "    def peek(self): pass\n"
            "    def is_empty(self): pass\n"
            "    def __len__(self): return 0\n",
            encoding="utf-8",
        )
        assert t1.judge("", tmp_path) is True

        # 子串检查骗得过（方法名都在注释里），import 验证骗不过
        broken = tmp_path / "stack.py"
        broken.write_text(
            "# def push\n# def pop\n# def peek\n# def is_empty\n"
            "# def __len__\nclass Stack\n    <<<语法错误>>>\n",
            encoding="utf-8",
        )
        assert t1.judge("", tmp_path) is False
