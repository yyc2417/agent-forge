"""阶段 5 Agent Demo —— 三步渐进式学习

学习目标：理解 Benchmark 系统的设计和使用，从"单任务跑分"到"全量对比报告"。

三步设计：
    Step 1（单 Agent 跑分）：
        → 加载 3 个 easy 任务，单 Agent 执行
        → 理解 Benchmark 的任务定义、隔离执行、自动评判

    Step 2（单 Agent vs 多 Agent 对比）：
        → 加载 5 个任务（3 easy + 2 medium）
        → 分别以单/多 Agent 模式执行，打印对比表
        → 理解多 Agent 协作的量化优势

    Step 3（全量 Benchmark + 报告生成）：
        → 全部 20 个任务，每任务 3 次取中位数
        → 单 Agent vs 多 Agent 完整对比
        → 自动生成 benchmark_report.md

使用方式：
    python demos/phase5_demo.py --step 1
    python demos/phase5_demo.py --step 2
    python demos/phase5_demo.py --step 3

前置条件：
    1. 已配置 .env 中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖
"""

import sys

from dotenv import load_dotenv

from agent_forge.utils import print_info, print_separator, safe_print
from benchmark.metrics import aggregate_runs
from benchmark.runner import BenchmarkRunner
from benchmark.tasks import load_all_tasks, load_quick_tasks

load_dotenv()


# ============================================================
# Step 1: 单 Agent 跑分
# ============================================================

def run_step1() -> None:
    """单 Agent Benchmark 跑分：理解任务定义、隔离执行、自动评判。

    学习目标：
    1. TaskDefinition 的结构（id, description, judge_config）
    2. 临时目录隔离执行（每个任务独立环境）
    3. Judge 自动评判（contains/file_contains/regex）
    """
    print_separator("阶段 5 Demo — Step 1: 单 Agent 跑分", 60)
    print_info("加载 3 个 easy 任务，单 Agent 逐个执行")
    print_info("观察：任务描述 → Agent 执行 → 评判结果 → 统计汇总")
    safe_print()

    tasks = load_quick_tasks(count=3)
    safe_print(f"  已加载 {len(tasks)} 个任务:")
    for t in tasks:
        safe_print(f"    - [{t.id}] {t.name}")
    safe_print()

    runner = BenchmarkRunner(runs=1, timeout=120)

    safe_print("  开始单 Agent 跑分...")
    safe_print()

    results = []
    for i, task in enumerate(tasks):
        safe_print(f"  [{i + 1}/{len(tasks)}] {task.id}: {task.name}")
        runs = runner._run_task_mode(task, "single")
        agg = aggregate_runs(runs)
        results.append(agg)

        safe_print(
            f"    结果: {'✅' if agg.success else '❌'} "
            f"耗时: {agg.wall_time_ms / 1000:.1f}s "
            f"Token: {agg.total_tokens:,}"
        )
        safe_print()

    # 汇总
    success = sum(1 for r in results if r.success)
    safe_print(f"{'─' * 50}")
    safe_print(f"  汇总: {success}/{len(results)} 成功")
    safe_print(f"  平均耗时: {sum(r.wall_time_ms for r in results) / len(results) / 1000:.1f}s")
    safe_print(f"  总 Token: {sum(r.total_tokens for r in results):,}")


# ============================================================
# Step 2: 单 Agent vs 多 Agent 对比
# ============================================================

