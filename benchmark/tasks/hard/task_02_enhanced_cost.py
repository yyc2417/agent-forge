from pathlib import Path

TASK = {
    "id": "hard-02",
    "name": "增强版 CostTracker",
    "description": "读取 agent_forge/cost.py，创建一个增强版的 CostTracker（新增 to_json 方法支持导出为 JSON 格式），将增强版代码写入 enhanced_cost.py",
    "difficulty": "hard",
    "judge": {
        "type": "custom",
    },
}


def judge(agent_output: str) -> bool:
    """自定义评判：enhanced_cost.py 存在 + 包含 to_json + 包含原始方法。"""
    enhanced_file = Path("enhanced_cost.py")
    if not enhanced_file.exists():
        return False

    try:
        content = enhanced_file.read_text(encoding="utf-8")
    except Exception:
        return False

    # 必须包含 to_json 方法
    if "to_json" not in content:
        return False

    # 必须包含 CostTracker 类
    if "class CostTracker" not in content and "class EnhancedCostTracker" not in content:
        return False

    return True
