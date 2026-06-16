"""阶段 3 Agent Demo —— 三步渐进式学习

学习目标：理解记忆系统、工具权限、生命周期 Hooks 的设计和使用。

三步设计：
    Step 1（记忆系统）：ShortTermMemory + LongTermMemory + 带记忆的 Agent
        → 短期记忆：多轮对话上下文保持
        → 长期记忆：跨会话知识存储（store/recall/list 工具）

    Step 2（工具权限 + Hooks + Token 追踪）：
        → ToolRegistry 按权限级别分配工具
        → HookManager 注册生命周期回调
        → CostTracker 统计 Token 成本

    Step 3（全栈集成）：Orchestrator + 记忆 + 权限 + Hooks + 成本 + 会话保存
        → 所有阶段 3功能整合到 Orchestrator 编排流程

使用方式：
    python demos/phase3_agent_demo.py --step 1
    python demos/phase3_agent_demo.py --step 2
    python demos/phase3_agent_demo.py --step 3

前置条件：
    1. 已配置 .env 中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖
"""

import sys

from agent_forge.agents import BaseAgent, CoderAgent, Orchestrator, ReviewerAgent
from agent_forge.bus import LoggingInterceptor, MessageBus
from agent_forge.cost import CostTracker
from agent_forge.hooks import HookManager
from agent_forge.memory import LongTermMemory, SessionManager, ShortTermMemory, create_memory_tools
from agent_forge.tools import ToolPermission, ToolRegistry, grep_search, read_file, run_shell, write_file
from agent_forge.utils import print_info, print_separator, safe_print

# ============================================================
# Step 1: 记忆系统
# ============================================================

def run_step1() -> None:
    """记忆系统演示 —— ShortTermMemory + LongTermMemory + 带记忆的 Agent。

    对比 phase2 Step 1：
    - phase2: 无记忆的 Specialist，每轮对话都是全新上下文
    - phase3: 有记忆的 Agent，能记住之前的对话内容

    演示内容：
    1. ShortTermMemory 独立演示（滑动窗口行为）
    2. LongTermMemory 独立演示（store/recall/search）
    3. 带记忆的 Agent 多轮对话
    """
    print_separator("阶段 3 Demo — Step 1：记忆系统", 60)
    print_info("演示 ShortTermMemory（滑动窗口）+ LongTermMemory（持久化存储）")
    safe_print()

    # ── 1. ShortTermMemory 独立演示 ──
    safe_print(f"{'─' * 40}")
    safe_print("  [1] ShortTermMemory 滑动窗口演示")
    safe_print(f"{'─' * 40}")

    stm = ShortTermMemory(max_messages=5)
    safe_print("  创建 ShortTermMemory(max_messages=5)")

    from langchain_core.messages import AIMessage, HumanMessage

    for i in range(8):
        stm.add(HumanMessage(content=f"第 {i + 1} 轮用户输入"))
        if i % 2 == 0:
            stm.add(AIMessage(content=f"第 {i + 1} 轮 Agent 回复"))

    safe_print(f"  添加 8 轮对话后：{stm}")
    safe_print(f"  窗口内消息数：{len(stm.get_messages())}")
    safe_print(f"  是否有摘要：{'是' if stm.get_summary() else '否'}")
    if stm.get_summary():
        safe_print(f"  摘要内容：{stm.get_summary()[:100]}...")
    safe_print()

    # ── 2. LongTermMemory 独立演示 ──
    safe_print(f"{'─' * 40}")
    safe_print("  [2] LongTermMemory 持久化存储演示")
    safe_print(f"{'─' * 40}")

    ltm = LongTermMemory(file_path=".agentforge/demo_memory.json")
    ltm.store("project_name", "AgentForge", tags="project,config")
    ltm.store("project_lang", "Python 3.11+", tags="project,config")
    ltm.store("author_name", "宇诚", tags="personal")

    safe_print(f"  存储 3 条记忆后：{ltm}")
    safe_print()
    safe_print(f"  recall('project_name'): {ltm.recall('project_name')}")
    safe_print(f"  search('project'): {ltm.search('project')}")
    safe_print(f"  list_memories(): {ltm.list_memories()}")
    safe_print()

    # ── 3. 带记忆的 Agent 多轮对话 ──
    safe_print(f"{'─' * 40}")
    safe_print("  [3] 带记忆的 Agent 多轮对话")
    safe_print(f"{'─' * 40}")

    memory = ShortTermMemory(max_messages=10)
    agent = BaseAgent(
        name="assistant",
        role="智能助手，能够记住之前的对话内容",
        tools=[read_file] + create_memory_tools(ltm),
        memory=memory,
    )

    safe_print(f"  创建带记忆的 Agent：{agent}")
    safe_print(f"  工具列表：{[t.name for t in agent._tools]}")
    safe_print()

    # 多轮对话交互
    safe_print("输入消息与 Agent 对话（输入 /quit 退出）：")
    safe_print('试试："请记住我的名字叫宇诚"')
    safe_print('然后："我的名字叫什么？"')
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

        result = agent.run(user_input)
        safe_print(f"\n  [Agent] {result}")
        safe_print(f"  [记忆状态] {memory}")


