"""expert-03 跨文件 Bug 定位修复（假设 H1：analyst 的检索定位价值）。

种子 bug 在 storage.find_low_stock（docstring 说 below，实现用 >），
症状经 reporting.stock_report 的低库存清单显现——Agent 需要沿
"症状 → 调用链 → 根因"跨文件定位。
"""

from pathlib import Path

from benchmark.tasks.expert.fixture_project import (
    REGRESSION_TEST,
    create_expert_fixture,
)
from benchmark.tasks.expert.judge_utils import run_pytest, run_python

TASK = {
    "id": "expert-03",
    "name": "跨文件 Bug 定位修复",
    "description": (
        "库存报表 inventory/reporting.py 的 stock_report 中，'Low stock' 清单显示的"
        "商品不对：库存数量低于阈值 10 的商品没有被列出，反而列出了库存充足的商品。"
        "症状在报表，根因可能在其他模块。请定位根因并修复（保持各模块既有接口不变），"
        "修复后运行 tests/（包含 tests/test_storage_regression.py 回归测试）确认全部通过。"
    ),
    "difficulty": "expert",
    "timeout": 300,
    "judge": {
        "type": "custom",
    },
}

# 行为探针：直接验证 find_low_stock 的边界语义（修复前输出 p2，修复后 p1）
_PROBE = (
    "from inventory.models import Product\n"
    "from inventory.storage import find_low_stock\n"
    "r = find_low_stock([Product('p1', 'Low', 5, 1.0), Product('p2', 'High', 50, 1.0)], 10)\n"
    "print(','.join(p.product_id for p in r))\n"
)


def setup(work_dir: Path) -> None:
    create_expert_fixture(work_dir)
    # 回归测试由 setup 写入：修复前失败，修复后通过
    regression = work_dir / "tests" / "test_storage_regression.py"
    regression.write_text(REGRESSION_TEST, encoding="utf-8", newline="\n")


def judge(agent_output: str, work_dir: Path) -> bool:
    """判据：全量测试（含回归）绿 + 边界语义探针正确。"""
    if run_pytest(work_dir).returncode != 0:
        return False
    probe = run_python(work_dir, _PROBE)
    if probe.returncode != 0:
        return False
    return probe.stdout.decode("utf-8", "replace").strip() == "p1"
