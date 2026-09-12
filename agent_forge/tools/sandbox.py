"""工具沙箱 —— 线程局部的工作区根目录约束

所有文件类工具（read_file / write_file / grep_search）和 shell 工具
都通过本模块确定"当前线程允许操作的根目录"：

- 默认（未设置沙箱根）：使用进程当前工作目录 Path.cwd()
- Benchmark / Dashboard 等场景调用 set_sandbox_root(work_dir) 后，
  相对路径锚定到沙箱根，越界的绝对路径与 ".." 逃逸一律拒绝

为什么用 threading.local？
- os.chdir 是进程全局状态，多线程并发跑任务时互相踩踏
  （benchmark runner 曾用全局 chdir + 锁，任务执行期仍会串目录）
- 线程局部让每个任务线程拥有独立的沙箱根，天然并发安全，
  也让 runner 能用 worker 线程实现任务级超时而不污染主线程

设计原则：
- 沙箱是第一层防线：拒绝"明显越界"的路径访问与敏感文件读取
- 不伪装成完整安全边界——生产环境仍需容器级隔离（见 ADR-004）
"""

import os
import threading
from pathlib import Path

# 线程局部的沙箱根目录（None 表示未设置，回退到进程 cwd）
_local = threading.local()

# 受保护的敏感文件前缀（任意目录层级下都不允许读写）
# .env 中的 API Key 等机密不应进入 Agent 上下文
_SENSITIVE_FILE_PREFIXES = (".env",)


def set_sandbox_root(path: str | Path) -> None:
    """设置当前线程的沙箱根目录。

    Args:
        path: 工作区根目录（通常是任务的工作目录或项目根目录）。
    """
    _local.root = Path(path).resolve()


def get_sandbox_root() -> Path:
    """获取当前线程的沙箱根目录。

    未设置时返回进程当前工作目录的绝对路径（secure-by-default：
    工具默认只能访问 cwd 下的文件）。
    """
    root = getattr(_local, "root", None)
    if root is not None:
        return root
    return Path.cwd().resolve()


def clear_sandbox_root() -> None:
    """清除当前线程的沙箱根设置（回退到进程 cwd）。"""
    _local.root = None


def is_sensitive_file(path: Path) -> bool:
    """判断路径是否为受保护的敏感文件（.env / .env.local 等）。"""
    return path.name.startswith(_SENSITIVE_FILE_PREFIXES)


def resolve_in_sandbox(path: str | Path) -> tuple[Path, str | None]:
    """将工具入参路径解析到沙箱内并做安全校验。

    规则：
    1. 相对路径锚定沙箱根（而非进程 cwd）
    2. 解析（含 .. 收敛）后必须仍位于沙箱根内，否则拒绝
    3. 敏感文件（.env*）无论位置一律拒绝

    Args:
        path: 工具入参的原始路径。

    Returns:
        (解析后的绝对路径, 错误信息) 元组。
        错误信息为 None 表示校验通过；否则为可直接返回给 LLM 的
        描述性错误串。
    """
    root = get_sandbox_root()
    raw = Path(path)

    if not raw.is_absolute():
        raw = root / raw

    resolved = raw.resolve()

    # Windows 文件系统大小写不敏感，比较前统一大小写
    resolved_n = os.path.normcase(str(resolved))
    root_n = os.path.normcase(str(root))
    if resolved_n != root_n and not resolved_n.startswith(root_n + os.sep):
        return resolved, (
            f"错误：路径 '{path}' 超出沙箱根目录 '{root}'，已拒绝访问。\n"
            f"工具只能访问工作区内的文件（相对路径或沙箱根下的绝对路径）。"
        )

    if is_sensitive_file(resolved):
        return resolved, (
            f"错误：'{resolved.name}' 是受保护的敏感文件，拒绝访问。\n"
            f"环境变量中的 API Key 等机密信息不应进入 Agent 上下文。"
        )

    return resolved, None
