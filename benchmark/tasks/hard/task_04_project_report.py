from pathlib import Path

TASK = {
    "id": "hard-04",
    "name": "项目代码统计报告",
    "description": "分析 agent_forge/ 目录下的代码统计信息（每个 .py 文件的行数、类数量、函数数量），生成一份 Markdown 格式的分析报告写入 code_stats_report.md 文件",
    "difficulty": "hard",
    "judge": {
        "type": "custom",
    },
}


def judge(agent_output: str, work_dir: Path) -> bool:
    """自定义评判：报告文件存在 + 包含文件信息 + 包含数字统计 + Markdown 标题。"""
    report_file = work_dir / "code_stats_report.md"
    if not report_file.exists():
        return False

    try:
        content = report_file.read_text(encoding="utf-8")
    except Exception:
        return False

    # 必须包含 Markdown 标题
    if "#" not in content:
        return False

    # 必须包含文件相关关键词
    if "文件" not in content and "file" not in content.lower():
        return False

    # 必须包含数字统计
    import re
    if not re.search(r'\d+', content):
        return False

    return True
