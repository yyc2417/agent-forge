TASK = {
    "id": "medium-03",
    "name": "代码分析报告",
    "description": "读取 agent_forge/utils.py 文件，分析其代码质量并给出至少 3 条改进建议",
    "difficulty": "medium",
    "judge": {
        "type": "contains",
        "values": ["utils"],
    },
}


def judge(agent_output: str) -> bool:
    """自定义评判：输出至少 100 字符且包含分析关键词。"""
    if len(agent_output) < 100:
        return False
    keywords = ["建议", "改进", "优化", "可以", "应该", "问题", "分析"]
    return any(kw in agent_output for kw in keywords)
