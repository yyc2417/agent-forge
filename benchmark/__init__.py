"""Benchmark 系统 —— AgentForge 量化评测框架

自动运行标准任务集，对比单 Agent vs 多 Agent 的表现，
采集完成率、耗时、Token 消耗等指标，生成 Markdown 报告。

使用方式：
    # 通过 Demo 脚本
    python demos/phase5_demo.py --step 3

    # 直接调用
    from benchmark import run_benchmark
    single, multi, report = run_benchmark(quick=True)

    # 完整运行
    from benchmark import run_benchmark
    single, multi, report = run_benchmark()
"""

from benchmark.judge import Judge
from benchmark.metrics import BenchmarkSummary, MetricsCollector, TaskMetrics, aggregate_runs
from benchmark.reporter import Reporter
from benchmark.runner import BenchmarkRunner, run_benchmark
from benchmark.tasks import TaskDefinition, load_all_tasks, load_quick_tasks

__all__ = [
    "TaskDefinition", "load_all_tasks", "load_quick_tasks",
    "Judge",
    "TaskMetrics", "MetricsCollector", "BenchmarkSummary", "aggregate_runs",
    "Reporter",
    "BenchmarkRunner", "run_benchmark",
]
