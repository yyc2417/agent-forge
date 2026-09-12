import importlib.util
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


def judge(agent_output: str, work_dir: Path) -> bool:
    """自定义评判：stack.py 存在、方法齐全，且真的可以 import 并调用。

    旧实现只做子串检查（"def push" 出现在注释里也算），docstring
    却声称"可 import"——现在补上真实的 importlib 验证，
    让 hard 难度的区分度来自代码质量而非文本出现。
    """
    stack_file = work_dir / "stack.py"
    if not stack_file.exists():
        return False

    try:
        content = stack_file.read_text(encoding="utf-8")
    except Exception:
        return False

    # 快速失败：文本层面先检查关键方法与类定义
    required = ["def push", "def pop", "def peek", "def is_empty", "def __len__"]
    if not all(method in content for method in required):
        return False
    if "class Stack" not in content:
        return False

    # 真实 import：语法错误的 stack.py（只要方法名以文本形式存在也能
    # 骗过子串检查）在这里会被筛掉
    try:
        spec = importlib.util.spec_from_file_location("stack_under_test", stack_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return False

    stack_cls = getattr(module, "Stack", None)
    if stack_cls is None:
        return False
    return all(callable(getattr(stack_cls, name, None))
               for name in ("push", "pop", "peek", "is_empty", "__len__"))
