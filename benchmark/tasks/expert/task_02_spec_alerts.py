"""expert-02 规格驱动实现（假设 H1 异质角色 + H2 长链条）。

判据采用 AppWorld 状态单测范式（ADR-008）：
- 验终态：隐藏验收测试在 judge 时才写入 work_dir（Agent 事前
  看不到，防"面向判据编程"），按 spec.md 契约跑真测试；
- 查副作用：spec.md 约束不得改动的文件与 pristine 内容逐一比对。
"""

import json
import subprocess
import sys
from pathlib import Path

from benchmark.tasks.expert.fixture_project import (
    FIXTURE_FILES,
    PROTECTED_FILES,
    create_expert_fixture,
)
from benchmark.tasks.expert.judge_utils import run_pytest

TASK = {
    "id": "expert-02",
    "name": "规格驱动的低库存告警实现",
    "description": (
        "阅读项目根目录的 spec.md，按规格实现低库存告警功能：在 inventory/services.py "
        "新增 check_alerts 函数，并给 inventory/cli.py 新增 alerts 子命令。函数签名、"
        "返回字段、输出格式、排序等契约必须严格遵守 spec.md；不得改动 models、storage、"
        "reporting、tests/ 与 docs/ 的现有行为。完成后运行 tests/ 确认原有测试全部通过。"
    ),
    "difficulty": "expert",
    "timeout": 300,
    "judge": {
        "type": "custom",
    },
}

# 验收测试：契约完全来自 spec.md；judge 时写入，Agent 事前不可见。
_ACCEPTANCE_TEST = '''\
"""Judge acceptance tests for the low-stock alert spec."""

from inventory.models import Product
from inventory.services import check_alerts
from inventory.storage import save_products


def test_alert_levels_sorted(tmp_path):
    path = tmp_path / "products.json"
    save_products(
        [
            Product("p3", "Beam", 20, 0.5),
            Product("p2", "Nut", 7, 0.5),
            Product("p1", "Bolt", 2, 0.5),
        ],
        path,
    )
    alerts = check_alerts(10, path)
    assert [(a["product_id"], a["level"]) for a in alerts] == [
        ("p1", "critical"),
        ("p2", "warning"),
    ]
    assert alerts[0]["name"] == "Bolt"
    assert alerts[0]["quantity"] == 2


def test_no_alerts(tmp_path):
    path = tmp_path / "products.json"
    save_products([Product("p3", "Beam", 20, 0.5)], path)
    assert check_alerts(10, path) == []
'''

_CLI_PROBE = "from inventory.cli import main  # noqa: F401 — alerts 子命令可导入"


def setup(work_dir: Path) -> None:
    create_expert_fixture(work_dir)


def judge(agent_output: str, work_dir: Path) -> bool:
    """判据：副作用检查 + 隐藏验收测试 + CLI 端到端探针。"""
    # 1) 副作用检查：spec 约束不得改动的文件与 pristine 逐一比对
    #    （read_text 通用换行归一，与写入时的换行风格无关）
    for rel_path in PROTECTED_FILES:
        current = work_dir / rel_path
        if not current.exists():
            return False
        if current.read_text(encoding="utf-8") != FIXTURE_FILES[rel_path]:
            return False

    # 2) 隐藏验收测试（judge 时写入，覆盖同名防预留作弊文件）
    acceptance = work_dir / "_judge_acceptance_test_alerts.py"
    acceptance.write_text(_ACCEPTANCE_TEST, encoding="utf-8", newline="\n")
    if run_pytest(work_dir, acceptance.name).returncode != 0:
        return False

    # 3) CLI 端到端：手写 storage 格式的 JSON（见 fixture 自检测试），
    #    跑 alerts 子命令验证输出契约
    products_json = work_dir / "products.json"
    products_json.write_text(
        json.dumps(
            [
                {"product_id": "p1", "name": "Bolt", "quantity": 2, "price": 0.5},
                {"product_id": "p2", "name": "Nut", "quantity": 7, "price": 0.5},
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    cli_run = subprocess.run(
        [sys.executable, "-m", "inventory.cli", "alerts"],
        cwd=work_dir,
        capture_output=True,
        timeout=60,
    )
    if cli_run.returncode != 0:
        return False
    stdout = cli_run.stdout.decode("utf-8", "replace")
    return "CRITICAL: Bolt (2)" in stdout and "WARNING: Nut (7)" in stdout
