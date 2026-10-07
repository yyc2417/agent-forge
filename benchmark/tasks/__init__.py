"""Benchmark 任务定义和加载器

每个任务文件定义一个标准格式的 TASK dict + 可选的 judge/setup/teardown 函数。
本模块提供 TaskDefinition 数据类和 load_all_tasks() 加载器，
自动扫描 easy/medium/hard 目录下的所有任务文件。

任务文件格式：
    TASK = {
        "id": "easy-01",
        "name": "创建文件",
        "description": "在当前目录创建 hello.py，内容为 print('Hello World')",
        "difficulty": "easy",
        "judge": {"type": "file_contains", "file": "hello.py", "values": ["Hello World"]}
    }

    def judge(agent_output: str) -> bool:
        '''自定义评判逻辑（可选）'''
        ...

    def setup():
        '''环境准备（可选）'''
        ...

    def teardown():
        '''环境清理（可选）'''
        ...
"""

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent_forge.utils import safe_print


@dataclass
class TaskDefinition:
    """Benchmark 任务定义。

    Attributes:
        id: 任务唯一标识，如 "easy-01"。
        name: 任务名称。
        description: 传给 Agent 的任务描述。
        difficulty: 难度级别（easy/medium/hard）。
        judge_config: 评判配置 dict，包含 type 和评判参数。
        judge_fn: 自定义评判函数（custom 类型时使用）。
        setup_fn: 环境准备函数（可选）。
        teardown_fn: 环境清理函数（可选）。
        timeout: 超时时间（秒）。
    """
    id: str
    name: str
    description: str
    difficulty: str
    judge_config: dict = field(default_factory=dict)
    judge_fn: Callable | None = None
    setup_fn: Callable | None = None
    teardown_fn: Callable | None = None
    timeout: int = 120


def _load_task_module(task_file: Path):
    """动态加载任务文件的 Python 模块。

    加载失败（语法错误、导入错误等）打印告警后返回 None——
    任务不会静默消失，对比报告的任务缩水可以被察觉。
    """
    module_name = f"benchmark.tasks.{task_file.stem}"
    spec = importlib.util.spec_from_file_location(module_name, task_file)
    if spec is None or spec.loader is None:
        safe_print(f"  [Tasks] 警告: 无法创建导入规格，跳过任务: {task_file.name}")
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        safe_print(
            f"  [Tasks] 警告: 任务文件加载失败，已跳过 {task_file.name}: "
            f"{type(e).__name__}: {e}"
        )
        return None
    return module


def _task_from_module(module, task_file: Path) -> TaskDefinition | None:
    """从加载的模块中提取 TaskDefinition。"""
    task_dict = getattr(module, "TASK", None)
    if not isinstance(task_dict, dict):
        return None

    return TaskDefinition(
        id=task_dict.get("id", task_file.stem),
        name=task_dict.get("name", task_file.stem),
        description=task_dict.get("description", ""),
        difficulty=task_dict.get("difficulty", "easy"),
        judge_config=task_dict.get("judge", {}),
        judge_fn=getattr(module, "judge", None),
        setup_fn=getattr(module, "setup", None),
        teardown_fn=getattr(module, "teardown", None),
        timeout=task_dict.get("timeout", 120),
    )


def load_all_tasks(
    difficulty_filter: str | None = None,
) -> list[TaskDefinition]:
    """扫描 tasks/ 目录，加载所有任务定义。

    Args:
        difficulty_filter: 按难度过滤（"easy"/"medium"/"hard"）。
                          None 表示加载所有。

    Returns:
        TaskDefinition 列表，按 id 排序。
    """
    tasks_dir = Path(__file__).parent
    all_tasks: list[TaskDefinition] = []

    # 扫描 easy/medium/hard/expert 子目录
    for sub_dir in ["easy", "medium", "hard", "expert"]:
        if difficulty_filter and sub_dir != difficulty_filter:
            continue

        dir_path = tasks_dir / sub_dir
        if not dir_path.is_dir():
            continue

        for task_file in sorted(dir_path.glob("task_*.py")):
            module = _load_task_module(task_file)
            if module is None:
                continue
            task = _task_from_module(module, task_file)
            if task is not None:
                all_tasks.append(task)

    # 按 id 排序（easy-01, easy-02, ..., medium-01, ..., hard-01, ...）
    all_tasks.sort(key=lambda t: t.id)
    return all_tasks


def load_quick_tasks(count: int = 5) -> list[TaskDefinition]:
    """加载快速演示用的任务（前 N 个 easy 任务）。

    Args:
        count: 要加载的任务数量。

    Returns:
        TaskDefinition 列表。
    """
    easy_tasks = load_all_tasks(difficulty_filter="easy")
    return easy_tasks[:count]


__all__ = ["TaskDefinition", "load_all_tasks", "load_quick_tasks"]
