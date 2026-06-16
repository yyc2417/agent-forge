"""阶段 1 Agent Demo —— 三步渐进式学习

学习目标：理解 Agent 抽象和消息总线的设计，从"能用基类"到"理解通信"到"多 Agent 协作"。

三步设计：
    Step 1（基类用法）：用 BaseAgent 一行创建 Agent
        → 对比 phase0_demo Step 3，体会封装带来的简洁性
        → phase0 需要手写 100+ 行构建 StateGraph，现在只需 3 行

    Step 2（消息总线观测）：Agent + MessageBus 单 Agent 自通信
        → 通过 LoggingInterceptor 看到 Agent 内部发生了什么
        → 理解事件驱动：每次思考、调工具、完成都会产生事件

    Step 3（双 Agent 协作）：Coder + Reviewer 通过 Message Bus 协作
        → 理解 REQUEST-RESPONSE 配对
        → 理解消息追溯：/history 命令查看完整消息链

使用方式：
    python demos/phase1_agent_demo.py --step 1
    python demos/phase1_agent_demo.py --step 2
    python demos/phase1_agent_demo.py --step 3

前置条件：
    1. 已配置 .env 中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖
"""

import sys

# ─── AgentForge 核心库 ────────────────────────────────────
from agent_forge.agents import BaseAgent
from agent_forge.bus import LoggingInterceptor, Message, MessageBus, MessageIntent
from agent_forge.tools import ALL_TOOLS
from agent_forge.utils import print_info, print_separator, safe_print

# ============================================================
# Step 1: BaseAgent 最简用法
# ============================================================

def run_step1() -> None:
    """用 BaseAgent 创建 Agent，对比 phase0_demo 的手动构建。

    phase0_demo Step 3 需要：
    - 手动定义 AgentState
    - 手动写 agent_node / tool_node / should_continue 函数
    - 手动构建 StateGraph 并编译
    - 手动处理 SystemMessage 注入

    现在只需要：
    - BaseAgent(name="...", role="...", tools=[...])
    - agent.run("任务描述")

    代码量从 100+ 行降到 3 行，但功能完全等价。
    这就是抽象的价值——把重复的模式提取出来，让使用者聚焦于业务逻辑。
    """
    print_separator("阶段 1 Demo — Step 1：BaseAgent 最简用法", 60)
    print_info("对比 phase0_demo Step 3，现在创建 Agent 只需 3 行代码")
    safe_print()

    # ── 3 行创建一个完整的 Agent ──
    agent = BaseAgent(
        name="assistant",
        role="通用 AI 助手",
        tools=ALL_TOOLS,
    )
    safe_print(f"[INFO] Agent 已创建: {agent}")
    safe_print()

    # ── 交互循环 ──
    run_interactive_loop(agent, step_name="Step 1")


# ============================================================
# Step 2: Agent + MessageBus 单 Agent 自通信
# ============================================================

def run_step2() -> None:
    """展示 MessageBus 如何让 Agent 的行为"可见"。

    核心概念：可观测性（Observability）

    在 Step 1 中，Agent 是一个黑盒——输入任务，输出结果，
    中间发生了什么只有看 LLM 的原始输出才知道。

    有了 MessageBus，Agent 的每个关键行为都会自动发布事件：
    - agent.started   → Agent 开始处理任务
    - agent.thinking  → Agent 正在推理
    - agent.tool_request → Agent 请求调用工具
    - agent.tool_result  → 工具执行结果
    - agent.completed → Agent 处理完成

    通过 LoggingInterceptor，这些事件被实时打印出来。
    这就像给 Agent 装了一个"X 光机"——不用拆开就能看到内部运转。

    与 CrewAI/AutoGen 的对比：
    - CrewAI 的 Agent 日志混杂在 stdout 中，没有结构化
    - AutoGen 有对话日志，但格式是自由文本
    - 我们的方案：结构化事件 + 统一总线 + 可插拔拦截器
    """
    print_separator("阶段 1 Demo — Step 2：MessageBus 观测", 60)
    print_info("Agent 的每个行为都会通过 MessageBus 发布事件")
    print_info("LoggingInterceptor 实时打印所有事件")
    safe_print()

    # ── 创建 MessageBus + 日志拦截器 ──
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())

    # 额外订阅：用通配符 "*" 接收所有消息
    # 展示 MessageBus 的订阅机制
    event_count = {"count": 0}

    def count_events(msg: Message) -> None:
        event_count["count"] += 1

    bus.subscribe("*", count_events)

    # ── 创建 Agent（绑定 Bus）──
    agent = BaseAgent(
        name="observer-agent",
        role="可观测的 AI 助手",
        tools=ALL_TOOLS,
        bus=bus,
    )
    safe_print(f"[INFO] Agent 已创建并绑定 MessageBus: {agent}")
    safe_print()
    safe_print("提示：注意观察 [BUS] 开头的日志行，它们是 MessageBus 拦截器输出的事件")
    safe_print()

    # ── 交互循环 ──
    run_interactive_loop(agent, step_name="Step 2")

    # ── 展示统计 ──
    safe_print(f"\n[INFO] 本次会话共发布 {event_count['count']} 个事件")
    safe_print(f"[INFO] 消息历史共 {len(bus.get_history())} 条")


# ============================================================
# Step 3: 双 Agent 协作
# ============================================================

