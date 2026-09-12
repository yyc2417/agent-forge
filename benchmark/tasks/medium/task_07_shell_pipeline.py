from benchmark.tasks.sample_project import create as _create_sample

TASK = {
    "id": "medium-07",
    "name": "Shell 管道操作",
    "description": "用 Shell 命令找出当前项目中行数最多的 5 个 Python 文件，返回文件名和行数",
    "difficulty": "medium",
    "judge": {
        "type": "regex",
        "pattern": "\\d+\\s+\\S+\\.py",
    },
}


def setup(work_dir):
    """创建多个行数不同的 .py 文件（隔离目录原本为空，任务否则不可满足）。"""
    _create_sample(work_dir)
