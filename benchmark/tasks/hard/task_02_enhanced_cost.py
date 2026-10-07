import shutil
from pathlib import Path

# 任务文件位于 <repo>/benchmark/tasks/hard/，向上三级即仓库根
_REPO_ROOT = Path(__file__).resolve().parents[3]

TASK = {
    "id": "hard-02",
    "name": "增强版 CostTracker",
    "description": "读取当前目录下的 cost.py（一份 CostTracker 的现有实现），"
                   "创建一个增强版的 CostTracker（新增 to_json 方法支持导出为 JSON 格式），"
                   "将增强版代码写入 enhanced_cost.py",
    "difficulty": "hard",
    "timeout": 240,
    "judge": {
        "type": "custom",
    },
}


def setup(work_dir: Path):
    """把 agent_forge/cost.py 复制进工作目录，使任务可满足。

    旧版描述要求"读取 agent_forge/cost.py"，但 runner 已把执行环境
    隔离到空临时目录，该文件根本不存在——Agent 只能凭 LLM 记忆臆写，
    任务测的不是它声称的能力。setup 把源文件放进工作目录，任务才成立。
    """
    src = _REPO_ROOT / "agent_forge" / "cost.py"
    if src.exists():
        shutil.copy(src, work_dir / "cost.py")


def judge(agent_output: str, work_dir: Path) -> bool:
    """自定义评判：enhanced_cost.py 存在 + 包含 to_json + 包含原始方法。"""
    enhanced_file = work_dir / "enhanced_cost.py"
    if not enhanced_file.exists():
        return False

    try:
        content = enhanced_file.read_text(encoding="utf-8")
    except Exception:
        return False

    # 必须包含 to_json 方法
    if "to_json" not in content:
        return False

    # 必须包含 CostTracker 类
    if "class CostTracker" not in content and "class EnhancedCostTracker" not in content:
        return False

    return True
