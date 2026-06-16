TASK = {
    "id": "medium-06",
    "name": "配置文件生成",
    "description": "生成一个 config.json 文件，包含项目名 'agent-forge'、版本号 '0.1.0'、Python 版本 '3.11' 和依赖列表",
    "difficulty": "medium",
    "judge": {
        "type": "file_contains",
        "file": "config.json",
        "values": ["agent-forge", "version"],
    },
}
