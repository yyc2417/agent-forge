from benchmark.tasks.sample_project import create as _create_sample

TASK = {
    "id": "easy-04",
    "name": "列出目录结构",
    "description": "列出当前项目根目录下的一级子目录和文件名称",
    "difficulty": "easy",
    "judge": {
        "type": "contains",
        "values": ["agent_forge"],
    },
}


def setup(work_dir):
    """创建含 agent_forge/ 子目录的样例项目（隔离目录原本为空）。"""
    _create_sample(work_dir)
