"""expert-04 按约定扩展模块 + 文档（假设 H1：writer 角色首次进 benchmark）。

考察"读懂项目约定并遵守"：元数据头、dataclass 的 to_dict/from_dict、
存储函数带可选 path 参数——全部来自 README.md 与现有模块的既有写法。
"""

from pathlib import Path

from benchmark.tasks.expert.fixture_project import create_expert_fixture
from benchmark.tasks.expert.judge_utils import run_python

TASK = {
    "id": "expert-04",
    "name": "按约定新增模块并补文档",
    "description": (
        "参照项目既有约定（见 README.md 与现有模块的写法），新增 inventory/supplier.py："
        "定义 Supplier 数据类（字段 supplier_id、name、email，提供 to_dict 与 "
        "from_dict），并提供 load_suppliers(path=...) 与 save_suppliers(suppliers, "
        "path=...) 两个 JSON 存取函数（默认文件 suppliers.json）；新模块按约定添加"
        "元数据头。然后在 docs/USAGE.md 的 Modules 清单登记新模块，并补充一小节使用"
        "示例。"
    ),
    "difficulty": "expert",
    "timeout": 300,
    "judge": {
        "type": "custom",
    },
}

_PROBE = (
    "from pathlib import Path\n"
    "from inventory.supplier import Supplier, load_suppliers, save_suppliers\n"
    "s = Supplier('s1', 'Acme', 'a@acme.io')\n"
    "path = Path('suppliers.json')\n"
    "save_suppliers([s], path)\n"
    "loaded = load_suppliers(path)\n"
    "assert loaded[0] == s\n"
    "print('OK')\n"
)


def setup(work_dir: Path) -> None:
    create_expert_fixture(work_dir)


def judge(agent_output: str, work_dir: Path) -> bool:
    """判据：模块合规（含元数据头约定）+ 真实导入与存取探针 + 文档登记。"""
    supplier = work_dir / "inventory" / "supplier.py"
    if not supplier.exists():
        return False
    try:
        content = supplier.read_text(encoding="utf-8")
    except Exception:
        return False
    if "class Supplier" not in content:
        return False
    if "def load_suppliers" not in content or "def save_suppliers" not in content:
        return False
    if not content.splitlines()[0].startswith("# meta: version="):
        return False

    # 真实导入 + 存取回环（Agent 实现的模块在包语境下可用）
    probe = run_python(work_dir, _PROBE)
    if probe.returncode != 0 or b"OK" not in probe.stdout:
        return False

    # 文档：登记新模块 + 原有内容保留
    usage_file = work_dir / "docs" / "USAGE.md"
    if not usage_file.exists():
        return False
    usage = usage_file.read_text(encoding="utf-8").lower()
    return "supplier" in usage and "inventory.models" in usage and "## modules" in usage
