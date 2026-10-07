"""Expert 层 fixture 自检测试（零 API；种子与约定的结构性验证）。"""

import json
import subprocess
import sys
from pathlib import Path

from benchmark.tasks.expert.fixture_project import (
    FIXTURE_FILES,
    REGRESSION_TEST,
    create_expert_fixture,
    iter_meta_headers,
)


def _run_pytest(work_dir: Path, *extra_args: str) -> subprocess.CompletedProcess:
    """在 work_dir 里跑 fixture 自带的 pytest（python -m pytest 注入 cwd 到 sys.path）。"""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", *extra_args],
        cwd=work_dir,
        capture_output=True,
        timeout=120,
    )


def test_fixture_builds_and_pristine_tests_pass(tmp_path):
    """构建即全绿：fixture 自身不能是坏的（v1 评测环境教训）。"""
    create_expert_fixture(tmp_path)
    result = _run_pytest(tmp_path)
    assert result.returncode == 0, result.stdout.decode("utf-8", "replace")


def test_seeded_bug_regression_fails_before_fix(tmp_path):
    """种子②：expert-03 的回归测试在 pristine fixture 上必须失败。"""
    create_expert_fixture(tmp_path)
    regression = tmp_path / "tests" / "test_storage_regression.py"
    regression.write_text(REGRESSION_TEST, encoding="utf-8", newline="\n")
    result = _run_pytest(tmp_path, "tests/test_storage_regression.py")
    assert result.returncode != 0


def test_duplicated_money_formatting_seeded(tmp_path):
    """种子①：_format_money 在 services 与 reporting 各一份。"""
    create_expert_fixture(tmp_path)
    services = (tmp_path / "inventory" / "services.py").read_text(encoding="utf-8")
    reporting = (tmp_path / "inventory" / "reporting.py").read_text(encoding="utf-8")
    assert "def _format_money" in services
    assert "def _format_money" in reporting


def test_meta_headers_parseable(tmp_path):
    """种子③：inventory/ 包内全部模块的元数据头可解析。"""
    create_expert_fixture(tmp_path)
    entries = {rel: (version, owner) for rel, version, owner in iter_meta_headers(tmp_path)}
    assert set(entries) == {
        "inventory/__init__.py",
        "inventory/models.py",
        "inventory/storage.py",
        "inventory/services.py",
        "inventory/reporting.py",
        "inventory/cli.py",
    }
    assert entries["inventory/storage.py"] == ("1.1", "bob")
    assert entries["inventory/services.py"] == ("1.2", "carol")


def test_build_is_deterministic(tmp_path):
    """两次构建逐字节一致（expert-02 副作用检查的前提）。"""
    first, second = tmp_path / "a", tmp_path / "b"
    create_expert_fixture(first)
    create_expert_fixture(second)
    for rel in FIXTURE_FILES:
        assert (first / rel).read_bytes() == (second / rel).read_bytes()


def test_storage_file_is_plain_json_list(tmp_path):
    """storage 产物是普通的 JSON 对象数组（judge 可直接手写该格式）。"""
    create_expert_fixture(tmp_path)
    script = (
        "from inventory.models import Product\n"
        "from inventory.storage import save_products\n"
        "save_products([Product('p1', 'Widget', 25, 3.5)])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    payload = json.loads((tmp_path / "products.json").read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload[0]["name"] == "Widget"
