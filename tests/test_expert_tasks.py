"""Expert 层任务可满足性测试（零 API）。

金路径在 tmp 中直接构造正确终态（不跑 Agent），judge 必须通过
——证明任务结构性可满足（v1 "修评测环境"教训的应用）；失败
路径验证 judge 能拒绝错误/作弊终态。
"""

from pathlib import Path

from benchmark.tasks import load_all_tasks
from benchmark.tasks.expert.fixture_project import (
    FIXTURE_FILES,
    REGRESSION_TEST,
    create_expert_fixture,
    iter_meta_headers,
)
from benchmark.tasks.expert.task_01_dedup_refactor import judge as judge01
from benchmark.tasks.expert.task_02_spec_alerts import judge as judge02
from benchmark.tasks.expert.task_03_cross_file_bugfix import judge as judge03
from benchmark.tasks.expert.task_04_module_and_docs import judge as judge04
from benchmark.tasks.expert.task_05_inventory_report import judge as judge05

_OLD_MONEY_BLOCK = (
    "def _format_money(amount: float) -> str:\n"
    '    """Format an amount as CNY currency, e.g. ``1,234.50 CNY``."""\n'
    '    return "CNY " + f"{amount:,.2f}"\n'
    "\n"
    "\n"
)

_PRICING = (
    "# meta: version=1.0 owner=fixture\n"
    '"""Shared price formatting."""\n'
    "\n"
    "\n"
    "def format_money(amount: float) -> str:\n"
    '    """Format an amount as CNY currency, e.g. ``1,234.50 CNY``."""\n'
    '    return "CNY " + f"{amount:,.2f}"\n'
)

_CHECK_ALERTS = (
    "\n\n"
    "def check_alerts(threshold: int = 10, path: Path = STORAGE_FILE) -> list[dict]:\n"
    '    """Low-stock alerts (see spec.md)."""\n'
    "    alerts = []\n"
    "    for product in sorted(load_products(path), key=lambda p: p.quantity):\n"
    "        if product.quantity >= threshold:\n"
        "            break\n"
    '        level = "critical" if product.quantity < 5 else "warning"\n'
    "        alerts.append({\n"
    '            "product_id": product.product_id,\n'
    '            "name": product.name,\n'
    '            "quantity": product.quantity,\n'
    '            "level": level,\n'
    "        })\n"
    "    return alerts\n"
)

_SUPPLIER = (
    "# meta: version=1.0 owner=fixture\n"
    '"""Supplier records."""\n'
    "from __future__ import annotations\n"
    "\n"
    "import json\n"
    "from dataclasses import asdict, dataclass\n"
    "from pathlib import Path\n"
    "\n"
    'SUPPLIERS_FILE = Path("suppliers.json")\n'
    "\n"
    "\n"
    "@dataclass\n"
    "class Supplier:\n"
    "    supplier_id: str\n"
    "    name: str\n"
    "    email: str\n"
    "\n"
    "    def to_dict(self) -> dict:\n"
    "        return asdict(self)\n"
    "\n"
    "    @classmethod\n"
    '    def from_dict(cls, data: dict) -> "Supplier":\n'
    "        return cls(\n"
    '            supplier_id=data["supplier_id"],\n'
    '            name=data["name"],\n'
    '            email=data["email"],\n'
    "        )\n"
    "\n"
    "\n"
    "def load_suppliers(path: Path = SUPPLIERS_FILE) -> list[Supplier]:\n"
    "    if not path.exists():\n"
    "        return []\n"
    '    raw = json.loads(path.read_text(encoding="utf-8"))\n'
    "    return [Supplier.from_dict(item) for item in raw]\n"
    "\n"
    "\n"
    "def save_suppliers(suppliers: list[Supplier], path: Path = SUPPLIERS_FILE) -> None:\n"
    '    path.write_text(json.dumps([s.to_dict() for s in suppliers], indent=2),\n'
    '                    encoding="utf-8")\n'
)

_USAGE_APPEND_CODE = (
    "- `inventory.reporting`: text stock reports\n"
    "- `inventory.supplier`: supplier records\n"
    "\n"
    "## Suppliers\n"
    "\n"
    "```python\n"
    "from inventory.supplier import Supplier, save_suppliers\n"
    'save_suppliers([Supplier("s1", "Acme", "a@acme.io")])\n'
    "```\n"
)


