from benchmark.tasks.sample_project import create as _create_sample

TASK = {
    "id": "medium-05",
    "name": "搜索并汇总",
    "description": "搜索当前项目中 read_file / write_file / run_shell 等工具函数的定义位置，列出所有工具函数的名称",
    "difficulty": "medium",
    "judge": {
        "type": "contains",
        "values": ["read_file", "write_file", "run_shell"],
    },
}


def setup(work_dir):
    """创建含工具函数定义的样例项目（隔离目录原本为空）。"""
    _create_sample(work_dir)
