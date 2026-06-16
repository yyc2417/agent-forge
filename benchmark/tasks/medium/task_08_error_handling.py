TASK = {
    "id": "medium-08",
    "name": "错误处理代码",
    "description": "编写一个 safe_divide(a, b) 函数，包含 ZeroDivisionError 和 TypeError 异常处理，有完整的类型注解，写入 safe_divide.py",
    "difficulty": "medium",
    "judge": {
        "type": "file_contains",
        "file": "safe_divide.py",
        "values": ["def safe_divide", "ZeroDivisionError", "try"],
    },
}
