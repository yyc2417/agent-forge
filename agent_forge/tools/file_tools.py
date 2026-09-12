"""文件操作工具集

Agent 通过这两个工具获得最基本的文件 I/O 能力：
    - read_file:  读取项目文件、查看代码、了解上下文
    - write_file: 产出代码文件、报告、分析结果

为什么需要这些工具？
    没有工具的 LLM 只能"说话"，无法真正"做事"。
    文件读写是 Agent 最常见的需求——无论是写代码还是生成报告，
    最终都要落盘。

安全设计（sandbox 沙箱）：
    所有路径经 resolve_in_sandbox 校验：
    - 相对路径锚定沙箱根（默认为进程 cwd，可用 set_sandbox_root 切换）
    - 越界的绝对路径 / ".." 逃逸一律拒绝
    - .env 等敏感文件拒绝读取，防止 API Key 进入 LLM 上下文
"""


from langchain_core.tools import tool

from agent_forge.tools.sandbox import resolve_in_sandbox


@tool
def read_file(path: str) -> str:
    """读取指定路径的文件内容。

    适用场景：
        - Agent 需要查看项目结构时，先读关键文件
        - Agent 需要分析代码时，读目标源文件
        - Agent 需要理解上下文时，读相关配置文件

    限制：
        - 仅支持 UTF-8 编码的文本文件
        - 不支持二进制文件（图片、PDF 等）
        - 不支持读取目录（请用 run_shell 工具执行 ls）

    Args:
        path: 文件的相对路径或沙箱内的绝对路径。
              相对路径基于沙箱根目录（默认为进程工作目录）。

    Returns:
        文件内容字符串。如果文件不存在、是目录、越出沙箱边界或编码不匹配，
        返回描述性的错误信息而非抛出异常。

    Example:
        >>> read_file.invoke({"path": "README.md"})
        '（返回 README.md 的完整内容）'
    """
    file_path, sandbox_error = resolve_in_sandbox(path)
    if sandbox_error:
        return sandbox_error

    # 存在性检查
    if not file_path.exists():
        return f"错误：文件 '{path}' 不存在。请确认路径是否正确。"

    # 类型检查（防止 Agent 试图"读"一个目录）
    if file_path.is_dir():
        return (
            f"错误：'{path}' 是一个目录，不是文件。\n"
            f"如需查看目录内容，请使用 run_shell 工具执行 'ls {path}'。"
        )

    # 尝试以 UTF-8 读取
    try:
        content = file_path.read_text(encoding="utf-8")
        return content
    except UnicodeDecodeError:
        return (
            f"错误：文件 '{path}' 不是 UTF-8 文本文件，无法读取。\n"
            f"当前仅支持 UTF-8 编码的文本文件。"
        )
    except PermissionError:
        return f"错误：没有权限读取文件 '{path}'。"
    except Exception as e:
        return f"读取文件时发生未知错误：{type(e).__name__}: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """将内容写入指定路径的文件（会覆盖已有内容）。

    适用场景：
        - Agent 生成代码后，写入项目文件
        - Agent 生成报告后，保存为 Markdown 文件
        - Agent 修改配置文件

    安全说明：
        - 覆盖写入：如果文件已存在，内容会被替换
        - 自动创建目录：如果父目录不存在，会自动创建
        - 沙箱限制：只能写入沙箱根目录内的路径；.env 等敏感文件拒绝写入

    Args:
        path: 目标文件的相对路径或沙箱内的绝对路径。
              相对路径基于沙箱根目录（默认为进程工作目录）。
        content: 要写入文件的完整内容字符串。

    Returns:
        操作结果，包含写入的字符数。

    Example:
        >>> write_file.invoke({"path": "output/report.md", "content": "# 报告\\n内容..."})
        '成功写入文件：output/report.md（15 字符）'
    """
    file_path, sandbox_error = resolve_in_sandbox(path)
    if sandbox_error:
        return sandbox_error

    try:
        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # 写入文件
        file_path.write_text(content, encoding="utf-8")
        return f"成功写入文件：{path}（{len(content)} 字符）"
    except PermissionError:
        return f"错误：没有权限写入文件 '{path}'。"
    except OSError as e:
        return f"写入文件时发生系统错误：{e}"
    except Exception as e:
        return f"写入文件时发生未知错误：{type(e).__name__}: {e}"
