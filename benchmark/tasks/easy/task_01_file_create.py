TASK = {
    "id": "easy-01",
    "name": "创建文件",
    "description": "在当前目录创建一个名为 hello.py 的文件，内容为 print('Hello World')",
    "difficulty": "easy",
    "judge": {
        "type": "file_contains",
        "file": "hello.py",
        "values": ["Hello World"],
    },
}
