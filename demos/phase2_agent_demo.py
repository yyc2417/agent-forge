"""阶段 2 Agent Demo —— 三步渐进式学习

学习目标：理解多 Agent 编排的设计演进，从"手动控制"到"自动编排"。

三步设计：
    Step 1（Specialist 独立运行）：Coder 编码 + Reviewer 独立审查
        → 理解 Specialist 是 BaseAgent 的子类，各自独立
        → 没有编排，手动传递结果

    Step 2（手动编排）：Coder → Reviewer 顺序执行 + 条件回退
        → 手动控制执行顺序和回退逻辑
        → 通过 Bus 日志观察 REQUEST-RESPONSE 配对

    Step 3（Orchestrator 自动编排）：LLM 拆解 + StateGraph 驱动
        → Orchestrator 用 LLM 自动拆解任务
        → StateGraph 驱动工作流：decompose → execute → review → aggregate
        → 对比 Step 2 体会自动编排的价值

使用方式：
    python demos/phase2_agent_demo.py --step 1
    python demos/phase2_agent_demo.py --step 2
    python demos/phase2_agent_demo.py --step 3

前置条件：
    1. 已配置 .env 中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖
"""

import sys

from agent_forge.agents import CoderAgent, Orchestrator, ReviewerAgent
from agent_forge.bus import LoggingInterceptor, Message, MessageBus, MessageIntent
from agent_forge.utils import print_info, print_separator, safe_print

# ============================================================
# Step 1: Specialist 独立运行
# ============================================================

def run_step1() -> None:
    """Specialist 独立运行 —— 感受专业 Agent 的能力。

    对比 phase1_demo Step 1（通用 BaseAgent）：
    - phase1: agent = BaseAgent(name="assistant", role="通用助手", tools=ALL_TOOLS)
    - phase2: coder = CoderAgent()  ← 预定义好 name/role/tools/prompt

    Specialist 就是 BaseAgent 的子类，只定制了"我是谁"和"我能做什么"。
    两个 Specialist 各自独立运行，互不知道对方的存在。
    """
    print_separator("阶段 2 Demo — Step 1：Specialist 独立运行", 60)
    print_info("CoderAgent 和 ReviewerAgent 各自独立完成任务")
    print_info("对比 phase1 的通用 BaseAgent，体会专业 Agent 的角色化设计")
    safe_print()

    # ── 创建 Specialist ──
    # 对比 phase1 Step 1：
    #   agent = BaseAgent(name="assistant", role="通用助手", tools=ALL_TOOLS)
    # 现在只需一行，name/role/tools/prompt 都已预定义
    coder = CoderAgent()
    reviewer = ReviewerAgent()

    safe_print(f"[INFO] {coder}")
    safe_print(f"[INFO] {reviewer}")
    safe_print()

    # ── 交互循环 ──
    safe_print("输入编程任务（输入 /quit 退出）：")
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

        # Coder 独立编码
        safe_print(f"\n{'─' * 40}")
        safe_print("  [Coder] 编码中...")
        safe_print(f"{'─' * 40}")
        code_result = coder.run(user_input)
        safe_print(f"\n  [Coder 产出]\n{code_result}")

        # Reviewer 独立审查
        safe_print(f"\n{'─' * 40}")
        safe_print("  [Reviewer] 审查中...")
        safe_print(f"{'─' * 40}")
        review_result = reviewer.run(
            f"请审查以下代码产出：\n原始需求：{user_input}\n\n"
            f"代码：\n{code_result}"
        )
        safe_print(f"\n  [Reviewer 审查意见]\n{review_result}")

        safe_print(f"\n{'─' * 40}")
        safe_print("  注意：两个 Agent 各自独立，没有编排，结果手动传递")
        safe_print(f"{'─' * 40}")


# ============================================================
# Step 2: 手动编排（顺序执行 + 条件回退）
# ============================================================

