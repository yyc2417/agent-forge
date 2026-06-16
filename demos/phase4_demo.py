"""阶段 4 Agent Demo —— 三步渐进式学习

学习目标：理解可观测性从"看日志"到"结构化数据"再到"GUI 可视化"的演进。

三步设计：
    Step 1（BusCollector + 单 Agent）：
        → BusCollector 订阅 Bus 采集事件数据
        → 后台线程运行 Agent，主线程轮询打印采集到的事件
        → 对比 phase1 的 LoggingInterceptor（纯打印）vs BusCollector（结构化采集+统计）

    Step 2（Orchestrator + 全链路追踪）：
        → BusCollector + CostTracker + Orchestrator + Specialists
        → 后台线程运行编排，主线程展示完整事件时间线 + Agent 状态 + Token 统计
        → 理解全链路追踪——从用户输入到最终输出的每一步都可见

    Step 3（Streamlit Dashboard 全栈集成）：
        → 启动 Streamlit Dashboard GUI
        → 在浏览器中提交任务，实时观察消息流、Agent 状态、成本分析
        → 体验完整的可视化观测能力

使用方式：
    python demos/phase4_demo.py --step 1
    python demos/phase4_demo.py --step 2
    python demos/phase4_demo.py --step 3

前置条件：
    1. 已配置 .env 中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖
    3. Step 3 需要额外安装 streamlit：uv pip install -e ".[dashboard]"
"""

import sys
import threading
import time
from datetime import datetime

from agent_forge.agents import BaseAgent, CoderAgent, Orchestrator, ReviewerAgent
from agent_forge.bus import LoggingInterceptor, MessageBus
from agent_forge.cost import CostTracker
from agent_forge.dashboard import BusCollector
from agent_forge.tools import ALL_TOOLS
from agent_forge.utils import print_info, print_separator, safe_print

# ============================================================
# 共享工具函数
# ============================================================

def _format_timestamp(ts: float) -> str:
    """格式化时间戳为 HH:MM:SS。"""
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _print_event_line(event: dict) -> None:
    """格式化打印一条事件。"""
    ts = event.get("timestamp", 0)
    time_str = _format_timestamp(ts) if ts else "??:??:??"
    role = event.get("role", "?")
    payload = event.get("payload", {})
    event_type = payload.get("event_type", "unknown")

    # payload 预览
    preview_parts = []
    for k, v in payload.items():
        if k != "event_type":
            val = str(v)[:50]
            preview_parts.append(f"{k}={val}")
    preview = ", ".join(preview_parts) if preview_parts else ""

    safe_print(f"  [{time_str}] {role:<14} | {event_type:<28} | {preview}")


def _print_stats(stats: dict) -> None:
    """打印统计摘要。"""
    safe_print(f"\n{'─' * 60}")
    safe_print("  统计摘要")
    safe_print(f"{'─' * 60}")
    safe_print(f"  总消息数:    {stats['total_messages']}")
    safe_print(f"  事件数:      {stats['total_events']}")
    safe_print(f"  活跃 Agent:  {stats['agent_count']}")
    safe_print(f"  工具调用:    {stats['tool_calls']}")
    safe_print(f"  REQUEST:     {stats['request_count']}")
    safe_print(f"  RESPONSE:    {stats['response_count']}")
    safe_print(f"  耗时:        {stats['duration_seconds']}s")
    safe_print(f"{'─' * 60}")


def _print_agent_states(states: dict) -> None:
    """打印 Agent 状态表。"""
    if not states:
        return
    safe_print(f"\n  {'Agent':<14} {'状态':<16} {'消息数':>6} {'最后事件'}")
    safe_print(f"  {'─' * 14} {'─' * 16} {'─' * 6} {'─' * 28}")
    for name, s in states.items():
        tool_info = f" (🔧{s['current_tool']})" if s["current_tool"] else ""
        safe_print(
            f"  {name:<14} {s['status']:<16} {s['message_count']:>6} "
            f"{s['last_event_type']}{tool_info}"
        )


