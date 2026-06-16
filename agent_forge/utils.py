"""通用工具函数

从 demos/phase0_agent_demo.py 中提取的共享工具，
供 agent_forge 核心库和 demos 共同使用。

提取原则：
    如果同一个函数在两个以上文件中出现，就应该提取到公共模块。
    safe_print 在 phase0_demo 中定义，现在 bus/bus.py 和 agents/base.py 也需要它。
"""

import builtins as _builtins


def safe_print(*args, **kwargs) -> None:
    """Windows GBK 终端兼容的打印函数。

    在 Windows 中文终端（GBK 编码）下，emoji 等 Unicode 字符
    会触发 UnicodeEncodeError。本函数在打印失败时自动降级为纯 ASCII。

    为什么不用 sys.stdout.encoding 检测？
    - 有些 IDE（如 VS Code）的终端虽然是 UTF-8，但 Python 检测为 GBK
    - try/except 是最可靠的方案：能打就打，不能打就降级
    """
    try:
        _builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = []
        for arg in args:
            if isinstance(arg, str):
                safe_args.append(arg.encode("ascii", errors="replace").decode("ascii"))
            else:
                safe_args.append(arg)
        try:
            _builtins.print(*safe_args, **kwargs)
        except Exception:
            pass


def print_separator(title: str, width: int = 60) -> None:
    """打印带标题的分隔线。"""
    safe_print("=" * width)
    safe_print(title)
    safe_print("=" * width)


def print_info(msg: str) -> None:
    """打印信息行。"""
    safe_print(f"[INFO] {msg}")