def run_step2() -> None:
    """手动编排 —— Coder → Reviewer 顺序执行 + 条件回退。

    对比 Step 1：
    - Step 1: 两个 Agent 独立，结果手动传递
    - Step 2: 手动控制流程（for 循环 + if/else），加入回退机制

    对比 Step 3：
    - Step 2: 人工写 for 循环控制流程（硬编码编排）
    - Step 3: Orchestrator 用 LLM + StateGraph 自动编排

    新增功能：
    - MessageBus + LoggingInterceptor：观察 Agent 间的消息流
    - 条件回退：Reviewer 不通过 → 反馈给 Coder → 重新编码
    - /history 命令：查看完整消息链
    """
    print_separator("阶段 2 Demo — Step 2：手动编排 + 条件回退", 60)
    print_info("Coder → Reviewer 顺序执行，审查不通过则回退重新编码")
    print_info("注意观察 [BUS] 日志，这是 MessageBus 拦截器输出的事件流")
    safe_print()

    # ── 创建 MessageBus + 日志拦截器 ──
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())

    # ── 创建 Specialist（共享 Bus）──
    coder = CoderAgent(bus=bus)
    reviewer = ReviewerAgent(bus=bus)

    safe_print(f"[INFO] {coder}")
    safe_print(f"[INFO] {reviewer}")
    safe_print("[INFO] MessageBus 已启用（LoggingInterceptor）")
    safe_print()

    # ── 交互循环 ──
    safe_print("输入编程任务（输入 /history 查看消息历史，/quit 退出）：")
    safe_print('试试："写一个计算斐波那契数列的函数"')
    safe_print()

    max_retries = 2

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
        if user_input.lower() == "/history":
            show_history(bus)
            continue

        # ── 阶段 1: Coder 编码 ──
        safe_print(f"\n{'─' * 40}")
        safe_print("  [阶段 1] Coder 编码")
        safe_print(f"{'─' * 40}")

        # 手动发布 REQUEST 事件（可观测性）
        bus.publish(Message(
            role="orchestrator",
            intent=MessageIntent.REQUEST,
            payload={"target_agent": "coder", "task": user_input},
        ))
        code_result = coder.run(user_input)
        safe_print(f"\n  [Coder 产出]\n{code_result}")

        # 手动发布 RESPONSE 事件
        bus.publish(Message(
            role="coder",
            intent=MessageIntent.RESPONSE,
            payload={"result_preview": code_result[:200]},
        ))

        # ── 阶段 2: Reviewer 审查 + 条件回退 ──
        for attempt in range(max_retries + 1):
            safe_print(f"\n{'─' * 40}")
            safe_print(f"  [阶段 2] Reviewer 审查 (尝试 {attempt + 1}/{max_retries + 1})")
            safe_print(f"{'─' * 40}")

            bus.publish(Message(
                role="orchestrator",
                intent=MessageIntent.REQUEST,
                payload={"target_agent": "reviewer", "task": "审查代码"},
            ))

            review_result = reviewer.run(
                f"请审查以下代码（原始需求：{user_input}）：\n{code_result}"
            )
            safe_print(f"\n  [Reviewer 审查意见]\n{review_result}")

            bus.publish(Message(
                role="reviewer",
                intent=MessageIntent.RESPONSE,
                payload={"result_preview": review_result[:200]},
            ))

            # 判断审查结果
            passed = "通过" in review_result and "不通过" not in review_result

            if passed:
                safe_print("\n  [结果] 审查通过!")
                break
            elif attempt < max_retries:
                safe_print("\n  [结果] 审查不通过，回退到 Coder 修改...")

                # 回退：把审查意见反馈给 Coder
                bus.publish(Message(
                    role="orchestrator",
                    intent=MessageIntent.REQUEST,
                    payload={"target_agent": "coder", "task": "根据审查意见修改"},
                ))
                code_result = coder.run(
                    f"根据审查意见修改代码：\n"
                    f"审查意见：{review_result}\n"
                    f"原始需求：{user_input}\n"
                    f"当前代码：\n{code_result}"
                )
                safe_print(f"\n  [Coder 修改后]\n{code_result}")

                bus.publish(Message(
                    role="coder",
                    intent=MessageIntent.RESPONSE,
                    payload={"result_preview": code_result[:200]},
                ))
            else:
                safe_print("\n  [结果] 已达最大重试次数，使用当前版本")

        safe_print(f"\n{'─' * 40}")
        safe_print(f"  消息历史共 {len(bus.get_history())} 条")
        safe_print("  输入 /history 查看完整消息链")
        safe_print(f"{'─' * 40}")


# ============================================================
# Step 3: Orchestrator 自动编排
# ============================================================

def run_step3() -> None:
    """Orchestrator 自动编排 —— LLM 拆解 + StateGraph 驱动。

    对比 Step 2：
    - Step 2: 人工写 for 循环 + if/else 控制流程
    - Step 3: 只需输入任务，Orchestrator 自动完成拆解、调度、审查、汇总

    Orchestrator 内部流程（StateGraph 驱动）：
    1. decompose: LLM 拆解任务为 SubTask 列表
    2. execute: 依次将 SubTask 分发给对应 Specialist
    3. review: Reviewer 审查 Coder 产出
    4. aggregate: 汇总所有产出为最终报告

    如果 review 不通过，StateGraph 自动回退到 execute 重新执行。
    """
    print_separator("阶段 2 Demo — Step 3：Orchestrator 自动编排", 60)
    print_info("只需输入任务，Orchestrator 自动拆解、调度、审查、汇总")
    print_info("StateGraph 驱动：decompose -> execute -> review -> aggregate")
    safe_print()

    # ── 创建 MessageBus + 日志拦截器 ──
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())

    # ── 创建 Specialist 团队 ──
    coder = CoderAgent(bus=bus)
    reviewer = ReviewerAgent(bus=bus)
    specialists = {"coder": coder, "reviewer": reviewer}

    # ── 创建 Orchestrator ──
    orchestrator = Orchestrator(
        specialists=specialists,
        bus=bus,
        max_retries=2,
    )

    safe_print(f"[INFO] Orchestrator: {orchestrator}")
    safe_print(f"[INFO] Specialists: {list(specialists.keys())}")
    safe_print("[INFO] MessageBus 已启用（LoggingInterceptor）")
    safe_print()

    # ── 交互循环 ──
    safe_print("输入任务（输入 /history 查看消息历史，/quit 退出）：")
    safe_print('试试："帮我写一个 Python 的用户登录验证模块"')
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
        if user_input.lower() == "/history":
            show_history(bus)
            continue

        # ── Orchestrator 自动编排 ──
        safe_print(f"\n{'═' * 50}")
        safe_print("  [Orchestrator] 开始自动编排...")
        safe_print(f"{'═' * 50}")

        result = orchestrator.run(user_input)

        safe_print(f"\n{'═' * 50}")
        safe_print("  [最终输出]")
        safe_print(f"{'═' * 50}")
        safe_print(result)

        safe_print(f"\n{'─' * 40}")
        safe_print(f"  消息历史共 {len(bus.get_history())} 条")
        safe_print("  输入 /history 查看完整编排过程")
        safe_print(f"{'─' * 40}")


# ============================================================
# 共享工具函数
# ============================================================

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
            f"{msg.role:<14} | "
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
        safe_print(f"\n[AgentForge] Phase 2 Agent Demo — Step {step}\n")
    except UnicodeEncodeError:
        safe_print(f"\nStarting Phase 2 Agent Demo — Step {step}\n")

    steps[step]()
