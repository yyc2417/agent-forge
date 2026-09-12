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
    - 隔离执行：每个任务用临时目录，工具沙箱（线程局部）把所有文件
      操作锚定到该目录，防止前一个任务的副作用影响后续
    - 超时控制：每个任务在 worker 线程中执行，超过 timeout（默认
      120 秒）放弃本次运行并继续下一任务；线程无法被强杀，卡死的
      调用（如 LLM 网络挂起）会残留为 daemon 线程，但不拖垮整轮
    - 不再使用 os.chdir：旧实现的进程级 chdir + 锁只能保护切换瞬间，
      任务执行期间并发 runner 仍会串目录；线程局部沙箱从根上消除
    - 可重复性：同一任务跑 3 次取中位数，消除 LLM 随机性
"""

import inspect
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

from agent_forge.agents import BaseAgent, CoderAgent, Orchestrator, ReviewerAgent
from agent_forge.bus import MessageBus
from agent_forge.cost import CostTracker
from agent_forge.tools import ALL_TOOLS
from agent_forge.tools.sandbox import clear_sandbox_root, set_sandbox_root
from agent_forge.utils import safe_print
from benchmark.judge import Judge
from benchmark.metrics import (
    MetricsCollector,
    TaskMetrics,
    aggregate_runs,
)
from benchmark.reporter import Reporter
from benchmark.tasks import TaskDefinition, load_all_tasks, load_quick_tasks

# Agent 工厂：按模式创建 Agent（测试可注入假 Agent，不发真实请求）
AgentFactory = Callable[[str, MessageBus, CostTracker], BaseAgent]


def _call_setup(fn: Callable, work_dir: Path) -> None:
    """调用任务 setup 函数，兼容无参与 (work_dir) 单参签名。

    推荐 (work_dir) 签名：setup 需要写文件时显式接收工作目录，
    而不是隐式依赖进程 cwd（runner 已不再 os.chdir）。
    """
    try:
        params = [
            p
            for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        params = []
    if len(params) >= 1:
        fn(work_dir)
    else:
        fn()


class BenchmarkRunner:
    """Benchmark 执行引擎。

    Attributes:
        runs: 每个任务的重复运行次数（取中位数）。
        timeout: 每个任务的默认超时时间（秒），task.timeout 优先。
        report_dir: 报告输出目录。
        agent_factory: Agent 工厂（mode, bus, cost_tracker) -> BaseAgent。
                       None 使用内置默认工厂。
    """

    def __init__(
        self,
        runs: int = 3,
        timeout: int = 120,
        report_dir: str = "benchmark/reports/latest",
        agent_factory: AgentFactory | None = None,
    ):
        self.runs = runs
        self.timeout = timeout
        self.report_dir = report_dir
        self._agent_factory = agent_factory

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

        if not tasks:
            safe_print("  [Runner] 警告: 没有可运行的任务（检查 difficulty_filter 拼写或任务目录），跳过")
            return [], [], Path(self.report_dir)

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
        """以指定模式运行任务 runs 次。

        单次运行的基础设施异常（临时目录创建失败等）只作废该次运行，
        不中断整轮——否则跑了数小时的任务集会因最后一个任务的偶发
        异常全部作废。
        """
        runs_metrics: list[TaskMetrics] = []

        for run_idx in range(self.runs):
            try:
                metrics = self._run_single(task, mode, run_idx)
            except Exception as e:
                safe_print(f"  [Runner] 运行异常: {type(e).__name__}: {e}")
                collector = MetricsCollector()
                collector.start_task(task.id, task.name, task.difficulty, mode, run_idx)
                metrics = collector.end_task(
                    "", None, None, False, [f"runner error: {type(e).__name__}: {e}"]
                )
            runs_metrics.append(metrics)

        return runs_metrics

    def _run_single(
        self,
        task: TaskDefinition,
        mode: str,
        run_index: int,
    ) -> TaskMetrics:
        """执行一次任务运行（worker 线程 + 超时保护）。

        执行模型：
        - setup / agent / judge / teardown 全部在 worker 线程中执行，
          线程内 set_sandbox_root(work_dir) 使所有文件工具锚定到本任务的
          临时目录（线程局部，天然并发安全，替代旧的进程级 os.chdir）
        - 主线程 join(timeout)；超时则记录失败并继续（worker 为 daemon，
          无法强杀，卡死的调用随进程退出回收）

        Args:
            task: 任务定义。
            mode: "single" 或 "multi"。
            run_index: 本次运行的序号。

        Returns:
            本次运行的 TaskMetrics。
        """
        collector = MetricsCollector()
        collector.start_task(task.id, task.name, task.difficulty, mode, run_index)

        work_dir = Path(tempfile.mkdtemp(prefix=f"af_bench_{task.id}_"))
        timeout = task.timeout or self.timeout

        outcome: dict = {
            "agent_output": "",
            "success": False,
            "errors": [],
            "cost_tracker": None,
            "bus": None,
        }

        def _worker() -> None:
            set_sandbox_root(work_dir)
            try:
                # setup（兼容无参与 (work_dir) 单参签名）
                if task.setup_fn:
                    try:
                        _call_setup(task.setup_fn, work_dir)
                    except Exception as e:
                        outcome["errors"].append(f"setup failed: {e}")
                        return

                # 每次运行独立的 Bus + CostTracker
                bus = MessageBus()
                cost_tracker = CostTracker()
                outcome["bus"] = bus
                outcome["cost_tracker"] = cost_tracker

                factory = self._agent_factory or self._default_agent_factory
                try:
                    agent = factory(mode, bus, cost_tracker)
                except Exception as e:
                    outcome["errors"].append(f"agent factory failed: {e}")
                    agent = None

                if agent is not None:
                    # 执行 Agent
                    try:
                        outcome["agent_output"] = agent.run(task.description)
                    except Exception as e:
                        outcome["errors"].append(f"{type(e).__name__}: {e}")

                    # Judge 评判（异常不再吞掉，进入 errors 便于归因）
                    try:
                        outcome["success"] = Judge.evaluate(
                            task, outcome["agent_output"], work_dir
                        )
                    except Exception as e:
                        outcome["errors"].append(f"judge error: {type(e).__name__}: {e}")

                # teardown
                if task.teardown_fn:
                    try:
                        task.teardown_fn()
                    except Exception as e:
                        outcome["errors"].append(f"teardown failed: {e}")
            except Exception as e:  # 兜底安全网：worker 内任何异常都进入 errors
                outcome["errors"].append(f"worker error: {type(e).__name__}: {e}")
            finally:
                clear_sandbox_root()

        worker = threading.Thread(
            target=_worker,
            daemon=True,
            name=f"af-bench-{task.id}-{mode}-{run_index}",
        )
        worker.start()
        worker.join(timeout)

        if worker.is_alive():
            outcome["errors"].append(f"task timeout after {timeout}s")
            outcome["success"] = False

        # 清理临时目录（worker 超时残留文件句柄时删除失败，目录留给系统清理）
        shutil.rmtree(work_dir, ignore_errors=True)

        return collector.end_task(
            outcome["agent_output"],
            outcome["cost_tracker"],
            outcome["bus"],
            outcome["success"],
            outcome["errors"],
        )

    def _default_agent_factory(
        self, mode: str, bus: MessageBus, cost_tracker: CostTracker
    ) -> BaseAgent:
        """默认 Agent 工厂：按模式创建单 Agent 或 Orchestrator。"""
        if mode == "single":
            return BaseAgent(
                name="solo",
                role="全能工程师",
                tools=ALL_TOOLS,
                bus=bus,
                cost_tracker=cost_tracker,
                max_turns=10,
            )
        coder = CoderAgent(bus=bus, cost_tracker=cost_tracker)
        reviewer = ReviewerAgent(bus=bus, cost_tracker=cost_tracker)
        return Orchestrator(
            specialists={"coder": coder, "reviewer": reviewer},
            bus=bus,
            cost_tracker=cost_tracker,
        )

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

        def _rate(success: int, total: int) -> str:
            return f"{success}/{total} ({success / total:.0%})" if total > 0 else "0/0"

        safe_print(f"\n{'═' * 60}")
        safe_print("  Benchmark 汇总")
        safe_print(f"{'═' * 60}")
        safe_print(f"  {'指标':<16} {'单Agent':>12} {'多Agent':>12}")
        safe_print(f"  {'─' * 16} {'─' * 12} {'─' * 12}")
        safe_print(
            f"  {'完成率':<14} {_rate(s_success, s_total):>12} "
            f"{_rate(m_success, m_total):>12}"
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
