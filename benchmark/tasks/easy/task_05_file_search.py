from benchmark.tasks.sample_project import create as _create_sample

TASK = {
    "id": "easy-05",
    "name": "文件搜索",
    "description": "搜索项目中所有包含 'class BaseAgent' 的 Python 文件，返回文件名列表",
    "difficulty": "easy",
    "judge": {
        "type": "contains",
        "values": ["base.py"],
    },
}


def setup(work_dir):
    """创建含 class BaseAgent 的样例项目（隔离目录原本为空）。"""
    _create_sample(work_dir)
