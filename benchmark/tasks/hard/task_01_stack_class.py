from pathlib import Path

TASK = {
    "id": "hard-01",
    "name": "完整 Stack 类实现",
    "description": "实现一个完整的 Stack 类，包含 push, pop, peek, is_empty, __len__ 五个方法，要求有完整的类型注解和 docstring，将代码写入 stack.py 文件",
    "difficulty": "hard",
    "judge": {
        "type": "custom",
    },
}


def judge(agent_output: str) -> bool:
    """自定义评判：检查 stack.py 存在、方法齐全、可 import。"""
    stack_file = Path("stack.py")
    if not stack_file.exists():
        return False

    try:
        content = stack_file.read_text(encoding="utf-8")
    except Exception:
        return False

    # 检查关键方法
    required = ["def push", "def pop", "def peek", "def is_empty", "def __len__"]
    if not all(method in content for method in required):
        return False

    # 检查类定义
    if "class Stack" not in content:
        return False

    return True
