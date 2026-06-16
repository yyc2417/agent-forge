TASK = {
    "id": "medium-04",
    "name": "多文件操作",
    "description": "创建 data/input.txt 写入 'name,age\\nAlice,30\\nBob,25'，再创建 process.py 包含读取该 CSV 文件并打印数据的代码",
    "difficulty": "medium",
    "judge": {
        "type": "file_contains",
        "file": "data/input.txt",
        "values": ["Alice"],
    },
}
