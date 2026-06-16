"""研究报告场景 Demo —— Analyst → Coder → Writer 协作流程

演示 AgentForge 在研究报告场景下的多 Agent 协作：
1. AnalystAgent 制定调研框架和对比维度
2. CoderAgent 搜集信息（读取本地资料 + 执行搜索）
3. WriterAgent 整合所有信息，撰写对比报告文件
4. 汇总最终产出

使用方式：
    python demos/research_workflow.py

前置条件：
    1. 已配置 .env 中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖
"""

from dotenv import load_dotenv

from agent_forge.agents import (
    AnalystAgent,
    CoderAgent,
    Orchestrator,
    WriterAgent,
)
from agent_forge.bus import LoggingInterceptor, MessageBus
from agent_forge.cost import CostTracker
from agent_forge.utils import print_separator, safe_print

load_dotenv()


def main():
    """运行研究报告场景的多 Agent 协作 Demo。"""
    print_separator("AgentForge — 研究报告协作 Demo", 60)
    safe_print("  Analyst → Coder → Writer 协作流程")
    safe_print("  分析 → 信息搜集 → 撰写报告")
    safe_print()

    # 创建 Bus + CostTracker
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())
    cost_tracker = CostTracker()

    # 创建 Agent 团队
    analyst = AnalystAgent(bus=bus, cost_tracker=cost_tracker)
    coder = CoderAgent(bus=bus, cost_tracker=cost_tracker)
    writer = WriterAgent(bus=bus, cost_tracker=cost_tracker)

    orchestrator = Orchestrator(
        specialists={
            "analyst": analyst,
            "coder": coder,
            "writer": writer,
        },
        bus=bus,
        cost_tracker=cost_tracker,
    )

    safe_print("Agent 团队已就绪：Analyst + Coder + Writer")
    safe_print()

    # 交互循环
    safe_print("输入调研任务（输入 /quit 退出）：")
    safe_print("试试：'分析 agent_forge 项目的架构设计，输出分析报告'")
    safe_print()

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            safe_print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            safe_print("再见！")
            break

        safe_print(f"\n{'─' * 50}")
        safe_print("  Orchestrator 开始编排...")
        safe_print(f"{'─' * 50}")

        result = orchestrator.run(user_input)

        safe_print(f"\n{'═' * 50}")
        safe_print("  最终产出")
        safe_print(f"{'═' * 50}")
        safe_print(result[:1000])

        # 打印成本报告
        cost_tracker.print_report()
        cost_tracker.clear()


if __name__ == "__main__":
    main()
