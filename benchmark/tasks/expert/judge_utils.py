"""Expert 层 judge 共用的 subprocess 探针。

判据原则（ADR-008，范式借自 AppWorld 状态单测）：
- 行为验证用真实执行（pytest / import 探针），只看返回码或
  ASCII 输出，规避 Windows 控制台编码差异；
- 全部探针带超时，且在 runner 的 worker 线程内运行——
  任务级 timeout 仍是最终兜底。
"""

import subprocess
import sys
from pathlib import Path


def run_python(
    work_dir: Path, script: str, timeout: int = 60
) -> subprocess.CompletedProcess:
    """在 work_dir 中执行一段 Python（import / 行为探针）。"""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=work_dir,
        capture_output=True,
        timeout=timeout,
    )


def run_pytest(
    work_dir: Path, *targets: str, timeout: int = 180
) -> subprocess.CompletedProcess:
    """在 work_dir 中跑 pytest。

    ``python -m pytest`` 会把 cwd 注入 sys.path，work_dir 下的
    inventory 包可以直接被导入；targets 为空时跑 tests/ 全量。
    """
    args = [sys.executable, "-m", "pytest", *(targets or ["tests/"]), "-q"]
    return subprocess.run(
        args,
        cwd=work_dir,
        capture_output=True,
        timeout=timeout,
    )
