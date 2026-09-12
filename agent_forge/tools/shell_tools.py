"""Shell 命令执行工具

让 Agent 能够执行系统命令——这是 Agent 从"聊天机器人"变成"AI 程序员"
的关键一步。有了 Shell 执行能力，Agent 可以：
    - 查看目录结构（ls / dir）
    - 运行 Python 脚本
    - 执行 git 命令（查看状态、查看日志）
    - 搜索文件内容（grep）

⚠️ 安全是首要考虑：
    本工具内建多层防线（命令黑名单 + 沙箱 cwd + 超时 + 输出截断），
    防止 Agent 意外执行破坏性操作。
    但黑名单无法防御所有变体（例如 `python -c "import shutil; ..."`），
    生产环境请配合 Docker 容器隔离使用（见 ADR-004）。
"""

import platform
import re
import subprocess

from langchain_core.tools import tool

from agent_forge.tools.sandbox import get_sandbox_root

# ─── 平台检测 ────────────────────────────────────────────────
_IS_WINDOWS = platform.system() == "Windows"

# Windows 下常见 Linux 命令的自动别名映射。
# LLM 默认生成 Linux 命令，在 Windows 上会失败并浪费工具调用轮次。
# 这里在命令开头做简单替换，让 Agent 无需关心平台差异。
# 注意：键不带尾随空格，匹配时用 `== 键` 或 `以 "键 + 空格" 开头`。
_WINDOWS_ALIASES: dict[str, str] = {
    "ls -la": "dir",
    "ls -l":  "dir",
    "ls -a":  "dir",
    "ls":     "dir",
    "pwd":    "cd",
    "which":  "where",
    "cat":    "type",
    "cp":     "copy",
    "mv":     "move",
    "mkdir -p": "mkdir",
}

# ─── 安全配置 ────────────────────────────────────────────
# 这些命令被完全禁止，即使 Agent 请求也会拒绝执行。
# 设计原则：宁可拒绝一个合法请求，也不允许一次意外破坏。
#
# 两层检测：
# 1. FORBIDDEN_COMMANDS：子串匹配（简单、快速）
# 2. FORBIDDEN_PATTERNS：正则匹配（捕获参数变体，如 rm -fr / rmdir /s）
#
# 注意：黑名单不是银弹——`python -c "import shutil; ..."` 等变体
# 无法用黑名单防御，真正安全需要 sandbox（Docker/虚拟机）。
# 这里只是第一层防线，残余风险已在 ADR-004 中明确记录。
FORBIDDEN_COMMANDS: list[str] = [
    "rm -rf",       # 递归强制删除（Linux/macOS）
    "del /f",       # 强制删除（Windows）
    "mkfs",         # 创建文件系统（会覆盖分区）
    "dd if=",       # 磁盘写入（dd 的破坏性用法）
    "shutdown",     # 关机
    "reboot",       # 重启
    "halt",         # 停机
    "poweroff",     # 断电
    ":(){ :|:& };:",  # Fork 炸弹（经典 DoS 攻击）
    "chmod 777",    # 全局可写（安全风险）
]

# 正则检测：覆盖黑名单子串抓不到的参数变体。
# format 用锚定匹配（仅作为独立命令时拦截），避免误伤 clang-format、
# npm run format 等合法命令。
FORBIDDEN_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+(-[a-z]*r|--recursive)(\s|$)"),   # rm 带任何递归参数
    re.compile(r"\brmdir\b[^|;&]*/s", re.IGNORECASE),     # Windows 递归删目录
    re.compile(r"\bdel\b[^|;&]*/s", re.IGNORECASE),       # Windows 递归删除
    re.compile(r"\bchmod\b[^|;&]*\b777\b"),               # chmod -R 777 等变体
    re.compile(r"(^|[;&|]\s*)format\b"),                  # format 仅作命令开头时拦截
    re.compile(r">\s*/dev/(sd|nvme|hd)"),                 # 直接写块设备
    re.compile(r":\(\)\s*\{"),                            # Fork 炸弹变体
]

# 输出字符上限：防止 Agent 执行 cat 大文件导致上下文溢出
MAX_OUTPUT_CHARS: int = 10000

# 命令超时时间（秒）
COMMAND_TIMEOUT: int = 30


# ─── 纯函数辅助（便于单元测试，不依赖平台）────────────────


