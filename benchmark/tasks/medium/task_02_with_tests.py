TASK = {
    "id": "medium-02",
    "name": "带测试的函数",
    "description": "编写一个 is_palindrome(s: str) -> bool 函数和至少 3 个 assert 测试用例，全部写入 palindrome.py 文件",
    "difficulty": "medium",
    "judge": {
        "type": "file_contains",
        "file": "palindrome.py",
        "values": ["def is_palindrome", "assert"],
    },
}
