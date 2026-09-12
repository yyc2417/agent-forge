"""为需要"项目文件"的评测任务构造最小样例项目。

背景：benchmark 每个任务在隔离的临时目录中执行（原工作目录为空）。
部分任务引用了"当前项目中的文件"（如 README.md、agent_forge/agents/base.py），
若 setup 不构造这些文件，任务结构性不可满足——Agent 无论多正确都会失败，
快速验证跑（2026-09-12）中 easy-02/04/05 因此全灭。

需要项目文件的任务在 setup() 里调用 create(work_dir)。
"""

from pathlib import Path

# 相对路径 → 文件内容（最小化，但满足各任务 judge 的可发现性）
SAMPLE_FILES: dict[str, str] = {
    "README.md": (
        "# AgentForge Sample\n\n"
        "这是一个用于评测的最小项目样例。\n"
        "它只包含几个示例模块，用于测试 Agent 的文件读取与目录浏览能力。\n"
    ),
    "pyproject.toml": (
        '[project]\nname = "sample-project"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
    ),
    "agent_forge/agents/base.py": (
        '"""样例 BaseAgent 模块。"""\n\n\n'
        "class BaseAgent:\n"
        '    """所有 Agent 的基类。"""\n\n'
        "    def __init__(self, name: str) -> None:\n"
        "        self.name = name\n\n"
        "    def run(self, task: str) -> str:\n"
        '        return f"done: {task}"\n'
    ),
    "agent_forge/agents/specialists.py": (
        '"""样例 Specialist 模块。"""\n\n\n'
        "class CoderAgent:\n"
        '    """编码专家。"""\n'
    ),
    "agent_forge/tools/file_tools.py": (
        '"""样例文件工具。"""\n\n\n'
        "def read_file(path: str) -> str:\n"
        '    """读取文件。"""\n'
        '    return ""\n\n\n'
        "def write_file(path: str, content: str) -> str:\n"
        '    """写入文件。"""\n'
        '    return ""\n'
    ),
    "agent_forge/tools/shell_tools.py": (
        '"""样例 shell 工具。"""\n\n\n'
        "def run_shell(command: str) -> str:\n"
        '    """执行命令。"""\n'
        '    return ""\n'
    ),
    "agent_forge/tools/search_tools.py": (
        '"""样例搜索工具。"""\n\n\n'
        "def grep_search(pattern: str, path: str = \".\") -> str:\n"
        '    """搜索内容。"""\n'
        '    return ""\n'
    ),
}


def create(work_dir: Path) -> None:
    """在评测工作目录中创建样例项目文件。"""
    for rel_path, content in SAMPLE_FILES.items():
        target = work_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