def _apply_windows_aliases(command: str, is_windows: bool = _IS_WINDOWS) -> str:
    """将命令开头的 Linux 命令映射为 Windows 等效命令。

    匹配规则：strip 后完整等于键，或以 "键 + 空格" 开头。
    只替换第一个匹配（键按"长键优先"顺序排列）。

    Args:
        command: 原始命令。
        is_windows: 是否在 Windows 平台（默认自动检测）。

    Returns:
        转换后的命令；非 Windows 或无匹配时原样返回。
    """
    if not is_windows:
        return command
    command_stripped = command.strip()
    for linux_cmd, win_cmd in _WINDOWS_ALIASES.items():
        if command_stripped == linux_cmd or command_stripped.startswith(linux_cmd + " "):
            return command_stripped.replace(linux_cmd, win_cmd, 1)
    return command


def _find_forbidden(command: str) -> str | None:
    """检查命令是否命中黑名单，返回命中描述；未命中返回 None。

    归一化空白字符（连续空格/tab 压缩为单个空格，防 "rm  -rf" 绕过），
    再依次尝试子串名单与正则名单。

    Args:
        command: 原始命令。

    Returns:
        命中的禁止规则描述（如 "rm -rf"），None 表示未命中。
    """
    command_normalized = re.sub(r"\s+", " ", command.lower().strip())
    for forbidden in FORBIDDEN_COMMANDS:
        if forbidden in command_normalized:
            return forbidden
    for pattern in FORBIDDEN_PATTERNS:
        match = pattern.search(command_normalized)
        if match:
            return f"匹配禁止规则 {pattern.pattern!r}（命中片段 '{match.group(0)}'）"
    return None


def _decode_output(data: bytes) -> str:
    """解码子进程输出：优先 UTF-8，失败时 Windows 回退 GBK。

    中文 Windows 的 cmd.exe 输出是 GBK 编码，强制 UTF-8 会得到成片
    替换符；反过来 Git Bash 等输出 UTF-8。双编码尝试兼顾两者。

    Args:
        data: 子进程的原始字节输出。

    Returns:
        解码后的文本。
    """
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        fallback = "gbk" if _IS_WINDOWS else "latin-1"
        return data.decode(fallback, errors="replace")


@tool
def run_shell(command: str) -> str:
    """执行 Shell 命令并返回标准输出和标准错误。

    适用场景：
        - 查看项目结构：ls, dir, tree
        - 运行代码：python script.py
        - 版本控制：git status, git log --oneline
        - 搜索文件内容：grep pattern file.txt
        - 系统信息：pwd, whoami, date

    安全限制：
        - 危险命令自动拦截（rm -rf、rmdir /s、format、shutdown 等及其变体）
        - 命令在沙箱根目录下执行（默认为进程工作目录，可用
          set_sandbox_root 切换）
        - 命令执行超时 30 秒自动终止
        - 输出超过 10,000 字符自动截断

    已知局限（详见 ADR-004）：
        黑名单无法覆盖所有破坏性变体（如 python -c 调 shutil.rmtree），
        生产环境必须配合容器级隔离。

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
        'total 48\\ndrwxr-xr-x ...'

        >>> run_shell.invoke({"command": "rm -rf /"})
        '🛑 安全拦截：命令包含禁止操作 ...'
    """
    # ── 第零层：Windows 命令别名自动映射 ──
    command = _apply_windows_aliases(command)

    # ── 第一层：黑名单检查 ──
    forbidden = _find_forbidden(command)
    if forbidden:
        return (
            f"🛑 安全拦截：命令命中禁止规则 '{forbidden}'。\n"
            f"   被拦截的命令：{command[:100]}\n"
            f"   如需执行此类操作，请人工在终端中确认后执行。"
        )

    # ── 第二层：执行命令（沙箱根目录下）──
    try:
        result = subprocess.run(
            command,
            shell=True,               # 支持管道等 Shell 语法
            capture_output=True,      # 捕获 stdout 和 stderr（bytes）
            timeout=COMMAND_TIMEOUT,  # 超时保护
            cwd=str(get_sandbox_root()),  # 沙箱根目录（线程局部，可注入）
        )

        # 解码输出（UTF-8 优先，Windows 回退 GBK）
        output = _decode_output(result.stdout)
        if result.stderr:
            stderr_text = _decode_output(result.stderr)
            if output:
                output += "\n"
            output += f"[stderr]\n{stderr_text}"

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
