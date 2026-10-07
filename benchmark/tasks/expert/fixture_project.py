"""Expert 层 fixture——确定性迷你"库存管理"应用（ADR-008）。

设计约束：
- 内容全部写死（无随机、无时间戳），多次构建逐字节一致——
  副作用检查（expert-02）依赖这个性质
- 种子① 重复代码：``_format_money`` 在 services.py 与
  reporting.py 各一份（expert-01 去重目标）
- 种子② bug：storage.find_low_stock 用 ``>`` 实现"below"语义
  （docstring 与实现不符的典型遗留缺陷），症状表现在报表的
  低库存清单——pristine 测试不测该边界所以全绿；expert-03 的
  setup 额外写入回归测试（修复前必须失败）
- 种子③ 元数据头：每个源文件首行 ``# meta: version=x owner=y``
  （expert-05 盘点任务的 ground truth 来源）
- 全 ASCII 数据（产品名等），judge 的 subprocess 断言只看
  返回码或 ASCII 输出，规避 Windows 控制台编码问题
"""

from pathlib import Path

# 元数据头行格式：# meta: version=<x> owner=<name>
_META_PREFIX = "# meta: version="


def _meta(version: str, owner: str) -> str:
    return f"{_META_PREFIX}{version} owner={owner}"


# 相对路径 → 文件内容。新增文件时保持"首行元数据头"的约定。
FIXTURE_FILES: dict[str, str] = {
    # ── inventory 包 ──────────────────────────────────────
    "inventory/__init__.py": (
        f'{_meta("1.0", "alice")}\n'
        '"""Inventory management mini-application."""\n'
        "\n"
        '__all__ = ["models", "storage", "services", "reporting", "cli"]\n'
    ),
    "inventory/models.py": (
        f'{_meta("1.0", "alice")}\n'
        '"""Data models for the inventory app."""\n'
        "from __future__ import annotations\n"
        "\n"
        "from dataclasses import asdict, dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Product:\n"
        '    """A product kept in stock."""\n'
        "\n"
        "    product_id: str\n"
        "    name: str\n"
        "    quantity: int\n"
        "    price: float\n"
        "\n"
        "    def to_dict(self) -> dict:\n"
        "        return asdict(self)\n"
        "\n"
        "    @classmethod\n"
        '    def from_dict(cls, data: dict) -> "Product":\n'
        "        return cls(\n"
        '            product_id=data["product_id"],\n'
        '            name=data["name"],\n'
        '            quantity=int(data["quantity"]),\n'
        '            price=float(data["price"]),\n'
        "        )\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Order:\n"
        '    """A purchase order against one product."""\n'
        "\n"
        "    order_id: str\n"
        "    product_id: str\n"
        "    quantity: int\n"
        "\n"
        "    def to_dict(self) -> dict:\n"
        "        return asdict(self)\n"
        "\n"
        "    @classmethod\n"
        '    def from_dict(cls, data: dict) -> "Order":\n'
        "        return cls(\n"
        '            order_id=data["order_id"],\n'
        '            product_id=data["product_id"],\n'
        '            quantity=int(data["quantity"]),\n'
        "        )\n"
    ),
    # 种子②：find_low_stock 的实现用 >，与 docstring 的 below 语义相反。
    "inventory/storage.py": (
        f'{_meta("1.1", "bob")}\n'
        '"""JSON file storage for products."""\n'
        "from __future__ import annotations\n"
        "\n"
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        "from inventory.models import Product\n"
        "\n"
        'STORAGE_FILE = Path("products.json")\n'
        "\n"
        "\n"
        'def load_products(path: Path = STORAGE_FILE) -> list[Product]:\n'
        '    """Load all products from the JSON storage file."""\n'
        "    if not path.exists():\n"
        "        return []\n"
        '    raw = json.loads(path.read_text(encoding="utf-8"))\n'
        "    return [Product.from_dict(item) for item in raw]\n"
        "\n"
        "\n"
        "def save_products(products: list[Product], path: Path = STORAGE_FILE) -> None:\n"
        '    """Persist all products to the JSON storage file."""\n'
        "    payload = [p.to_dict() for p in products]\n"
        '    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")\n'
        "\n"
        "\n"
        "def find_product(products: list[Product], product_id: str) -> Product | None:\n"
        '    """Return the product with the given id, or None."""\n'
        "    for product in products:\n"
        "        if product.product_id == product_id:\n"
        "            return product\n"
        "    return None\n"
        "\n"
        "\n"
        "def find_low_stock(products: list[Product], threshold: int) -> list[Product]:\n"
        '    """Return products whose stock quantity is below ``threshold``."""\n'
        "    # Legacy note: reporting depends on this query; keep the\n"
        '    # "strictly related to the low-stock report" behavior.\n'
        "    return [p for p in products if p.quantity > threshold]\n"
    ),
    # 种子①：_format_money 第一份（第二份在 reporting.py）。
    "inventory/services.py": (
        f'{_meta("1.2", "carol")}\n'
        '"""Business logic: purchasing, order totals and discounts."""\n'
        "from __future__ import annotations\n"
        "\n"
        "from pathlib import Path\n"
        "\n"
        "from inventory.models import Order, Product\n"
        "from inventory.storage import STORAGE_FILE, find_product, load_products, save_products\n"
        "\n"
        "VOLUME_DISCOUNT_RATE = 0.9  # 10% off orders of 10+ units\n"
        "\n"
        "\n"
        'def _format_money(amount: float) -> str:\n'
        '    """Format an amount as CNY currency, e.g. ``1,234.50 CNY``."""\n'
        '    return "CNY " + f"{amount:,.2f}"\n'
        "\n"
        "\n"
        "def add_product(product: Product, path: Path = STORAGE_FILE) -> None:\n"
        '    """Insert a product, or replace it if the id already exists."""\n'
        "    products = load_products(path)\n"
        "    products = [p for p in products if p.product_id != product.product_id]\n"
        "    products.append(product)\n"
        "    save_products(products, path)\n"
        "\n"
        "\n"
        "def purchase(product_id: str, quantity: int, path: Path = STORAGE_FILE) -> Product:\n"
        '    """Deduct stock for a purchase.\n'
        "\n"
        '    Raises ValueError on unknown product or insufficient stock.\n'
        '    """\n'
        "    products = load_products(path)\n"
        "    product = find_product(products, product_id)\n"
        "    if product is None:\n"
        '        raise ValueError(f"unknown product: {product_id}")\n'
        "    if product.quantity < quantity:\n"
        '        raise ValueError(f"insufficient stock for {product_id}")\n'
        "    product.quantity -= quantity\n"
        "    save_products(products, path)\n"
        "    return product\n"
        "\n"
        "\n"
        "def order_total(order: Order, path: Path = STORAGE_FILE) -> str:\n"
        '    """Total price string for an order; volume discount at 10+ units."""\n'
        "    products = load_products(path)\n"
        "    product = find_product(products, order.product_id)\n"
        "    if product is None:\n"
        '        raise ValueError(f"unknown product: {order.product_id}")\n'
        "    total = product.price * order.quantity\n"
        "    if order.quantity >= 10:\n"
        "        total *= VOLUME_DISCOUNT_RATE\n"
        "    return _format_money(total)\n"
    ),
    # 种子①：_format_money 第二份；低库存清单经由 find_low_stock（种子②症状处）。
    "inventory/reporting.py": (
        f'{_meta("1.0", "dave")}\n'
        '"""Human-readable stock reports."""\n'
        "from __future__ import annotations\n"
        "\n"
        "from pathlib import Path\n"
        "\n"
        "from inventory.storage import STORAGE_FILE, find_low_stock, load_products\n"
        "\n"
        "LOW_STOCK_THRESHOLD = 10\n"
        "\n"
        "\n"
        'def _format_money(amount: float) -> str:\n'
        '    """Format an amount as CNY currency, e.g. ``1,234.50 CNY``."""\n'
        '    return "CNY " + f"{amount:,.2f}"\n'
        "\n"
        "\n"
        "def stock_report(path: Path = STORAGE_FILE) -> str:\n"
        '    """Render a text report: inventory table + low-stock section."""\n'
        "    products = load_products(path)\n"
        '    lines = ["== Stock Report ==", ""]\n'
        "    total_value = 0.0\n"
        "    for product in sorted(products, key=lambda p: p.name):\n"
        "        value = product.quantity * product.price\n"
        "        total_value += value\n"
        "        lines.append(\n"
        '            f"- {product.name} (#{product.product_id}): "\n'
        '            f"qty={product.quantity}, "\n'
        '            f"price={_format_money(product.price)}, "\n'
        '            f"value={_format_money(value)}"\n'
        "        )\n"
        '    lines.append("")\n'
        '    lines.append(f"Total inventory value: {_format_money(total_value)}")\n'
        '    lines.append("")\n'
        "    low = find_low_stock(products, LOW_STOCK_THRESHOLD)\n"
        '    lines.append(f"== Low stock (below {LOW_STOCK_THRESHOLD}) ==")\n'
        "    if low:\n"
        "        for product in low:\n"
        '            lines.append(f"- {product.name}: qty={product.quantity}")\n'
        "    else:\n"
        '        lines.append("(none)")\n'
        '    return "\\n".join(lines)\n'
    ),
    "inventory/cli.py": (
        f'{_meta("1.0", "erin")}\n'
        '"""Command line interface for the inventory app."""\n'
        "from __future__ import annotations\n"
        "\n"
        "import argparse\n"
        "\n"
        "from inventory.models import Order\n"
        "from inventory.reporting import stock_report\n"
        "from inventory.services import order_total\n"
        "\n"
        "\n"
        "def main(argv: list[str] | None = None) -> int:\n"
        '    """Entry point; returns a process exit code."""\n'
        '    parser = argparse.ArgumentParser(prog="inventory")\n'
        '    sub = parser.add_subparsers(dest="command", required=True)\n'
        "\n"
        '    sub.add_parser("report", help="print the stock report")\n'
        "\n"
        '    p_order = sub.add_parser("order-total", help="total price of an order")\n'
        '    p_order.add_argument("order_id")\n'
        '    p_order.add_argument("product_id")\n'
        '    p_order.add_argument("quantity", type=int)\n'
        "\n"
        "    args = parser.parse_args(argv)\n"
        '    if args.command == "report":\n'
        "        print(stock_report())\n"
        "        return 0\n"
        '    if args.command == "order-total":\n'
        '        order = Order(args.order_id, args.product_id, args.quantity)\n'
        "        print(order_total(order))\n"
        "        return 0\n"
        "    return 1\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n"
    ),
    # ── tests（pristine 全绿；不测 find_low_stock 的边界语义）──
    "tests/test_storage.py": (
        f'{_meta("1.0", "frank")}\n'
        '"""Storage round-trip tests."""\n'
        "from pathlib import Path\n"
        "\n"
        "from inventory.models import Product\n"
        "from inventory.storage import load_products, save_products\n"
        "\n"
        "\n"
        "def test_save_and_load_roundtrip(tmp_path: Path):\n"
        '    path = tmp_path / "products.json"\n'
        "    products = [\n"
        '        Product("p1", "Widget", 25, 3.5),\n'
        '        Product("p2", "Gadget", 4, 19.99),\n'
        "    ]\n"
        "    save_products(products, path)\n"
        "    assert load_products(path) == products\n"
    ),
    "tests/test_services.py": (
        f'{_meta("1.0", "frank")}\n'
        '"""Business logic tests."""\n'
        "from pathlib import Path\n"
        "\n"
        "import pytest\n"
        "\n"
        "from inventory.models import Order, Product\n"
        "from inventory.services import add_product, order_total, purchase\n"
        "\n"
        "\n"
        "def _seed(path: Path) -> None:\n"
        '    add_product(Product("p1", "Widget", 25, 3.5), path)\n'
        '    add_product(Product("p2", "Gadget", 4, 19.99), path)\n'
        "\n"
        "\n"
        "def test_purchase_deducts_stock(tmp_path: Path):\n"
        '    path = tmp_path / "products.json"\n'
        "    _seed(path)\n"
        '    assert purchase("p1", 5, path).quantity == 20\n'
        "\n"
        "\n"
        "def test_purchase_insufficient_stock_raises(tmp_path: Path):\n"
        '    path = tmp_path / "products.json"\n'
        "    _seed(path)\n"
        "    with pytest.raises(ValueError):\n"
        '        purchase("p1", 999, path)\n'
        "\n"
        "\n"
        "def test_order_total_formats_currency(tmp_path: Path):\n"
        '    path = tmp_path / "products.json"\n'
        "    _seed(path)\n"
        '    assert order_total(Order("o1", "p1", 2), path) == "CNY 7.00"\n'
        "\n"
        "\n"
        "def test_order_total_volume_discount(tmp_path: Path):\n"
        '    path = tmp_path / "products.json"\n'
        "    _seed(path)\n"
        "    # 3.5 * 12 * 0.9 = 37.8\n"
        '    assert order_total(Order("o2", "p1", 12), path) == "CNY 37.80"\n'
    ),
    "tests/test_reporting.py": (
        f'{_meta("1.0", "frank")}\n'
        '"""Report rendering tests."""\n'
        "from pathlib import Path\n"
        "\n"
        "from inventory.models import Product\n"
        "from inventory.reporting import stock_report\n"
        "from inventory.services import add_product\n"
        "\n"
        "\n"
        "def test_report_lists_products_and_value(tmp_path: Path):\n"
        '    path = tmp_path / "products.json"\n'
        '    add_product(Product("p1", "Widget", 25, 3.5), path)\n'
        "    report = stock_report(path)\n"
        '    assert "Widget" in report\n'
        '    assert "CNY 87.50" in report\n'
        '    assert "Total inventory value: CNY 87.50" in report\n'
        "\n"
        "\n"
        "def test_report_has_low_stock_section(tmp_path: Path):\n"
        '    path = tmp_path / "products.json"\n'
        '    add_product(Product("p1", "Widget", 25, 3.5), path)\n'
        "    assert \"Low stock (below 10)\" in stock_report(path)\n"
    ),
    # ── 文档与规格 ─────────────────────────────────────────
    "docs/USAGE.md": (
        "# Usage\n"
        "\n"
        "The `inventory` package manages products, orders and stock reports.\n"
        "\n"
        "## Command line\n"
        "\n"
        "```bash\n"
        "python -m inventory.cli report\n"
        "python -m inventory.cli order-total o1 p1 12\n"
        "```\n"
        "\n"
        "## Library\n"
        "\n"
        "```python\n"
        "from inventory.models import Product\n"
        "from inventory.services import add_product, purchase\n"
        "from inventory.reporting import stock_report\n"
        "\n"
        'add_product(Product("p1", "Widget", 25, 3.5))\n'
        "print(stock_report())\n"
        "```\n"
        "\n"
        "## Modules\n"
        "\n"
        "- `inventory.models`: Product / Order dataclasses\n"
        "- `inventory.storage`: JSON file persistence\n"
        "- `inventory.services`: purchasing and order totals\n"
        "- `inventory.reporting`: text stock reports\n"
    ),
    # expert-02 的规格：hidden 验收测试的契约来源。
    "spec.md": (
        "# Spec: Low-stock alerts\n"
        "\n"
        "Add a low-stock alert feature spanning `services` and `cli`.\n"
        "\n"
        "## services.check_alerts\n"
        "\n"
        "In `inventory/services.py` add:\n"
        "\n"
        "    def check_alerts(threshold: int = 10, path: Path = STORAGE_FILE) -> list[dict]\n"
        "\n"
        "- Considers every product in storage.\n"
        "- A product is an alert when `quantity < threshold`.\n"
        "- Each alert is a dict with keys: `product_id`, `name`, `quantity`, `level`.\n"
        '- `level` is `"critical"` when `quantity < 5`, otherwise `"warning"`.\n'
        "- Alerts are sorted by `quantity` ascending.\n"
        "\n"
        "## cli `alerts` subcommand\n"
        "\n"
        "`python -m inventory.cli alerts` prints one line per alert:\n"
        "\n"
        "    CRITICAL: <name> (<quantity>)\n"
        "    WARNING: <name> (<quantity>)\n"
        "\n"
        "Level text is upper-cased; lines follow the order of `check_alerts`.\n"
        "With no alerts, print nothing and exit 0.\n"
        "\n"
        "## Constraints\n"
        "\n"
        "- models, storage, reporting and the existing tests must keep passing\n"
        "  unchanged.\n"
        "- Reuse the storage helpers; do not read or write JSON directly.\n"
    ),
    "README.md": (
        "# Inventory (benchmark fixture)\n"
        "\n"
        "A tiny inventory-management application.\n"
        "\n"
        "## Conventions\n"
        "\n"
        "- Every source file starts with a metadata header comment:\n"
        "  `# meta: version=<x> owner=<name>`. Add it to new modules.\n"
        "- Dataclasses live in `inventory.models` and offer\n"
        "  `to_dict` / `from_dict`.\n"
        "- Persistence helpers accept an optional `path` argument\n"
        "  and default to the module-level storage file.\n"
        "- Public functions have docstrings; tests live in `tests/`.\n"
    ),
}

