"""Shell 命令执行工具

让 Agent 能够执行系统命令——这是 Agent 从"聊天机器人"变成"AI 程序员"
的关键一步。有了 Shell 执行能力，Agent 可以：
    - 查看目录结构（ls / dir）
    - 运行 Python 脚本
    - 执行 git 命令（查看状态、查看日志）
    - 搜索文件内容（grep）

⚠️ 安全是首要考虑：
    本工具内建了命令黑名单机制，防止 Agent 意外执行破坏性操作。
    但这不能替代 sandbox——生产环境请配合 Docker 容器隔离使用。
"""

import platform
import re
import subprocess

from langchain_core.tools import tool

# ─── 平台检测 ────────────────────────────────────────────────
_IS_WINDOWS = platform.system() == "Windows"

# Windows 下常见 Linux 命令的自动别名映射。
# LLM 默认生成 Linux 命令，在 Windows 上会失败并浪费工具调用轮次。
# 这里在命令开头做简单替换，让 Agent 无需关心平台差异。
_WINDOWS_ALIASES: dict[str, str] = {
    "ls -la": "dir",
    "ls -l":  "dir",
    "ls -a":  "dir",
    "ls":     "dir",
    "pwd":    "cd",
    "which":  "where",
    "cat ":   "type ",
    "cp ":    "copy ",
    "mv ":    "move ",
    "mkdir -p": "mkdir",
}

# ─── 安全配置 ────────────────────────────────────────────
# 这些命令被完全禁止，即使 Agent 请求也会拒绝执行。
# 设计原则：宁可拒绝一个合法请求，也不允许一次意外破坏。
#
# 注意：黑名单不是银弹——真正安全需要 sandbox（Docker/虚拟机）。
# 这里只是第一层防线。
FORBIDDEN_COMMANDS: list[str] = [
    "rm -rf",       # 递归强制删除（Linux/macOS）
    "del /f",       # 强制删除（Windows）
    "format",       # 磁盘格式化
    "mkfs",         # 创建文件系统（会覆盖分区）
    "dd if=",       # 磁盘写入（dd 的破坏性用法）
    "shutdown",     # 关机
    "reboot",       # 重启
    "halt",         # 停机
    ":(){ :|:& };:",  # Fork 炸弹（经典 DoS 攻击）
    "chmod 777",    # 全局可写（安全风险）
]

# 输出字符上限：防止 Agent 执行 cat 大文件导致上下文溢出
MAX_OUTPUT_CHARS: int = 10000

# 命令超时时间（秒）
COMMAND_TIMEOUT: int = 30


@tool
def run_shell(command: str) -> str:
    """执行 Shell 命令并返回标准输出和标准错误。

    适用场景：
        - 查看项目结构：ls, dir, tree
        - 运行代码：python script.py
        - 版本控制：git status, git log --oneline
        - 搜索文件：grep pattern file.txt
        - 系统信息：pwd, whoami, date

    安全限制：
        - 危险命令自动拦截（rm -rf, format, shutdown 等）
        - 命令执行超时 30 秒自动终止
        - 输出超过 10,000 字符自动截断
        - 在当前工作目录下执行（即 Python 进程的 cwd，非固定项目目录）

    注意：
        本工具在 Agent 运行时的工作目录下执行命令。
        如需切换目录，请在命令中使用 cd。

    Args:
        command: 要执行的 Shell 命令字符串。
                 支持管道 (|)、重定向 (>)、串联 (&&) 等标准 Shell 语法。

    Returns:
        - 成功：标准输出 + 标准错误（组合在一条消息中）
        - 被拦截：安全警告消息，说明被拦截的原因
        - 超时：超时错误消息
        - 执行失败：错误描述

    Example:
        >>> run_shell.invoke({"command": "ls -la"})
        'total 48\ndrwxr-xr-x ...'

        >>> run_shell.invoke({"command": "rm -rf /"})
        '安全拦截：命令包含禁止操作 'rm -rf'。如需执行，请人工确认。'
    """
    # ── 第零层：Windows 命令别名自动映射 ──
    # LLM 常生成 Linux 命令，在此自动转换为 Windows 等效命令
    if _IS_WINDOWS:
        command_stripped = command.strip()
        for linux_cmd, win_cmd in _WINDOWS_ALIASES.items():
            if command_stripped == linux_cmd or command_stripped.startswith(linux_cmd + " "):
                command = command_stripped.replace(linux_cmd, win_cmd, 1)
                break

    # ── 第一层：黑名单检查 ──
    # 归一化空白字符：将连续空格/tab压缩为单个空格，防止 "rm  -rf" 绕过 "rm -rf" 匹配
    command_lower = command.lower()
    command_normalized = re.sub(r'\s+', ' ', command_lower.strip())
    for forbidden in FORBIDDEN_COMMANDS:
        if forbidden in command_normalized:
            return (
                f"🛑 安全拦截：命令包含禁止操作 '{forbidden}'。\n"
                f"   被拦截的命令：{command[:100]}\n"
                f"   如需执行此类操作，请人工在终端中确认后执行。"
            )

    # ── 第二层：执行命令 ──
    try:
        result = subprocess.run(
            command,
            shell=True,              # 支持管道等 Shell 语法
            capture_output=True,      # 捕获 stdout 和 stderr
            text=True,                # 以文本模式返回（而非 bytes）
            encoding="utf-8",         # 显式使用 UTF-8，避免 Windows 默认 GBK 解码失败
            errors="replace",         # 无法解码的字符替换为 ?，不抛异常
            timeout=COMMAND_TIMEOUT,  # 超时保护
            # cwd="." 表示 Python 进程的当前工作目录，不一定是项目根目录
            cwd=".",
        )

        # 组合 stdout 和 stderr
        output = result.stdout
        if result.stderr:
            if output:
                output += "\n"
            output += f"[stderr]\n{result.stderr}"

        # ── 第三层：输出截断 ──
        if len(output) > MAX_OUTPUT_CHARS:
            truncated_output = output[:MAX_OUTPUT_CHARS]
            return (
                f"{truncated_output}\n"
                f"...\n"
                f"[输出已截断：原始输出 {len(output)} 字符，"
                f"超过 {MAX_OUTPUT_CHARS} 字符上限]"
            )

        # 命令成功但无输出（如 mkdir、touch 成功时没有 stdout）
        if not output:
            return f"命令执行成功（返回码 {result.returncode}），无输出。"

        return output

    except subprocess.TimeoutExpired:
        return (
            f"错误：命令执行超时（{COMMAND_TIMEOUT} 秒）。\n"
            f"   被终止的命令：{command[:100]}\n"
            f"   如果这是合理的长耗时操作，请在终端中手动执行。"
        )
    except FileNotFoundError:
        return (
            f"错误：找不到要执行的命令。\n"
            f"   命令：{command[:100]}\n"
            f"   请确认命令名拼写正确且已安装在系统中。"
        )
    except Exception as e:
        return f"执行命令时发生未知错误：{type(e).__name__}: {e}"