def _write(work_dir: Path, rel: str, content: str) -> None:
    target = work_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def _golden_01(work_dir: Path) -> None:
    """expert-01 正确终态：提取 pricing 并更新两个原模块。"""
    create_expert_fixture(work_dir)
    for name, import_anchor in (
        ("services.py", "from inventory.models import Order, Product"),
        ("reporting.py", "from inventory.storage import STORAGE_FILE, find_low_stock, load_products"),
    ):
        rel = f"inventory/{name}"
        content = FIXTURE_FILES[rel]
        assert _OLD_MONEY_BLOCK in content
        content = content.replace(_OLD_MONEY_BLOCK, "")
        content = content.replace("_format_money(", "format_money(")
        content = content.replace(
            import_anchor, f"{import_anchor}\nfrom inventory.pricing import format_money"
        )
        _write(work_dir, rel, content)
    _write(work_dir, "inventory/pricing.py", _PRICING)


def _golden_02(work_dir: Path) -> None:
    """expert-02 正确终态：按 spec 实现 check_alerts + alerts 子命令。"""
    create_expert_fixture(work_dir)
    _write(work_dir, "inventory/services.py", FIXTURE_FILES["inventory/services.py"] + _CHECK_ALERTS)
    cli = FIXTURE_FILES["inventory/cli.py"].replace(
        '    sub.add_parser("report", help="print the stock report")\n',
        '    sub.add_parser("report", help="print the stock report")\n'
        '    sub.add_parser("alerts", help="print low-stock alerts")\n',
    ).replace(
        '    if args.command == "order-total":\n',
        '    if args.command == "alerts":\n'
        "        for alert in check_alerts():\n"
        "            print(f\"{alert['level'].upper()}: {alert['name']} ({alert['quantity']})\")\n"
        "        return 0\n"
        '    if args.command == "order-total":\n',
    ).replace(
        "from inventory.services import order_total",
        "from inventory.services import check_alerts, order_total",
    )
    _write(work_dir, "inventory/cli.py", cli)


def _golden_03(work_dir: Path) -> None:
    """expert-03 正确终态：修复 find_low_stock 的比较方向。"""
    create_expert_fixture(work_dir)
    _write(work_dir, "tests/test_storage_regression.py", REGRESSION_TEST)
    fixed = FIXTURE_FILES["inventory/storage.py"].replace(
        "return [p for p in products if p.quantity > threshold]",
        "return [p for p in products if p.quantity < threshold]",
    )
    assert fixed != FIXTURE_FILES["inventory/storage.py"]
    _write(work_dir, "inventory/storage.py", fixed)


def _golden_04(work_dir: Path) -> None:
    """expert-04 正确终态：新增 supplier 模块（带元数据头）+ 登记文档。"""
    create_expert_fixture(work_dir)
    _write(work_dir, "inventory/supplier.py", _SUPPLIER)
    usage = FIXTURE_FILES["docs/USAGE.md"].replace(
        "- `inventory.reporting`: text stock reports", _USAGE_APPEND_CODE.strip("\n")
    )
    _write(work_dir, "docs/USAGE.md", usage)


def _golden_05(work_dir: Path) -> None:
    """expert-05 正确终态：按实际元数据头生成盘点报告。"""
    create_expert_fixture(work_dir)
    lines = ["# Inventory Module Report", ""]
    for rel, version, owner in sorted(iter_meta_headers(work_dir)):
        lines.append(f"- {rel}: version={version}, owner={owner}")
    _write(work_dir, "inventory_report.md", "\n".join(lines) + "\n")


class TestExpertTasksLoadable:
    """任务集结构与接线。"""

    def test_five_expert_tasks_loaded_with_fields(self):
        expert = [t for t in load_all_tasks() if t.difficulty == "expert"]
        assert [t.id for t in expert] == [
            "expert-01", "expert-02", "expert-03", "expert-04", "expert-05",
        ]
        for task in expert:
            assert task.timeout == 300
            assert task.setup_fn is not None
            assert task.judge_fn is not None

    def test_quick_mode_unaffected(self):
        from benchmark.tasks import load_quick_tasks

        assert all(t.difficulty == "easy" for t in load_quick_tasks())


class TestExpert01Dedup:
    def test_golden_state_passes(self, tmp_path):
        _golden_01(tmp_path)
        assert judge01("", tmp_path) is True

    def test_incomplete_refactor_rejected(self, tmp_path):
        """只建 pricing 不改原模块 → 重复定义仍在，拒绝。"""
        create_expert_fixture(tmp_path)
        _write(tmp_path, "inventory/pricing.py", _PRICING)
        assert judge01("", tmp_path) is False

    def test_pricing_without_meta_header_rejected(self, tmp_path):
        """违反 README 元数据头约定 → 拒绝。"""
        _golden_01(tmp_path)
        no_meta = _PRICING.splitlines()[1:]
        _write(tmp_path, "inventory/pricing.py", "\n".join(no_meta) + "\n")
        assert judge01("", tmp_path) is False