def _poll_collector(
    collector: BusCollector,
    thread: threading.Thread,
    interval: float = 3.0,
) -> None:
    """主线程轮询打印采集到的事件（直到后台线程结束）。

    Args:
        collector: BusCollector 实例。
        thread: 后台运行线程。
        interval: 轮询间隔（秒）。
    """
    last_event_count = 0
    while thread.is_alive():
        time.sleep(interval)
        events = collector.get_events()
        stats = collector.get_stats()

        # 只打印新增事件
        new_events = events[last_event_count:]
        if new_events:
            safe_print(f"\n  ── 新增 {len(new_events)} 个事件（共 {len(events)} 个）──")
            for event in new_events:
                _print_event_line(event)
            last_event_count = len(events)

        # 打印实时统计
        safe_print(
            f"  [实时] 消息: {stats['total_messages']} | "
            f"事件: {stats['total_events']} | "
            f"Agent: {stats['agent_count']} | "
            f"工具: {stats['tool_calls']}"
        )

    # 线程结束后打印最终状态
    safe_print("\n  ── 任务完成 ──")
    _print_agent_states(collector.get_agent_states())
    _print_stats(collector.get_stats())


# ============================================================
# Step 1: BusCollector + 单 Agent（终端可视化）
# ============================================================

def run_step1() -> None:
    """单 Agent + BusCollector：理解可观测性从"看日志"到"结构化数据"的升级。

    对比 phase1 Step 2：
    - phase1: 用 LoggingInterceptor 在终端实时打印每条消息
    - phase4: 用 BusCollector 结构化采集所有事件，可以事后查询、统计

    学习目标：
    1. BusCollector 如何订阅 Bus 的 "*" 通配符事件
    2. 事件时间线的结构化存储（vs LoggingInterceptor 的纯文本打印）
    3. Agent 状态推导：从事件类型推导出 Agent 当前在做什么
    """
    print_separator("阶段 4 Demo — Step 1: BusCollector + 单 Agent", 60)
    print_info("BusCollector 订阅 Bus 采集事件，后台线程运行 Agent")
    print_info("对比 phase1 的 LoggingInterceptor（纯打印）vs BusCollector（结构化采集+统计）")
    safe_print()

    # 1. 创建 Bus + Collector
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())
    collector = BusCollector()
    collector.attach(bus)
    print_info("Bus + BusCollector 已就绪")

    # 2. 创建单 Agent
    agent = BaseAgent(
        name="coder",
        role="Python 工程师",
        tools=ALL_TOOLS,
        bus=bus,
    )
    print_info(f"Agent 已创建: {agent}")
    safe_print()

    # 3. 交互循环
    safe_print("输入任务（输入 /quit 退出）：")
    safe_print("试试：'读一下 README.md 的内容'")
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

        # 清空上一次的数据
        collector.clear()

        # 后台线程运行 Agent
        safe_print(f"\n{'─' * 40}")
        safe_print("  [Step 1] Agent 在后台运行中...")
        safe_print(f"{'─' * 40}")

        result_holder = {"result": ""}

        def run_agent():
            result_holder["result"] = agent.run(user_input)

        thread = threading.Thread(target=run_agent, daemon=True)
        thread.start()

        # 主线程轮询展示
        _poll_collector(collector, thread, interval=3.0)

        # 等待线程完全结束
        thread.join()

        # 打印最终结果
        safe_print("\n  [Agent 最终回复]")
        safe_print(f"  {result_holder['result'][:500]}")
        safe_print()


# ============================================================
# Step 2: Orchestrator + 多 Agent（全链路追踪）
# ============================================================

