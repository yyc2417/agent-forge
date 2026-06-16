"""Agent 模块

阶段 2：Agent 基类 + Specialist Agents + Orchestrator 编排器。
阶段 5：新增 AnalystAgent + WriterAgent。

提供三层 Agent 抽象：
- BaseAgent: 通用 Agent 基类（ReAct 循环 + Bus 集成）
- CoderAgent / ReviewerAgent / AnalystAgent / WriterAgent: 专业角色 Agent
- Orchestrator: 多 Agent 编排器（LangGraph StateGraph 驱动）
"""

from .base import AgentState, BaseAgent
from .orchestrator import Orchestrator, OrchestratorState
from .specialists import AnalystAgent, CoderAgent, ReviewerAgent, WriterAgent

__all__ = [
    "BaseAgent", "AgentState",
    "CoderAgent", "ReviewerAgent", "AnalystAgent", "WriterAgent",
    "Orchestrator", "OrchestratorState",
]
