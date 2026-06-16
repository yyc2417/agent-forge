"""Benchmark 自动评判器

根据任务的 judge_config 和 Agent 的输出/产出文件，
自动判定任务是否成功完成。

支持 5 种评判类型：
- contains:     Agent 输出包含指定字符串
- file_exists:  指定文件已创建
- file_contains: 指定文件包含指定内容
- regex:        正则匹配 Agent 输出
- custom:       调用自定义 judge 函数

设计原则：
- 尽量用简单规则（contains/regex），少用 LLM 评判
- LLM 评判有偏差，数字对比更可靠
- 评判规则要足够宽松以容纳合理变体，又足够严格以区分成功/失败
"""

import re
from pathlib import Path

from benchmark.tasks import TaskDefinition


class Judge:
    """Benchmark 评判器 —— 根据任务配置判定 Agent 输出是否达标。"""

    @staticmethod
    def evaluate(
        task: TaskDefinition,
        agent_output: str,
        work_dir: Path,
    ) -> bool:
        """评判 Agent 的输出是否满足任务要求。

        Args:
            task: 任务定义。
            agent_output: Agent 的文本输出。
            work_dir: 任务执行的工作目录（用于文件检查）。

        Returns:
            True 表示任务成功，False 表示失败。
        """
        config = task.judge_config
        judge_type = config.get("type", "contains")

        try:
            if judge_type == "contains":
                return Judge._judge_contains(config, agent_output)
            elif judge_type == "file_exists":
                return Judge._judge_file_exists(config, work_dir)
            elif judge_type == "file_contains":
                return Judge._judge_file_contains(config, work_dir)
            elif judge_type == "regex":
                return Judge._judge_regex(config, agent_output)
            elif judge_type == "custom":
                return Judge._judge_custom(task, agent_output)
            else:
                # 未知类型，尝试 custom judge_fn
                if task.judge_fn:
                    return bool(task.judge_fn(agent_output))
                return False
        except Exception:
            return False

    @staticmethod
    def _judge_contains(config: dict, output: str) -> bool:
        """检查输出是否包含所有指定字符串。"""
        values = config.get("values", [])
        if not values:
            return bool(output.strip())
        output_lower = output.lower()
        return all(v.lower() in output_lower for v in values)

    @staticmethod
    def _judge_file_exists(config: dict, work_dir: Path) -> bool:
        """检查指定文件是否已创建。"""
        files = config.get("files", [])
        if not files:
            file_path = config.get("file", "")
            if file_path:
                files = [file_path]
        return all((work_dir / f).exists() for f in files)

    @staticmethod
    def _judge_file_contains(config: dict, work_dir: Path) -> bool:
        """检查指定文件是否包含指定内容。"""
        file_path = config.get("file", "")
        if not file_path:
            return False

        full_path = work_dir / file_path
        if not full_path.exists():
            return False

        try:
            content = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            return False

        values = config.get("values", [])
        if not values:
            return bool(content.strip())

        content_lower = content.lower()
        return all(v.lower() in content_lower for v in values)

    @staticmethod
    def _judge_regex(config: dict, output: str) -> bool:
        """正则匹配 Agent 输出。"""
        pattern = config.get("pattern", "")
        if not pattern:
            return False
        return bool(re.search(pattern, output))

    @staticmethod
    def _judge_custom(task: TaskDefinition, output: str) -> bool:
        """调用自定义 judge 函数。"""
        if task.judge_fn:
            return bool(task.judge_fn(output))
        return False
