"""Benchmark 指标采集器

采集每个任务执行的详细指标：耗时、token、成功/失败、消息数等。
支持单 Agent 和多 Agent 两种模式的指标采集。

核心数据类：
- TaskMetrics: 单次任务执行的指标快照
- BenchmarkSummary: 多个任务的汇总统计

采集来源：
- wall_time: time.time() 计时
- tokens: CostTracker.get_summary()
- messages: MessageBus.get_history()
- success: Judge.evaluate()
"""

import time
from dataclasses import dataclass, field
from statistics import median

from agent_forge.bus import MessageBus
from agent_forge.cost import CostTracker


@dataclass
class TaskMetrics:
    """单次任务执行的指标快照。

    Attributes:
        task_id: 任务 ID（如 "easy-01"）。
        task_name: 任务名称。
        difficulty: 难度级别。
        mode: 执行模式（"single" 或 "multi"）。
        run_index: 第几次运行（0-based）。
        success: 任务是否成功。
        wall_time_ms: 墙钟时间（毫秒）。
        total_tokens: 总 token 消耗。
        llm_calls: LLM 调用次数。
        agent_count: 参与的 Agent 数量。
        messages_exchanged: Agent 间消息数。
        output: Agent 的最终输出内容。
        errors: 执行过程中的错误列表。
    """
    task_id: str
    task_name: str
    difficulty: str
    mode: str
    run_index: int = 0
    success: bool = False
    wall_time_ms: float = 0.0
    total_tokens: int = 0
    llm_calls: int = 0
    agent_count: int = 1
    messages_exchanged: int = 0
    output: str = ""
    errors: list[str] = field(default_factory=list)


class MetricsCollector:
    """指标采集器 —— 在任务执行过程中采集指标。

    使用方式：
        collector = MetricsCollector()
        collector.start_task("easy-01", "创建文件", "easy", "single", 0)
        # ... 执行任务 ...
        metrics = collector.end_task(agent_output, cost_tracker, bus, success)
    """

    def __init__(self):
        self._start_time: float = 0.0
        self._task_id: str = ""
        self._task_name: str = ""
        self._difficulty: str = ""
        self._mode: str = ""
        self._run_index: int = 0

    def start_task(
        self,
        task_id: str,
        task_name: str,
        difficulty: str,
        mode: str,
        run_index: int,
    ) -> None:
        """开始计时并记录任务信息。"""
        self._task_id = task_id
        self._task_name = task_name
        self._difficulty = difficulty
        self._mode = mode
        self._run_index = run_index
        self._start_time = time.time()

    def end_task(
        self,
        agent_output: str,
        cost_tracker: CostTracker | None = None,
        bus: MessageBus | None = None,
        success: bool = False,
        errors: list[str] | None = None,
    ) -> TaskMetrics:
        """结束计时并返回指标。

        Args:
            agent_output: Agent 的最终输出。
            cost_tracker: CostTracker 实例（提取 token 数据）。
            bus: MessageBus 实例（提取消息数）。
            success: 任务是否成功。
            errors: 错误列表。

        Returns:
            TaskMetrics 实例。
        """
        wall_time_ms = (time.time() - self._start_time) * 1000

        # 从 CostTracker 提取 token 数据
        total_tokens = 0
        llm_calls = 0
        if cost_tracker:
            total_tokens = cost_tracker.get_total_tokens()
            summary = cost_tracker.get_summary()
            llm_calls = sum(s["calls"] for s in summary.values())

        # 从 Bus 提取消息数（limit=None 表示不限制条数）
        messages_exchanged = 0
        if bus:
            messages_exchanged = len(bus.get_history(limit=None))

        return TaskMetrics(
            task_id=self._task_id,
            task_name=self._task_name,
            difficulty=self._difficulty,
            mode=self._mode,
            run_index=self._run_index,
            success=success,
            wall_time_ms=wall_time_ms,
            total_tokens=total_tokens,
            llm_calls=llm_calls,
            agent_count=len(cost_tracker.get_summary()) if cost_tracker else 1,
            messages_exchanged=messages_exchanged,
            output=agent_output[:500] if agent_output else "",
            errors=errors or [],
        )


def aggregate_runs(runs: list[TaskMetrics]) -> TaskMetrics:
    """将同一任务的多次运行聚合为一条指标（取中位数）。

    成功判定用多数投票：超过半数成功则判定成功。
    wall_time 和 total_tokens 取中位数。

    Args:
        runs: 同一任务的多次运行指标。

    Returns:
        聚合后的 TaskMetrics。
    """
    if not runs:
        raise ValueError("runs 不能为空")

    if len(runs) == 1:
        return runs[0]

    # 成功用多数投票
    success_count = sum(1 for r in runs if r.success)
    majority_success = success_count > len(runs) / 2

    # 数值取中位数
    wall_times = [r.wall_time_ms for r in runs]
    token_counts = [r.total_tokens for r in runs]
    llm_call_counts = [r.llm_calls for r in runs]

    # 使用成功运行的输出（如果有的话）
    successful_runs = [r for r in runs if r.success]
    best_output = successful_runs[0].output if successful_runs else runs[0].output

    base = runs[0]
    return TaskMetrics(
        task_id=base.task_id,
        task_name=base.task_name,
        difficulty=base.difficulty,
        mode=base.mode,
        run_index=-1,  # 聚合标记
        success=majority_success,
        wall_time_ms=median(wall_times),
        total_tokens=int(median(token_counts)),
        llm_calls=int(median(llm_call_counts)),
        agent_count=base.agent_count,
        messages_exchanged=base.messages_exchanged,
        output=best_output,
        # 聚合不丢错误信息：保留各次运行的诊断线索（旧版固定置空，
        # 排查问题时"跑了 3 次都失败但看不到原因"）
        errors=sorted({e for r in runs for e in r.errors}),
    )


@dataclass
class BenchmarkSummary:
    """Benchmark 汇总统计。"""

    @staticmethod
    def compute(
        single_metrics: list[TaskMetrics],
        multi_metrics: list[TaskMetrics],
    ) -> dict:
        """计算单 Agent vs 多 Agent 的汇总对比。

        Returns:
            {
                "single": {total, success, rate, avg_time, avg_tokens},
                "multi": {total, success, rate, avg_time, avg_tokens},
                "by_difficulty": {
                    "easy": {"single": {...}, "multi": {...}},
                    "medium": {...},
                    "hard": {...},
                },
            }
        """
        def _group_stats(metrics: list[TaskMetrics]) -> dict:
            total = len(metrics)
            success = sum(1 for m in metrics if m.success)
            rate = success / total if total > 0 else 0.0
            avg_time = sum(m.wall_time_ms for m in metrics) / total if total > 0 else 0.0
            avg_tokens = sum(m.total_tokens for m in metrics) / total if total > 0 else 0.0
            return {
                "total": total,
                "success": success,
                "rate": rate,
                "avg_time_ms": avg_time,
                "avg_tokens": avg_tokens,
            }

        return {
            "single": _group_stats(single_metrics),
            "multi": _group_stats(multi_metrics),
            "by_difficulty": {
                d: {
                    "single": _group_stats([m for m in single_metrics if m.difficulty == d]),
                    "multi": _group_stats([m for m in multi_metrics if m.difficulty == d]),
                }
                for d in ["easy", "medium", "hard", "expert"]
            },
        }