# expert-02 副作用检查的保护清单：spec.md 约束"models/storage/reporting、
# 现有测试与文档不得改动"——services.py 与 cli.py 是该功能的目标文件，
# 不在保护之列。
PROTECTED_FILES: tuple[str, ...] = (
    "inventory/__init__.py",
    "inventory/models.py",
    "inventory/storage.py",
    "inventory/reporting.py",
    "tests/test_storage.py",
    "tests/test_services.py",
    "tests/test_reporting.py",
    "docs/USAGE.md",
    "spec.md",
    "README.md",
)

# expert-03 的回归测试（setup 额外写入；修复前必须失败）。
REGRESSION_TEST = (
    f'{_meta("1.0", "grace")}\n'
    '"""Regression test: low-stock boundary semantics."""\n'
    "\n"
    "from inventory.models import Product\n"
    "from inventory.storage import find_low_stock\n"
    "\n"
    "\n"
    "def test_low_stock_returns_only_below_threshold():\n"
    "    products = [\n"
    '        Product("p1", "Low", 5, 1.0),\n'
    '        Product("p2", "High", 50, 1.0),\n'
    "    ]\n"
    "    result = find_low_stock(products, 10)\n"
    '    assert [p.product_id for p in result] == ["p1"]\n'
)


def create_expert_fixture(work_dir: Path) -> None:
    """把 fixture 写入 work_dir（内容确定性，多次构建逐字节一致）。"""
    for rel_path, content in FIXTURE_FILES.items():
        target = work_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def iter_meta_headers(work_dir: Path) -> list[tuple[str, str, str]]:
    """解析 inventory/ 包内各 .py 模块首行的元数据头。

    返回 (相对路径, version, owner) 列表，按路径排序；
    缺失/格式不符的文件被跳过（由调用方决定算不算失败）。
    expert-05 的 judge 以此重算 ground truth。
    """
    entries: list[tuple[str, str, str]] = []
    package_dir = work_dir / "inventory"
    if not package_dir.is_dir():
        return entries
    for py_file in sorted(package_dir.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            first_line = py_file.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            continue
        if not first_line.startswith(_META_PREFIX):
            continue
        rest = first_line[len(_META_PREFIX):]
        parts = rest.split(" owner=")
        if len(parts) != 2:
            continue
        rel = py_file.relative_to(work_dir).as_posix()
        entries.append((rel, parts[0].strip(), parts[1].strip()))
    return entries
