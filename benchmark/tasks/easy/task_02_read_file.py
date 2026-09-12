from benchmark.tasks.sample_project import create as _create_sample

TASK = {
    "id": "easy-02",
    "name": "读取文件",
    "description": "读取当前目录下的 README.md 文件的前 10 行内容并返回",
    "difficulty": "easy",
    "judge": {
        "type": "contains",
        "values": ["AgentForge"],
    },
}


def setup(work_dir):
    """提供被读取的 README.md（隔离目录原本为空，任务否则不可满足）。"""
    _create_sample(work_dir)
