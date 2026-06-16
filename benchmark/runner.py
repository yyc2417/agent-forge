"""Benchmark Runner —— 主执行引擎

遍历任务集，分别以单 Agent 和多 Agent 模式执行，
采集指标并生成对比报告。

执行流程：
    1. 加载所有 TaskDefinition
    2. 对每个任务执行 runs 次（默认 3 次取中位数）
    3. 每次运行：
       a. 创建临时工作目录（隔离执行）
       b. 创建独立的 Bus + CostTracker
       c. 运行 Agent（单/多模式）
       d. Judge 评判 + 采集指标
       e. 清理临时目录
    4. 聚合多次运行结果
    5. 生成 Markdown 报告

关键设计：
    - 隔离执行：每个任务用临时目录，防止前一个任务的副作用影响后续
    - 超时控制：每个任务 120 秒超时（可配置）
    - 可重复性：同一任务跑 3 次取中位数，消除 LLM 随机性
    - cwd 切换：用 threading.Lock 保护 os.chdir，任务结束后恢复
"""

import os
import shutil
import tempfile
import threading
from pathlib import Path

from agent_forge.agents import BaseAgent, CoderAgent, Orchestrator, ReviewerAgent
from agent_forge.bus import MessageBus
from agent_forge.cost import CostTracker
from agent_forge.tools import ALL_TOOLS
from agent_forge.utils import safe_print
from benchmark.judge import Judge
from benchmark.metrics import (
    MetricsCollector,
    TaskMetrics,
    aggregate_runs,
)
from benchmark.reporter import Reporter
from benchmark.tasks import TaskDefinition, load_all_tasks, load_quick_tasks

# cwd 切换锁（防止多线程竞争）
_cwd_lock = threading.Lock()