# ============================================================
# Step 2: 工具权限 + Hooks + Token 追踪
# ============================================================

def run_step2() -> None:
    """工具权限 + Hooks + Token 追踪演示。

    演示内容：
    1. ToolRegistry 按权限级别分配工具
    2. HookManager 注册生命周期回调
    3. CostTracker 统计 Token 成本并打印报告
    """
    print_separator("阶段 3 Demo — Step 2：工具权限 + Hooks + Token 追踪", 60)
    print_info("ToolRegistry 权限控制 + HookManager 生命周期回调 + CostTracker 成本统计")
    safe_print()

    # ── 1. ToolRegistry 权限控制 ──
    safe_print(f"{'─' * 40}")
    safe_print("  [1] ToolRegistry 权限控制")
    safe_print(f"{'─' * 40}")

    registry = ToolRegistry()
    registry.register(read_file, ToolPermission.READ)
    registry.register(grep_search, ToolPermission.READ)
    registry.register(write_file, ToolPermission.WRITE)
    registry.register(run_shell, ToolPermission.EXECUTE)

    safe_print(f"  已注册工具：{registry.list_tools()}")
    safe_print()

    read_tools = registry.get_tools(ToolPermission.READ)
    safe_print(f"  READ 权限工具：{[t.name for t in read_tools]}")

    write_tools = registry.get_tools(ToolPermission.WRITE)
    safe_print(f"  WRITE 权限工具：{[t.name for t in write_tools]}")

    exec_tools = registry.get_tools(ToolPermission.EXECUTE)
    safe_print(f"  EXECUTE 权限工具：{[t.name for t in exec_tools]}")
    safe_print()

    # ── 2. 只读 Agent vs 全权限 Agent ──
    safe_print(f"{'─' * 40}")
    safe_print("  [2] 只读 Agent vs 全权限 Agent")
    safe_print(f"{'─' * 40}")

    # 只读 Agent（只能 read_file 和 grep_search）
    reader = BaseAgent(
        name="reader",
        role="只读助手，只能查看文件不能修改",
        tools=registry.get_tools(ToolPermission.READ),
    )
    safe_print(f"  只读 Agent：{reader}")
    safe_print(f"  工具列表：{[t.name for t in reader._tools]}")

    # 全权限 Agent
    developer = BaseAgent(
        name="developer",
        role="全栈开发者，拥有所有工具权限",
        tools=registry.get_tools(ToolPermission.EXECUTE),
    )
    safe_print(f"  全权限 Agent：{developer}")
    safe_print(f"  工具列表：{[t.name for t in developer._tools]}")
    safe_print()

    # ── 3. Hooks + Token 追踪 ──
    safe_print(f"{'─' * 40}")
    safe_print("  [3] Hooks + Token 追踪")
    safe_print(f"{'─' * 40}")

    hooks = HookManager()
    hook_log = []

    def on_pre_llm(**kwargs):
        msg = f"[{kwargs['agent']}] LLM 调用前，消息数: {len(kwargs['messages'])}"
        hook_log.append(msg)
        safe_print(f"  [Hook] {msg}")

    def on_post_tool(**kwargs):
        msg = f"[{kwargs['agent']}] 工具 {kwargs['tool_name']} 执行完成"
        hook_log.append(msg)
        safe_print(f"  [Hook] {msg}")

    hooks.register("pre_llm_call", on_pre_llm)
    hooks.register("post_tool_use", on_post_tool)

    tracker = CostTracker(cost_per_1k_prompt=0.001, cost_per_1k_completion=0.002)

    agent = BaseAgent(
        name="tracked_agent",
        role="被追踪的 Agent",
        tools=[read_file, run_shell],
        hooks=hooks,
        cost_tracker=tracker,
    )

    safe_print("  创建带 Hooks 和 Token 追踪的 Agent")
    safe_print("  输入任务让 Agent 执行，观察 Hook 日志和 Token 统计")
    safe_print()
    safe_print("输入任务（输入 /report 查看成本报告，/quit 退出）：")
    safe_print('试试："读取 README.md 并统计行数"')
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
            break
        if user_input.lower() == "/report":
            tracker.print_report()
            continue

        result = agent.run(user_input)
        safe_print(f"\n  [Agent] {result}")

    # 最终成本报告
    safe_print(f"\n{'─' * 40}")
    safe_print("  Hook 日志汇总")
    safe_print(f"{'─' * 40}")
    for log in hook_log:
        safe_print(f"  {log}")

    tracker.print_report()


