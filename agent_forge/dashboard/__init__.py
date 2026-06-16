"""Dashboard 模块

提供 AgentForge 的可视化观测能力：
- BusCollector: 订阅 MessageBus 采集事件数据（线程安全）
- app.py: Streamlit Dashboard 主应用（通过 streamlit run 启动）

设计理念：
    Dashboard 是系统的可观测性窗口，通过直连 MessageBus 获取数据，
    不侵入 Agent 的核心逻辑。BusCollector 作为数据采集层，
    在后台线程中被动接收消息，Streamlit 在主线程中定期拉取展示。

使用方式：
    # 方式 1：通过 Demo 脚本
    python demos/phase4_demo.py --step 3

    # 方式 2：直接启动 Streamlit
    streamlit run agent_forge/dashboard/app.py
"""

from .collector import (
    STATUS_CALLING_TOOL,
    STATUS_COMPLETED,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_THINKING,
    AgentSnapshot,
    BusCollector,
)

__all__ = [
    "BusCollector",
    "AgentSnapshot",
    "STATUS_IDLE",
    "STATUS_RUNNING",
    "STATUS_THINKING",
    "STATUS_CALLING_TOOL",
    "STATUS_COMPLETED",
]