def run_step3() -> None:
    """两个 Agent 通过 Message Bus 协作完成任务。

    场景：用户输入一个编程任务
    1. Coder Agent 编写代码
    2. 结果通过 MessageBus 传递给 Reviewer Agent
    3. Reviewer Agent 审查代码并给出反馈

    关键概念：
    - REQUEST-RESPONSE 配对：Coder 发出 REQUEST，Reviewer 收到后处理
    - 消息追溯：/history 命令查看完整的消息链
    - 解耦：Coder 不知道 Reviewer 的存在，它们只和 Bus 通信

    注意：这里的编排是手动的（人工控制流程）。
    阶段 2将引入 Orchestrator 来自动编排多 Agent 协作。
    """
    print_separator("阶段 1 Demo — Step 3：双 Agent 协作", 60)
    print_info("Coder Agent 编写代码 → MessageBus 传递 → Reviewer Agent 审查")
    print_info("输入 /history 查看消息历史，输入 /quit 退出")
    safe_print()

    # ── 创建 MessageBus + 日志拦截器 ──
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())

    # ── 创建两个 Agent ──
    coder = BaseAgent(
        name="coder",
        role="资深 Python 工程师，擅长编写简洁、可读的代码",
        tools=ALL_TOOLS,
        bus=bus,
    )

    reviewer = BaseAgent(
        name="reviewer",
        role="代码审查专家，关注安全性、性能和代码风格",
        tools=[],  # Reviewer 只需要读代码，不需要工具
        bus=bus,
    )

    safe_print(f"[INFO] Coder:   {coder}")
    safe_print(f"[INFO] Reviewer: {reviewer}")
    safe_print()

    # ── 交互循环 ──
    safe_print("输入编程任务（输入 /history 查看消息历史，/quit 退出）：")
    safe_print('试试："写一个计算斐波那契数列的函数"')
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

        # ── /history 命令 ──
        if user_input.lower() == "/history":
            show_history(bus)
            continue

        # ── 阶段 1: Coder 编码 ──
        safe_print(f"\n{'─' * 40}")
        safe_print("  [阶段 1] Coder Agent 开始编码...")
        safe_print(f"{'─' * 40}")

        coder_result = coder.run(user_input)
        safe_print(f"\n  [Coder 产出]\n{coder_result}")

        # ── 通过 MessageBus 传递：Coder → Reviewer ──
        # 手动发布一条 REQUEST 消息
        request_msg = Message(
            role="coder",
            intent=MessageIntent.REQUEST,
            payload={
                "task": "审查以下代码",
                "code_output": coder_result,
                "original_request": user_input,
            },
        )
        bus.publish(request_msg)

        # ── 阶段 2: Reviewer 审查 ──
        safe_print(f"\n{'─' * 40}")
        safe_print("  [阶段 2] Reviewer Agent 开始审查...")
        safe_print(f"{'─' * 40}")

        review_prompt = (
            f"请审查以下代码产出。\n"
            f"原始需求：{user_input}\n\n"
            f"Coder 的产出：\n{coder_result}\n\n"
            f"请从安全性、性能、代码风格三个维度给出审查意见。"
        )
        review_result = reviewer.run(review_prompt)
        safe_print(f"\n  [Reviewer 审查意见]\n{review_result}")

        # Reviewer 发布 RESPONSE
        response_msg = Message(
            role="reviewer",
            intent=MessageIntent.RESPONSE,
            payload={"review": review_result},
            reply_to=request_msg.message_id,
        )
        bus.publish(response_msg)

        safe_print(f"\n{'─' * 40}")
        safe_print(f"  消息历史共 {len(bus.get_history())} 条")
        safe_print(f"  其中 REQUEST: {len(bus.get_history(intent=MessageIntent.REQUEST))} 条")
        safe_print(f"  其中 RESPONSE: {len(bus.get_history(intent=MessageIntent.RESPONSE))} 条")
        safe_print(f"{'─' * 40}")


# ============================================================
# 共享工具函数
# ============================================================

def run_interactive_loop(agent: BaseAgent, step_name: str) -> None:
    """运行 Agent 交互循环。"""
    safe_print("输入你的任务（输入 /quit 退出）：")
    safe_print('试试："读一下 README.md 的内容"')
    safe_print('试试："看看当前目录下有哪些文件"')
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

        safe_print(f"\n{'─' * 40}")
        safe_print(f"  [{step_name}] Agent 处理中...")
        safe_print(f"{'─' * 40}")

        try:
            result = agent.run(user_input)
            safe_print(f"\n  [Agent] {result}\n")
        except Exception as e:
            safe_print(f"  [错误] {type(e).__name__}: {e}")
            safe_print("  提示：检查 .env 中的 DEEPSEEK_API_KEY 是否正确配置")

        safe_print(f"{'─' * 40}")


def show_history(bus: MessageBus) -> None:
    """格式化显示消息历史。"""
    history = bus.get_history(limit=100)
    if not history:
        safe_print("\n[消息历史] 空（还没有任何消息）")
        return

    safe_print(f"\n{'═' * 60}")
    safe_print(f"  消息历史（共 {len(history)} 条）")
    safe_print(f"{'═' * 60}")

    for i, msg in enumerate(history, 1):
        intent_str = msg.intent.value.upper()
        reply_info = f" (reply_to: {msg.reply_to[:8]}...)" if msg.reply_to else ""
        safe_print(
            f"  {i:3d}. [{intent_str:>10}] "
            f"{msg.role:<12} | "
            f"{str(msg.payload)[:50]}"
            f"{reply_info}"
        )

    safe_print(f"{'═' * 60}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    step = "1"
    if len(sys.argv) > 2 and sys.argv[1] == "--step":
        step = sys.argv[2]

    steps = {"1": run_step1, "2": run_step2, "3": run_step3}

    if step not in steps:
        safe_print(f"错误：未知步骤 '{step}'。可选：1, 2, 3")
        sys.exit(1)

    try:
        safe_print(f"\n[AgentForge] Phase 1 Agent Demo — Step {step}\n")
    except UnicodeEncodeError:
        safe_print(f"\nStarting Phase 1 Agent Demo — Step {step}\n")

    steps[step]()
