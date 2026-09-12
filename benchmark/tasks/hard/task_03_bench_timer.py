from pathlib import Path

TASK = {
    "id": "hard-03",
    "name": "Benchmark 计时脚本",
    "description": "创建一个 benchmark_timer.py 脚本：接受一个任务描述列表，逐个执行（用 subprocess 调用 python -c），计时每个任务的执行时间，最后输出 Markdown 表格格式的结果",
    "difficulty": "hard",
    "judge": {
        "type": "custom",
    },
}


def judge(agent_output: str, work_dir: Path) -> bool:
    """自定义评判：文件存在 + 包含 time 导入 + Markdown 表格。"""
    timer_file = work_dir / "benchmark_timer.py"
    if not timer_file.exists():
        return False

    try:
        content = timer_file.read_text(encoding="utf-8")
    except Exception:
        return False

    # 必须导入 time 模块
    if "import time" not in content and "from time" not in content:
        return False

    # 必须包含 Markdown 表格格式
    if "|" not in content:
        return False

    return True
