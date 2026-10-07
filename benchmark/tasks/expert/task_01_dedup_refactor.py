"""expert-01 重复代码提取重构（假设 H2：长链条依赖）。"""

from pathlib import Path

from benchmark.tasks.expert.fixture_project import create_expert_fixture
from benchmark.tasks.expert.judge_utils import run_pytest, run_python

TASK = {
    "id": "expert-01",
    "name": "重复代码提取重构",
    "description": (
        "本项目 inventory/services.py 和 inventory/reporting.py 中各有一份重复实现的"
        "价格格式化函数 _format_money。请把该逻辑提取到新模块 inventory/pricing.py，"
        "公共函数命名为 format_money（去掉下划线前缀），两个原模块删除各自的 "
        "_format_money 定义并改为从 pricing 导入；新模块按 README.md 约定添加元数据头。"
        "完成后运行 tests/ 确认全部通过。"
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
    """判据：重复定义消失 + pricing 模块合规 + 原测试全绿 + 可导入。"""
    pricing = work_dir / "inventory" / "pricing.py"
    if not pricing.exists():
        return False
    try:
        pricing_content = pricing.read_text(encoding="utf-8")
    except Exception:
        return False
    if "def format_money" not in pricing_content:
        return False
    # README 约定：新模块带元数据头
    if not pricing_content.splitlines()[0].startswith("# meta: version="):
        return False

    # 重复定义必须从两个原模块中消失
    for name in ("services.py", "reporting.py"):
        original = work_dir / "inventory" / name
        if not original.exists():
            return False
        if "def _format_money" in original.read_text(encoding="utf-8"):
            return False

    # 行为保持：原测试套件全绿（重构是行为保持的）
    if run_pytest(work_dir).returncode != 0:
        return False
    # pricing 可经包路径导入
    probe = run_python(work_dir, "from inventory.pricing import format_money")
    return probe.returncode == 0