def run_step2() -> None:
    """Orchestrator + BusCollector：理解全链路追踪。

    对比 phase2 Step 3：
    - phase2: 用终端日志观察 Orchestrator 的拆解和执行
    - phase4: 用 BusCollector 结构化展示完整的事件时间线 + Agent 状态表 + Token 统计

    学习目标：
    1. 全链路追踪——从用户输入到最终输出的每一步都可见
    2. Orchestrator 事件（decomposing → dispatching → reviewing → aggregating）
    3. Token 成本追踪——按 Agent 维度统计 LLM 调用成本
    """
    print_separator("阶段 4 Demo — Step 2: Orchestrator + 全链路追踪", 60)
    print_info("BusCollector + CostTracker + Orchestrator + Specialists")
    print_info("全链路追踪：从用户输入到最终输出的每一步都可见")
    safe_print()

    # 1. 创建 Bus + Collector + CostTracker
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())
    collector = BusCollector()
    collector.attach(bus)
    cost_tracker = CostTracker()
    print_info("Bus + BusCollector + CostTracker 已就绪")

    # 2. 创建 Agent 团队
    coder = CoderAgent(bus=bus, cost_tracker=cost_tracker)
    reviewer = ReviewerAgent(bus=bus, cost_tracker=cost_tracker)
    orchestrator = Orchestrator(
        specialists={"coder": coder, "reviewer": reviewer},
        bus=bus,
        cost_tracker=cost_tracker,
    )
    print_info("Orchestrator + Coder + Reviewer 已就绪")
    safe_print()

    # 3. 交互循环
    safe_print("输入任务（输入 /quit 退出）：")
    safe_print("试试：'帮我写一个快速排序函数'")
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

        # 清空上一次的数据
        collector.clear()
        cost_tracker.clear()

        # 后台线程运行 Orchestrator
        safe_print(f"\n{'─' * 40}")
        safe_print("  [Step 2] Orchestrator 编排中...")
        safe_print(f"{'─' * 40}")

        result_holder = {"result": ""}

        def run_orchestrator():
            result_holder["result"] = orchestrator.run(user_input)

        thread = threading.Thread(target=run_orchestrator, daemon=True)
        thread.start()

        # 主线程轮询展示
        _poll_collector(collector, thread, interval=3.0)

        # 等待线程完全结束
        thread.join()

        # 打印 Token 成本报告
        cost_tracker.print_report()

        # 打印最终结果预览
        safe_print("\n  [Orchestrator 最终产出]")
        safe_print(f"  {result_holder['result'][:500]}")
        safe_print()


# ============================================================
# Step 3: Streamlit Dashboard 全栈集成
# ============================================================

def run_step3() -> None:
    """Streamlit Dashboard：体验完整的可视化观测能力。

    对比 phase3 Step 3：
    - phase3: 全栈终端集成（所有输出在终端）
    - phase4: 全栈 GUI 集成（所有数据在浏览器中可视化呈现）

    本步骤不运行 Agent，而是启动 Streamlit Dashboard。
    在 Dashboard 中可以提交任务并实时观察：
    - 消息流时间线（Tab 2）
    - Agent 状态变化（Tab 3）
    - Token 成本分析（Tab 4）
    """
    print_separator("阶段 4 Demo — Step 3: Streamlit Dashboard", 60)
    print_info("启动 Streamlit Dashboard GUI")
    print_info("在浏览器中提交任务，实时观察消息流、Agent 状态、成本分析")
    safe_print()

    # 检查 streamlit 是否已安装
    try:
        import streamlit  # noqa: F401
    except ImportError:
        safe_print("  [错误] Streamlit 未安装。请运行：")
        safe_print("    uv pip install -e \".[dashboard]\"")
        safe_print()
        return

    safe_print("  正在启动 Dashboard...")
    safe_print("  启动后会自动打开浏览器。按 Ctrl+C 停止。")
    safe_print()

    import subprocess
    try:
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run",
             "agent_forge/dashboard/app.py",
             "--server.headless", "false"],
            cwd=".",
        )
    except KeyboardInterrupt:
        safe_print("\n  Dashboard 已停止。")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    """运行入口：通过 --step 参数选择要运行的步骤。

    使用：
        python demos/phase4_demo.py --step 1   # BusCollector + 单 Agent
        python demos/phase4_demo.py --step 2   # Orchestrator + 全链路
        python demos/phase4_demo.py --step 3   # Streamlit Dashboard
        python demos/phase4_demo.py            # 默认 Step 1
    """
    step = "1"
    if len(sys.argv) > 2 and sys.argv[1] == "--step":
        step = sys.argv[2]

    steps = {"1": run_step1, "2": run_step2, "3": run_step3}

    if step not in steps:
        safe_print(f"错误：未知步骤 '{step}'。可选：1, 2, 3")
        sys.exit(1)

    try:
        safe_print(f"\n📊 启动阶段 4 Agent Demo — Step {step}\n")
    except UnicodeEncodeError:
        safe_print(f"\n[AgentForge] Starting Phase 4 Demo — Step {step}\n")

    steps[step]()
