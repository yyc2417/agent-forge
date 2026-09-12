import re
from pathlib import Path

TASK = {
    "id": "easy-03",
    "name": "统计文件数量",
    "description": "统计当前目录下所有 .py 文件的数量，并在回复中明确给出这个数字",
    "difficulty": "easy",
    "judge": {
        "type": "custom",
    },
}

# setup 在工作目录创建 7 个 .py 文件。
# 之所以是 7：旧版 judge 用 regex \d+ 评判——输出里出现任何数字
# （如 "Python 3.11"）即恒为成功，评测数据全是噪音；
# 选一个不容易被环境信息偶然包含的数字，降低误判率。
_FILE_COUNT = 7


def setup(work_dir: Path):
    """在工作目录创建若干 .py 文件供统计。"""
    for i in range(_FILE_COUNT):
        (work_dir / f"module_{i}.py").write_text("# placeholder\n", encoding="utf-8")


def judge(agent_output: str, work_dir: Path) -> bool:
    r"""自定义评判：输出中的数字必须包含实际文件数。

    旧版用 regex \d+ 评判——任何数字都能通过，恒为成功。
    现在对比输出中的数字与 work_dir 里真实的 .py 文件数。
    """
    actual = len(list(work_dir.glob("*.py")))
    numbers = [int(n) for n in re.findall(r"\d+", agent_output)]
    return actual in numbers
