"""Token 成本追踪器

在 LLM 调用过程中采集 token 使用量，按 Agent 维度汇总，
支持在 Demo 结束时打印成本报告表。

采集机制：
    LangChain 的 ChatOpenAI.invoke() 返回的 AIMessage 中，
    response_metadata 包含 token_usage（OpenAI 兼容 API 标准字段）：
    {
        "token_usage": {
            "prompt_tokens": 150,
            "completion_tokens": 80,
            "total_tokens": 230,
        }
    }

    采集点在 BaseAgent.agent_node() 中——LLM 调用后立即读取 response_metadata。

设计理念：
    CostTracker 是独立模块，不侵入 LLM Provider 层。
    通过 BaseAgent 的 cost_tracker 参数注入，可选使用。
    多个 Agent 可以共享同一个 CostTracker（如 Orchestrator 下的所有 Specialist）。

使用方式：
    tracker = CostTracker(cost_per_1k_prompt=0.001, cost_per_1k_completion=0.002)
    agent = BaseAgent(name="coder", cost_tracker=tracker, ...)
    agent.run("写一个排序函数")
    tracker.print_report()
"""

import time
from dataclasses import dataclass, field

from agent_forge.utils import safe_print


@dataclass
class TokenRecord:
    """单次 LLM 调用的 Token 记录。

    Attributes:
        agent_name: 调用 LLM 的 Agent 名称。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。
        timestamp: 调用时间戳。
    """
    agent_name: str
    prompt_tokens: int
    completion_tokens: int
    timestamp: float = field(default_factory=time.time)


class CostTracker:
    """Token 成本追踪器 —— 按 Agent 维度汇总 LLM 调用成本。

    支持功能：
    - record(): 记录单次 LLM 调用
    - get_summary(): 按 Agent 维度汇总统计
    - print_report(): 格式化打印成本表
    - clear(): 清空所有记录

    成本计算：
    - 默认价格参数为 DeepSeek API 的参考价格
    - cost_per_1k_prompt: 每 1000 个输入 token 的成本（默认 ¥0.001）
    - cost_per_1k_completion: 每 1000 个输出 token 的成本（默认 ¥0.002）
    """

    def __init__(
        self,
        cost_per_1k_prompt: float = 0.001,
        cost_per_1k_completion: float = 0.002,
    ) -> None:
        self._records: list[TokenRecord] = []
        self._cost_per_1k_prompt = cost_per_1k_prompt
        self._cost_per_1k_completion = cost_per_1k_completion

    def record(
        self,
        agent_name: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """记录一次 LLM 调用的 Token 使用量。

        Args:
            agent_name: Agent 名称。
            prompt_tokens: 输入 token 数。
            completion_tokens: 输出 token 数。
        """
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return
        self._records.append(TokenRecord(
            agent_name=agent_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ))

    def get_summary(self) -> dict[str, dict]:
        """按 Agent 维度汇总统计。

        Returns:
            {agent_name: {
                "calls": int,
                "prompt_tokens": int,
                "completion_tokens": int,
                "total_tokens": int,
                "cost": float,
            }}
        """
        summary: dict[str, dict] = {}
        for record in self._records:
            name = record.agent_name
            if name not in summary:
                summary[name] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                }
            s = summary[name]
            s["calls"] += 1
            s["prompt_tokens"] += record.prompt_tokens
            s["completion_tokens"] += record.completion_tokens
            s["total_tokens"] += record.prompt_tokens + record.completion_tokens
            s["cost"] += (
                record.prompt_tokens / 1000 * self._cost_per_1k_prompt
                + record.completion_tokens / 1000 * self._cost_per_1k_completion
            )
        return summary

    def get_total_tokens(self) -> int:
        """返回所有记录的总 token 数。"""
        return sum(r.prompt_tokens + r.completion_tokens for r in self._records)

    def get_total_cost(self) -> float:
        """返回所有记录的总成本。"""
        total = 0.0
        for r in self._records:
            total += (
                r.prompt_tokens / 1000 * self._cost_per_1k_prompt
                + r.completion_tokens / 1000 * self._cost_per_1k_completion
            )
        return total

    def print_report(self) -> None:
        """格式化打印成本报告表。"""
        summary = self.get_summary()
        if not summary:
            safe_print("\n  [CostTracker] 无 Token 记录")
            return

        safe_print(f"\n{'═' * 62}")
        safe_print("  Token 成本报告")
        safe_print(f"{'═' * 62}")
        safe_print(
            f"  {'Agent':<14} {'Calls':>5} {'Prompt':>8} {'Compl':>8} "
            f"{'Total':>8} {'Cost(¥/1k)':>10}"
        )
        safe_print(f"  {'─' * 14} {'─' * 5} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8}")

        total_calls = 0
        total_prompt = 0
        total_completion = 0
        total_tokens = 0

        for name, s in sorted(summary.items()):
            safe_print(
                f"  {name:<14} {s['calls']:>5} "
                f"{s['prompt_tokens']:>8,} {s['completion_tokens']:>8,} "
                f"{s['total_tokens']:>8,} "
                f"{'¥' + format(s['cost'], '.4f'):>8}"
            )
            total_calls += s["calls"]
            total_prompt += s["prompt_tokens"]
            total_completion += s["completion_tokens"]
            total_tokens += s["total_tokens"]

        safe_print(f"  {'─' * 14} {'─' * 5} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8}")
        safe_print(
            f"  {'合计':<12} {total_calls:>5} "
            f"{total_prompt:>8,} {total_completion:>8,} "
            f"{total_tokens:>8,} "
            f"{'¥' + format(self.get_total_cost(), '.4f'):>8}"
        )
        safe_print(f"{'═' * 62}")

    def clear(self) -> None:
        """清空所有记录。"""
        self._records.clear()
