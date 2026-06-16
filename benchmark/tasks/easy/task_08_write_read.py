TASK = {
    "id": "easy-08",
    "name": "写入并读回",
    "description": "创建一个名为 test_output.txt 的文件，写入内容 'AgentForge Test'，然后读取该文件并确认内容正确",
    "difficulty": "easy",
    "judge": {
        "type": "file_contains",
        "file": "test_output.txt",
        "values": ["AgentForge Test"],
    },
}