class BenchmarkRunner:
    """Benchmark 执行引擎。

    Attributes:
        runs: 每个任务的重复运行次数（取中位数）。
        timeout: 每个任务的超时时间（秒）。
        report_dir: 报告输出目录。
    """

    def __init__(
        self,
        runs: int = 3,
        timeout: int = 120,
        report_dir: str = "benchmark/reports/latest",
    ):
        self.runs = runs
        self.timeout = timeout
        self.report_dir = report_dir

    def run_all(
        self,
        tasks: list[TaskDefinition] | None = None,
    ) -> tuple[list[TaskMetrics], list[TaskMetrics], Path]:
        """运行所有任务并生成报告。

        Args:
            tasks: 要运行的任务列表。None 表示加载全部任务。

        Returns:
            (single_metrics, multi_metrics, report_path) 元组。
        """
        if tasks is None:
            tasks = load_all_tasks()

        safe_print(f"\n{'═' * 60}")
        safe_print(f"  AgentForge Benchmark — {len(tasks)} 个任务 × {self.runs} 次")
        safe_print(f"{'═' * 60}")

        all_single: list[TaskMetrics] = []
        all_multi: list[TaskMetrics] = []

        for i, task in enumerate(tasks):
            safe_print(f"\n[{i + 1}/{len(tasks)}] {task.id}: {task.name} ({task.difficulty})")

            # 单 Agent 模式
            single_runs = self._run_task_mode(task, "single")
            single_agg = aggregate_runs(single_runs)
            all_single.append(single_agg)
            safe_print(
                f"  单Agent: {'✅' if single_agg.success else '❌'} "
                f"{single_agg.wall_time_ms / 1000:.1f}s "
                f"{single_agg.total_tokens:,} tokens"
            )

            # 多 Agent 模式
            multi_runs = self._run_task_mode(task, "multi")
            multi_agg = aggregate_runs(multi_runs)
            all_multi.append(multi_agg)
            safe_print(
                f"  多Agent: {'✅' if multi_agg.success else '❌'} "
                f"{multi_agg.wall_time_ms / 1000:.1f}s "
                f"{multi_agg.total_tokens:,} tokens"
            )

        # 生成报告
        safe_print(f"\n{'─' * 60}")
        safe_print("  生成报告...")
        report_path = Reporter.generate(all_single, all_multi, self.report_dir)
        safe_print(f"  报告已保存: {report_path}")

        # 打印摘要
        self._print_summary(all_single, all_multi)

        return all_single, all_multi, report_path

    def _run_task_mode(
        self,
        task: TaskDefinition,
        mode: str,
    ) -> list[TaskMetrics]:
        """以指定模式运行任务 runs 次。"""
        runs_metrics: list[TaskMetrics] = []

        for run_idx in range(self.runs):
            metrics = self._run_single(task, mode, run_idx)
            runs_metrics.append(metrics)

        return runs_metrics

    def _run_single(
        self,
        task: TaskDefinition,
        mode: str,
        run_index: int,
    ) -> TaskMetrics:
        """执行一次任务运行。"""
        collector = MetricsCollector()
        collector.start_task(task.id, task.name, task.difficulty, mode, run_index)

        # 创建临时工作目录
        original_cwd = os.getcwd()
        work_dir = Path(tempfile.mkdtemp(prefix=f"af_bench_{task.id}_"))

        try:
            # 切换 cwd（线程安全）
            with _cwd_lock:
                os.chdir(work_dir)

            # setup
            if task.setup_fn:
                try:
                    task.setup_fn()
                except Exception as e:
                    return collector.end_task(
                        "", success=False, errors=[f"setup failed: {e}"]
                    )

            # 创建独立的 Bus + CostTracker
            bus = MessageBus()
            cost_tracker = CostTracker()

            # 执行 Agent
            agent_output = ""
            errors: list[str] = []

            try:
                if mode == "single":
                    agent_output = self._run_single_agent(
                        task, bus, cost_tracker
                    )
                else:
                    agent_output = self._run_multi_agent(
                        task, bus, cost_tracker
                    )
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")

            # Judge 评判
            success = False
            try:
                success = Judge.evaluate(task, agent_output, work_dir)
            except Exception as e:
                errors.append(f"judge error: {e}")

            # teardown
            if task.teardown_fn:
                try:
                    task.teardown_fn()
                except Exception:
                    pass

            return collector.end_task(
                agent_output, cost_tracker, bus, success, errors
            )

        finally:
            # 恢复 cwd + 清理临时目录
            with _cwd_lock:
                os.chdir(original_cwd)
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

    def _run_single_agent(
        self,
        task: TaskDefinition,
        bus: MessageBus,
        cost_tracker: CostTracker,
    ) -> str:
        """单 Agent 模式执行任务。"""
        agent = BaseAgent(
            name="solo",
            role="全能工程师",
            tools=ALL_TOOLS,
            bus=bus,
            cost_tracker=cost_tracker,
            max_turns=10,
        )
        return agent.run(task.description)

    def _run_multi_agent(
        self,
        task: TaskDefinition,
        bus: MessageBus,
        cost_tracker: CostTracker,
    ) -> str:
        """多 Agent 模式执行任务。"""
        coder = CoderAgent(bus=bus, cost_tracker=cost_tracker)
        reviewer = ReviewerAgent(bus=bus, cost_tracker=cost_tracker)
        orchestrator = Orchestrator(
            specialists={"coder": coder, "reviewer": reviewer},
            bus=bus,
            cost_tracker=cost_tracker,
        )
        return orchestrator.run(task.description)

    def _print_summary(
        self,
        single_metrics: list[TaskMetrics],
        multi_metrics: list[TaskMetrics],
    ) -> None:
        """打印汇总统计。"""
        s_total = len(single_metrics)
        m_total = len(multi_metrics)
        s_success = sum(1 for m in single_metrics if m.success)
        m_success = sum(1 for m in multi_metrics if m.success)

        s_avg_time = (
            sum(m.wall_time_ms for m in single_metrics) / s_total / 1000
            if s_total > 0 else 0
        )
        m_avg_time = (
            sum(m.wall_time_ms for m in multi_metrics) / m_total / 1000
            if m_total > 0 else 0
        )

        safe_print(f"\n{'═' * 60}")
        safe_print("  Benchmark 汇总")
        safe_print(f"{'═' * 60}")
        safe_print(f"  {'指标':<16} {'单Agent':>12} {'多Agent':>12}")
        safe_print(f"  {'─' * 16} {'─' * 12} {'─' * 12}")
        safe_print(
            f"  {'完成率':<14} {s_success}/{s_total} ({s_success / s_total:.0%}) "
            f"{m_success}/{m_total} ({m_success / m_total:.0%})"
        )
        safe_print(
            f"  {'平均耗时':<12} {s_avg_time:.1f}s {m_avg_time:.1f}s"
        )

        s_avg_tok = (
            sum(m.total_tokens for m in single_metrics) / s_total
            if s_total > 0 else 0
        )
        m_avg_tok = (
            sum(m.total_tokens for m in multi_metrics) / m_total
            if m_total > 0 else 0
        )
        safe_print(
            f"  {'平均Token':<12} {s_avg_tok:,.0f} {m_avg_tok:,.0f}"
        )
        safe_print(f"{'═' * 60}")


def run_benchmark(
    quick: bool = False,
    runs: int = 3,
    timeout: int = 120,
    difficulty: str | None = None,
) -> tuple[list[TaskMetrics], list[TaskMetrics], Path]:
    """便捷入口函数：运行 Benchmark。

    Args:
        quick: 是否使用快速模式（只跑前 5 个 easy 任务，1 次）。
        runs: 每个任务的重复次数。
        timeout: 超时时间（秒）。
        difficulty: 按难度过滤。

    Returns:
        (single_metrics, multi_metrics, report_path) 元组。
    """
    runner = BenchmarkRunner(runs=runs, timeout=timeout)

    if quick:
        tasks = load_quick_tasks(count=5)
        runner.runs = 1  # 快速模式只跑 1 次
    else:
        tasks = load_all_tasks(difficulty_filter=difficulty)

    return runner.run_all(tasks)
