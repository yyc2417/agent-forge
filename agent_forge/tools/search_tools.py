"""搜索工具 —— 文本搜索

提供 grep_search 工具，让 Agent 能在项目目录中搜索文本内容。
使用纯 Python 标准库实现（pathlib + re），不依赖系统 grep 命令。

安全设计：
    - 搜索结果最多返回 50 条，防止大量匹配淹没上下文
    - 跳过二进制文件和常见的非文本目录（.git, __pycache__, .venv）
    - 搜索范围受 path 参数限制，不会无限制遍历整个文件系统
"""

import re
from pathlib import Path

from langchain_core.tools import tool

# 跳过的目录名（搜索时自动忽略）
_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".egg-info",
    "dist", "build", ".qoder", ".workbuddy",
}

# 最大返回条数
_MAX_RESULTS = 50


@tool
def grep_search(pattern: str, path: str = ".", file_pattern: str = "*.py") -> str:
    """在指定目录中搜索文本模式（类似 grep）。

    使用 Python 正则表达式匹配文件内容。
    自动跳过 .git、__pycache__、.venv 等非文本目录。

    Args:
        pattern: 搜索的文本模式（支持 Python 正则表达式语法）。
                 例如："def test_"、"class.*Agent"、"import.*langgraph"
        path: 搜索的根目录，默认当前目录。
        file_pattern: 文件过滤 glob 模式，默认 "*.py"。
                      常用值："*.py"（Python）、"*.*"（所有文件）、"*.md"（Markdown）

    Returns:
        匹配结果，格式为 "文件名:行号: 匹配行内容"。
        最多返回 50 条匹配结果。无匹配时返回提示。
    """
    search_path = Path(path)
    if not search_path.exists():
        return f"错误：目录 '{path}' 不存在"

    if not search_path.is_dir():
        return f"错误：'{path}' 不是目录"

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"正则表达式错误：{e}"

    results: list[str] = []
    files_searched = 0

    for file_path in search_path.rglob(file_pattern):
        # 跳过隐藏目录和常见的非文本目录
        parts = file_path.parts
        if any(part in _SKIP_DIRS for part in parts):
            continue
        if any(part.startswith(".") and part != "." for part in parts):
            continue

        files_searched += 1

        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except (OSError, PermissionError):
            continue

        for line_num, line in enumerate(lines, 1):
            if regex.search(line):
                # 使用相对路径显示
                try:
                    rel_path = file_path.relative_to(search_path)
                except ValueError:
                    rel_path = file_path

                result_line = f"{rel_path}:{line_num}: {line.strip()}"
                results.append(result_line)

                if len(results) >= _MAX_RESULTS:
                    return (
                        f"搜索 '{pattern}'（已搜索 {files_searched} 个文件）\n"
                        f"找到 {_MAX_RESULTS}+ 条匹配（结果已截断）：\n"
                        + "\n".join(results)
                    )

    if not results:
        return f"搜索 '{pattern}'（已搜索 {files_searched} 个文件）：无匹配"

    return (
        f"搜索 '{pattern}'（已搜索 {files_searched} 个文件）\n"
        f"找到 {len(results)} 条匹配：\n"
        + "\n".join(results)
    )