def run_step2() -> None:
    """单 Agent vs 多 Agent 对比：量化多 Agent 协作的优势。

    学习目标：
    1. 对比实验的设计思路（同任务、不同模式）
    2. 多 Agent 的编排开销 vs 质量提升
    3. 如何解读对比数据
    """
    print_separator("阶段 5 Demo — Step 2: 单 Agent vs 多 Agent 对比", 60)
    print_info("加载 5 个任务（3 easy + 2 medium）")
    print_info("每个任务分别以单/多 Agent 模式执行")
    safe_print()

    easy_tasks = load_quick_tasks(count=3)
    all_tasks = load_all_tasks(difficulty_filter="medium")
    medium_tasks = all_tasks[:2]
    tasks = easy_tasks + medium_tasks

    safe_print(f"  已加载 {len(tasks)} 个任务:")
    for t in tasks:
        safe_print(f"    - [{t.id}] {t.name} ({t.difficulty})")
    safe_print()

    runner = BenchmarkRunner(runs=1, timeout=120)

    single_results = []
    multi_results = []

    for i, task in enumerate(tasks):
        safe_print(f"\n  [{i + 1}/{len(tasks)}] {task.id}: {task.name}")

        # 单 Agent
        s_runs = runner._run_task_mode(task, "single")
        s_agg = aggregate_runs(s_runs)
        single_results.append(s_agg)
        safe_print(
            f"    单Agent: {'✅' if s_agg.success else '❌'} "
            f"{s_agg.wall_time_ms / 1000:.1f}s "
            f"{s_agg.total_tokens:,} tok"
        )

        # 多 Agent
        m_runs = runner._run_task_mode(task, "multi")
        m_agg = aggregate_runs(m_runs)
        multi_results.append(m_agg)
        safe_print(
            f"    多Agent: {'✅' if m_agg.success else '❌'} "
            f"{m_agg.wall_time_ms / 1000:.1f}s "
            f"{m_agg.total_tokens:,} tok"
        )

    # 对比汇总
    s_success = sum(1 for r in single_results if r.success)
    m_success = sum(1 for r in multi_results if r.success)
    s_avg_time = sum(r.wall_time_ms for r in single_results) / len(single_results) / 1000
    m_avg_time = sum(r.wall_time_ms for r in multi_results) / len(multi_results) / 1000
    s_total_tok = sum(r.total_tokens for r in single_results)
    m_total_tok = sum(r.total_tokens for r in multi_results)

    safe_print(f"\n{'═' * 60}")
    safe_print("  对比汇总")
    safe_print(f"{'═' * 60}")
    safe_print(f"  {'指标':<14} {'单Agent':>12} {'多Agent':>12}")
    safe_print(f"  {'─' * 14} {'─' * 12} {'─' * 12}")
    s_rate = f"{s_success}/{len(single_results)} ({s_success / len(single_results):.0%})"
    m_rate = f"{m_success}/{len(multi_results)} ({m_success / len(multi_results):.0%})"
    safe_print(f"  {'完成率':<12} {s_rate} {m_rate}")
    safe_print(f"  {'平均耗时':<10} {s_avg_time:.1f}s {m_avg_time:.1f}s")
    safe_print(f"  {'总Token':<10} {s_total_tok:,} {m_total_tok:,}")
    safe_print(f"{'═' * 60}")


# ============================================================
# Step 3: 全量 Benchmark + 报告生成
# ============================================================

def run_step3() -> None:
    """全量 Benchmark：20 个任务 × 3 次 × 单/多 Agent = 完整对比报告。

    学习目标：
    1. 完整的 Benchmark 流程（加载 → 执行 → 聚合 → 报告）
    2. 统计意义：同一任务多次运行取中位数消除 LLM 随机性
    3. 报告的价值：README 里放摘要，演示时现场跑 quick 模式
    """
    print_separator("阶段 5 Demo — Step 3: 全量 Benchmark", 60)
    print_info("20 个任务 × 3 次运行 × 单/多 Agent")
    print_info("自动生成 benchmark_report.md")
    safe_print()

    runner = BenchmarkRunner(runs=3, timeout=120)
    single, multi, report_path = runner.run_all()

    safe_print(f"\n  报告已生成: {report_path}")
    safe_print(f"  查看报告: type {report_path}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    """运行入口：通过 --step 参数选择步骤。"""
    step = "1"
    if len(sys.argv) > 2 and sys.argv[1] == "--step":
        step = sys.argv[2]

    steps = {"1": run_step1, "2": run_step2, "3": run_step3}

    if step not in steps:
        safe_print(f"错误：未知步骤 '{step}'。可选：1, 2, 3")
        sys.exit(1)

    try:
        safe_print(f"\n📊 启动阶段 5 Agent Demo — Step {step}\n")
    except UnicodeEncodeError:
        safe_print(f"\n[AgentForge] Starting Phase 5 Demo — Step {step}\n")

    steps[step]()
