import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

TASK = {
    "id": "medium-03",
    "name": "代码分析报告",
    "description": "读取当前目录下的 utils.py 文件，分析其代码质量并给出至少 3 条改进建议",
    "difficulty": "medium",
    "judge": {
        "type": "custom",
    },
}


def setup(work_dir: Path):
    """把真实的 agent_forge/utils.py 复制进工作目录（隔离目录原本为空）。"""
    shutil.copy(_REPO_ROOT / "agent_forge" / "utils.py", work_dir / "utils.py")


def judge(agent_output: str) -> bool:
    """自定义评判：输出至少 100 字符且包含分析关键词。

    注意：模块里原本就定义了这个 judge 函数，但 TASK 的 judge.type
    误写成 contains，导致它从未被执行（死配置）——现改为 custom。
    """
    if len(agent_output) < 100:
        return False
    keywords = ["建议", "改进", "优化", "可以", "应该", "问题", "分析"]
    return any(kw in agent_output for kw in keywords)
