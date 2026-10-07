"""Benchmark 报告生成器

将 Benchmark 运行结果生成 Markdown 格式的报告文件。
报告包含：总体对比表、按难度分表、各任务详情表。

输出路径：benchmark/reports/latest/benchmark_report.md
"""

from datetime import datetime
from pathlib import Path

from agent_forge.utils import atomic_write_text
from benchmark.metrics import BenchmarkSummary, TaskMetrics


class Reporter:
    """Markdown 报告生成器。"""

    @staticmethod
    def generate(
        single_metrics: list[TaskMetrics],
        multi_metrics: list[TaskMetrics],
        output_dir: str = "benchmark/reports/latest",
    ) -> Path:
        """生成 Markdown 报告。

        Args:
            single_metrics: 单 Agent 模式的聚合指标列表。
            multi_metrics: 多 Agent 模式的聚合指标列表。
            output_dir: 报告输出目录。

        Returns:
            生成的报告文件路径。
        """
        summary = BenchmarkSummary.compute(single_metrics, multi_metrics)
        lines = Reporter._build_report(summary, single_metrics, multi_metrics)

        # 写入文件（原子写：防止进程崩溃留下截断的半截报告）
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        report_file = out_path / "benchmark_report.md"
        atomic_write_text(report_file, "\n".join(lines))

        return report_file

    @staticmethod
    def _build_report(
        summary: dict,
        single_metrics: list[TaskMetrics],
        multi_metrics: list[TaskMetrics],
    ) -> list[str]:
        """构建报告的 Markdown 行列表。"""
        lines: list[str] = []

        # 标题
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines.append("# AgentForge Benchmark Report")
        lines.append(f"> 生成时间：{now}")
        lines.append("")

        # 总体对比
        s = summary["single"]
        m = summary["multi"]
        lines.append("## 总体对比")
        lines.append("")
        lines.append("| 指标 | 单 Agent | 多 Agent | 差异 |")
        lines.append("|------|---------|----------|------|")
        lines.append(
            f"| 总完成率 | {s['success']}/{s['total']} "
            f"({s['rate']:.0%}) | {m['success']}/{m['total']} "
            f"({m['rate']:.0%}) | "
            f"{(m['rate'] - s['rate']):+.0%} |"
        )
        lines.append(
            f"| 平均耗时 | {s['avg_time_ms'] / 1000:.1f}s | "
            f"{m['avg_time_ms'] / 1000:.1f}s | "
            f"{((m['avg_time_ms'] - s['avg_time_ms']) / max(s['avg_time_ms'], 1)):+.0%} |"
        )
        lines.append(
            f"| 平均 Token | {s['avg_tokens']:.0f} | "
            f"{m['avg_tokens']:.0f} | "
            f"{((m['avg_tokens'] - s['avg_tokens']) / max(s['avg_tokens'], 1)):+.0%} |"
        )
        lines.append("")

        # 按难度分
        lines.append("## 按难度分")
        lines.append("")
        lines.append("| 难度 | 单 Agent | 多 Agent |")
        lines.append("|------|---------|----------|")
        for d in ["easy", "medium", "hard", "expert"]:
            ds = summary["by_difficulty"].get(d, {})
            single_d = ds.get("single", {})
            multi_d = ds.get("multi", {})
            s_total = single_d.get("total", 0)
            m_total = multi_d.get("total", 0)
            s_succ = single_d.get("success", 0)
            m_succ = multi_d.get("success", 0)
            s_rate = single_d.get("rate", 0)
            m_rate = multi_d.get("rate", 0)
            lines.append(
                f"| {d} ({s_total}) | {s_succ}/{s_total} ({s_rate:.0%}) | "
                f"{m_succ}/{m_total} ({m_rate:.0%}) |"
            )
        lines.append("")

        # 各任务详情
        lines.append("## 各任务详情")
        lines.append("")
        lines.append("| ID | 任务 | 难度 | 单Agent | 多Agent | 单耗时 | 多耗时 | 单Token | 多Token |")
        lines.append("|-----|------|------|---------|---------|--------|--------|---------|---------|")

        # 合并单/多指标
        multi_by_id = {m.task_id: m for m in multi_metrics}
        for sm in single_metrics:
            mm = multi_by_id.get(sm.task_id)
            s_status = "✅" if sm.success else "❌"
            m_status = "✅" if (mm and mm.success) else "❌"
            s_time = f"{sm.wall_time_ms / 1000:.1f}s"
            m_time = f"{mm.wall_time_ms / 1000:.1f}s" if mm else "-"
            s_tok = f"{sm.total_tokens:,}"
            m_tok = f"{mm.total_tokens:,}" if mm else "-"
            lines.append(
                f"| {sm.task_id} | {sm.task_name} | {sm.difficulty} | "
                f"{s_status} | {m_status} | {s_time} | {m_time} | "
                f"{s_tok} | {m_tok} |"
            )
        lines.append("")

        # 异常与超时明细（聚合层保留的各次运行诊断线索）
        # 2026-09-13 实测的教训：easy-05 多 Agent 失败原因、6 个任务的
        # 120s 超时都只能靠"耗时恰好 120.0s"反推——errors 已被采集和
        # 聚合，却从未渲染，进程结束即丢失。无异常时不输出本节。
        error_lines = Reporter._build_error_section(single_metrics, multi_metrics)
        if error_lines:
            lines.append("## 异常与超时明细")
            lines.append("")
            lines.extend(error_lines)
            lines.append("")

        return lines

    @staticmethod
    def _build_error_section(
        single_metrics: list[TaskMetrics],
        multi_metrics: list[TaskMetrics],
    ) -> list[str]:
        """构建异常明细行：按任务×模式列出去重后的 errors（每条截断 200 字符）。"""
        lines: list[str] = []
        for metrics in (*single_metrics, *multi_metrics):
            if not metrics.errors:
                continue
            mode_label = "单Agent" if metrics.mode == "single" else "多Agent"
            lines.append(f"- **{metrics.task_id}（{mode_label}）**")
            for err in metrics.errors:
                text = err if len(err) <= 200 else f"{err[:200]}…"
                lines.append(f"  - {text}")
        return lines