# ============================================================
# Step 3: 全栈集成
# ============================================================

def run_step3() -> None:
    """全栈集成 —— Orchestrator + 记忆 + 权限 + Hooks + 成本 + 会话保存。

    对比 phase2 Step 3：
    - phase2: Orchestrator 基本编排
    - phase3: Orchestrator + 记忆 + 权限 + Hooks + 成本追踪 + 会话保存

    演示内容：
    1. 共享的 CostTracker 和 HookManager
    2. Specialist 各自有独立的 ShortTermMemory
    3. 共享 LongTermMemory
    4. SessionManager 自动保存会话
    5. 运行完整编排任务，打印 Token 成本报告
    """
    print_separator("阶段 3 Demo — Step 3：全栈集成", 60)
    print_info("Orchestrator + 记忆 + Hooks + 成本追踪 + 会话保存")
    safe_print()

    # ── 共享基础设施 ──
    bus = MessageBus()
    bus.add_interceptor(LoggingInterceptor())

    tracker = CostTracker(cost_per_1k_prompt=0.001, cost_per_1k_completion=0.002)
    hooks = HookManager()

    llm_call_count = {"count": 0}

    def count_llm_calls(**kwargs):
        llm_call_count["count"] += 1

    hooks.register("pre_llm_call", count_llm_calls)

    shared_ltm = LongTermMemory(file_path=".agentforge/shared_memory.json")
    session_mgr = SessionManager()

    # ── 创建 Specialist ──
    coder = CoderAgent(
        bus=bus,
        memory=ShortTermMemory(max_messages=15),
        long_term_memory=shared_ltm,
        enable_memory_tools=True,
        hooks=hooks,
        cost_tracker=tracker,
    )

    reviewer = ReviewerAgent(
        bus=bus,
        memory=ShortTermMemory(max_messages=10),
        hooks=hooks,
        cost_tracker=tracker,
    )

    safe_print(f"  [Coder]     {coder}")
    safe_print(f"  [Reviewer]  {reviewer}")
    safe_print("  [Bus]       LoggingInterceptor 已启用")
    safe_print("  [Tracker]   CostTracker 已启用")
    safe_print("  [Memory]    共享 LongTermMemory + 各自 ShortTermMemory")
    safe_print()

    # ── 创建 Orchestrator ──
    orchestrator = Orchestrator(
        specialists={"coder": coder, "reviewer": reviewer},
        bus=bus,
    )

    # ── 交互循环 ──
    safe_print("输入编程任务（输入 /report 查看成本报告，/sessions 查看会话，/quit 退出）：")
    safe_print('试试："写一个 Python 的快速排序函数"')
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
            break
        if user_input.lower() == "/report":
            tracker.print_report()
            continue
        if user_input.lower() == "/sessions":
            sessions = session_mgr.list_sessions()
            if sessions:
                for s in sessions:
                    safe_print(f"  {s['id']} | {s['agent_name']} | {s['created']} | {s['message_count']} 条消息")
            else:
                safe_print("  无已保存的会话")
            continue

        # ── Orchestrator 编排 ──
        safe_print(f"\n{'═' * 50}")
        safe_print("  [Orchestrator] 开始自动编排...")
        safe_print(f"{'═' * 50}")

        result = orchestrator.run(user_input)

        safe_print(f"\n{'═' * 50}")
        safe_print("  [最终输出]")
        safe_print(f"{'═' * 50}")
        safe_print(result)

        # ── 保存会话 ──
        if coder.memory:
            sid = session_mgr.create_session("coder")
            session_mgr.save_session(sid, coder.memory)
            safe_print(f"\n  [会话] 已保存 Coder 会话: {sid}")

        # ── 成本报告 ──
        safe_print(f"\n  [统计] LLM 调用次数: {llm_call_count['count']}")
        tracker.print_report()

    # 退出时打印最终报告
    safe_print(f"\n{'═' * 50}")
    safe_print("  本次会话最终成本报告")
    safe_print(f"{'═' * 50}")
    tracker.print_report()


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
        safe_print(f"\n[AgentForge] Phase 3 Agent Demo — Step {step}\n")
    except UnicodeEncodeError:
        safe_print(f"\nStarting Phase 3 Agent Demo — Step {step}\n")

    steps[step]()