class TestExpert02Spec:
    def test_golden_state_passes(self, tmp_path):
        _golden_02(tmp_path)
        assert judge02("", tmp_path) is True

    def test_protected_file_modified_rejected(self, tmp_path):
        """改了 spec 禁止改动的 storage.py（顺手修 bug）→ 副作用拒绝。"""
        _golden_02(tmp_path)
        storage = FIXTURE_FILES["inventory/storage.py"].replace(
            "p.quantity > threshold", "p.quantity < threshold"
        )
        _write(tmp_path, "inventory/storage.py", storage)
        assert judge02("", tmp_path) is False

    def test_spec_violation_rejected(self, tmp_path):
        """check_alerts 缺失（只做了 CLI）→ 验收测试拒绝。"""
        create_expert_fixture(tmp_path)
        cli = FIXTURE_FILES["inventory/cli.py"].replace(
            '    sub.add_parser("report", help="print the stock report")\n',
            '    sub.add_parser("report", help="print the stock report")\n'
            '    sub.add_parser("alerts", help="print low-stock alerts")\n',
        )
        _write(tmp_path, "inventory/cli.py", cli)
        assert judge02("", tmp_path) is False


class TestExpert03Bugfix:
    def test_golden_state_passes(self, tmp_path):
        _golden_03(tmp_path)
        assert judge03("", tmp_path) is True

    def test_unfixed_rejected(self, tmp_path):
        """未修复 → 回归测试失败，拒绝（同时验证种子 bug 可复现）。"""
        create_expert_fixture(tmp_path)
        _write(tmp_path, "tests/test_storage_regression.py", REGRESSION_TEST)
        assert judge03("", tmp_path) is False


class TestExpert04ModuleAndDocs:
    def test_golden_state_passes(self, tmp_path):
        _golden_04(tmp_path)
        assert judge04("", tmp_path) is True

    def test_missing_meta_header_rejected(self, tmp_path):
        create_expert_fixture(tmp_path)
        no_meta = "\n".join(_SUPPLIER.splitlines()[1:]) + "\n"
        _write(tmp_path, "inventory/supplier.py", no_meta)
        assert judge04("", tmp_path) is False

    def test_missing_doc_entry_rejected(self, tmp_path):
        create_expert_fixture(tmp_path)
        _write(tmp_path, "inventory/supplier.py", _SUPPLIER)
        assert judge04("", tmp_path) is False


class TestExpert05Report:
    def test_golden_state_passes(self, tmp_path):
        _golden_05(tmp_path)
        assert judge05("", tmp_path) is True

    def test_incomplete_report_rejected(self, tmp_path):
        create_expert_fixture(tmp_path)
        entries = sorted(iter_meta_headers(tmp_path))
        lines = ["# Inventory Module Report", ""]
        for rel, version, owner in entries[:-1]:  # 漏掉最后一个模块
            lines.append(f"- {rel}: version={version}, owner={owner}")
        _write(tmp_path, "inventory_report.md", "\n".join(lines) + "\n")
        assert judge05("", tmp_path) is False

    def test_wrong_metadata_rejected(self, tmp_path):
        create_expert_fixture(tmp_path)
        lines = ["# Inventory Module Report", ""]
        for i, (rel, version, owner) in enumerate(iter_meta_headers(tmp_path)):
            wrong = "9.9" if i == 0 else version
            lines.append(f"- {rel}: version={wrong}, owner={owner}")
        _write(tmp_path, "inventory_report.md", "\n".join(lines) + "\n")
        assert judge05("", tmp_path) is False


class TestExpertRunnerPipeline:
    """假 Agent 走完 runner 全管线，expert 难度端到端无回归（零 API）。"""

    def test_run_all_with_expert_task(self, tmp_path):
        from benchmark.runner import BenchmarkRunner
        from benchmark.tasks import TaskDefinition

        calls: list[tuple[str, str | None]] = []

        def factory(mode, bus, cost, task=None):
            calls.append((mode, task.difficulty if task else None))
            from benchmark.metrics import TaskMetrics  # noqa: F401

            class _A:
                name = "fake"

                def run(self, task_text: str) -> str:
                    return "done 全部完成"

            return _A()

        task = TaskDefinition(
            id="expert-90",
            name="管线验证",
            description="验证管线",
            difficulty="expert",
            judge_config={"type": "contains", "values": ["done"]},
        )
        runner = BenchmarkRunner(runs=1, report_dir=str(tmp_path), agent_factory=factory)
        single, multi, report = runner.run_all([task])

        assert calls == [("single", "expert"), ("multi", "expert")]
        assert single[0].success and multi[0].success
        assert "| expert (1) |" in report.read_text(encoding="utf-8")
