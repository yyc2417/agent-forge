"""expert-05 全库盘点报告（假设 H3：上下文规模/多文件信息汇总）。

判据采用 medium-07 的期望值范式：judge 时从 work_dir 的实际
元数据头重算 ground truth，再对报告做宽容解析——考的是把
分散在多文件的事实汇总为准确清单。
"""

from pathlib import Path

from benchmark.tasks.expert.fixture_project import (
    create_expert_fixture,
    iter_meta_headers,
)

TASK = {
    "id": "expert-05",
    "name": "代码库盘点报告",
    "description": (
        "阅读 inventory/ 包内每个 Python 模块首行的元数据注释（格式："
        "# meta: version=<值> owner=<值>），生成一份 Markdown 盘点报告写入项目根目录"
        "的 inventory_report.md：每个模块一行，同时包含该模块的文件名、version 值与 "
        "owner 值，按文件名排序，报告带标题。"
    ),
    "difficulty": "expert",
    "timeout": 300,
    "judge": {
        "type": "custom",
    },
}


def setup(work_dir: Path) -> None:
    create_expert_fixture(work_dir)


def judge(agent_output: str, work_dir: Path) -> bool:
    """判据：报告中每个带元数据的模块都有"文件名+version+owner"同行条目。"""
    report_file = work_dir / "inventory_report.md"
    if not report_file.exists():
        return False
    try:
        report_text = report_file.read_text(encoding="utf-8")
    except Exception:
        return False

    expected = iter_meta_headers(work_dir)
    if not expected:
        return False
    lines = report_text.splitlines()
    for rel_path, version, owner in expected:
        basename = rel_path.rsplit("/", 1)[-1]
        if not any(
            basename in line and version in line and owner in line for line in lines
        ):
            return False
    return True
