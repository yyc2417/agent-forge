"""AgentForge - 基于 LangGraph 的多 Agent 协作框架

一个可演示、可扩展的多 Agent 协作框架，支持软件开发和通用任务两种场景。
本项目用于展示对 Agent 架构设计、任务编排和通信协议的深度理解。

项目结构概览：
    agent_forge/       - 核心库包（LLM / Tools / Agents / Bus / Memory / Dashboard）
    benchmark/         - 量化评测框架（20 任务 + 自动评判 + 报告生成）
    tests/             - 单元测试（100 用例）
    demos/             - 各阶段演示脚本 + 多场景工作流
    docs/              - 架构文档 / ADR / 学习笔记

当前进度：
    阶段 0 ✅ 单 Agent Demo（ReAct 循环）
    阶段 1 ✅ Agent 基类 + Message Bus
    阶段 2 ✅ Orchestrator + LangGraph 工作流
    阶段 3 ✅ Shared Memory + Tool Registry + Hooks + Token 追踪
    阶段 4 ✅ Dashboard + 场景 Demo + ARCHITECTURE.md
    阶段 5 ✅ Benchmark + 单元测试 + CI + 多场景演示
"""

__version__ = "0.1.0"
