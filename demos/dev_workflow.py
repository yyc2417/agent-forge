"""软件研发场景 Demo —— Analyst → Coder → Reviewer 协作流程

演示 AgentForge 在软件研发场景下的多 Agent 协作：
1. AnalystAgent 分析需求和项目结构
2. CoderAgent 根据分析编写代码
3. ReviewerAgent 审查代码质量
4. 如果审查不通过，自动回退给 Coder 重写

使用方式：
    python demos/dev_workflow.py

前置条件：
    1. 已配置 .env 中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖
"""

from dotenv import load_dotenv

from agent_forge.agents import (
    AnalystAgent,
    CoderAgent,
    Orchestrator,
    ReviewerAgent,
)
from agent_forge.bus import LoggingInterceptor, MessageBus
from agent_forge.cost import CostTracker
from agent_forge.utils import print_separator, safe_print

load_dotenv()


def main():
    """运行软件研发场景的多 Agent 协作 Demo。"""
    print_separator("AgentForge — 软件研发协作 Demo", 60)
    safe_print("  Analyst → Coder → Reviewer 协作流程")
    safe_print("  支持审查不通过自动回退重写")
    safe_print()

    # 创建 Bus + CostTracker
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())
    cost_tracker = CostTracker()

    # 创建 Agent 团队
    analyst = AnalystAgent(bus=bus, cost_tracker=cost_tracker)
    coder = CoderAgent(bus=bus, cost_tracker=cost_tracker)
    reviewer = ReviewerAgent(bus=bus, cost_tracker=cost_tracker)

    orchestrator = Orchestrator(
        specialists={
            "analyst": analyst,
            "coder": coder,
            "reviewer": reviewer,
        },
        bus=bus,
        cost_tracker=cost_tracker,
    )

    safe_print("Agent 团队已就绪：Analyst + Coder + Reviewer")
    safe_print()

    # 交互循环
    safe_print("输入研发任务（输入 /quit 退出）：")
    safe_print("试试：'帮我实现一个用户注册功能，包含输入验证'")
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
