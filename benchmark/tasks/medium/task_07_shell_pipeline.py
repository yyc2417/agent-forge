import re
from pathlib import Path

from benchmark.tasks.sample_project import create as _create_sample

TASK = {
    "id": "medium-07",
    "name": "Shell 管道操作",
    "description": "用 Shell 命令找出当前项目中行数最多的 5 个 Python 文件，返回文件名和行数",
    "difficulty": "medium",
    "judge": {
        "type": "custom",
    },
}


def setup(work_dir):
    """创建多个行数不同的 .py 文件（隔离目录原本为空，任务否则不可满足）。"""
    _create_sample(work_dir)


def _expected_top5(work_dir: Path) -> list[tuple[str, set[int]]]:
    """从工作目录重算 ground truth：按行数取前 5 的 .py 文件。

    返回 (文件基名, 可接受行数集合)。行数同时提供 splitlines 与
    wc -l 两种口径（仅当文件不以换行结尾时二者相差 1），
    避免评判规则比工具的计数习惯更严格。
    """
    entries: list[tuple[str, set[int]]] = []
    for py in sorted(work_dir.rglob("*.py")):
        try:
            text = py.read_text(encoding="utf-8")
        except Exception:
            continue
        counts = {len(text.splitlines()), text.count("\n")}
        entries.append((py.name, counts))
    entries.sort(key=lambda e: (-max(e[1]), e[0]))
    return entries[:5]


def _line_matches(line: str, name: str, counts: set[int]) -> bool:
    """同一行同时出现文件名与（任一口径的）行数即认匹配。

    2026-09-13 实测中旧 regex judge（`\\d+\\s+\\S+\\.py`）对输出格式
    敏感，Agent 可能算对但表述为 `base.py: 7` / `base.py（7 行）`
    而被判失败。数字匹配用 (?<!\\d)/(?!\\d) 防止 7 误配 17。
    """
    if name not in line:
        return False
    return any(
        re.search(rf"(?<!\d){re.escape(str(c))}(?!\d)", line)
        for c in counts
    )


def judge(agent_output: str, work_dir: Path) -> bool:
    """自定义评判：输出中每个 top-5 文件都能找到"文件名 + 行数"同行证据。"""
    expected = _expected_top5(work_dir)
    if not expected:
        return False
    lines = agent_output.splitlines()
    for name, counts in expected:
        if not any(_line_matches(line, name, counts) for line in lines):
            return False
    return True
