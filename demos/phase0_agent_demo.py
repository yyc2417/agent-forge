"""阶段 0 Agent Demo —— 三步渐进式学习

学习目标：理解 Agent 循环的本质（ReAct 模式），从"会调 API"到"懂原理"。

三步设计：
    Step 1（最小跑通）：用 LangGraph 预构建的 create_react_agent 一行创建 Agent
        → 感受 ReAct 模式：LLM 循环「推理 → 行动 → 观察 → 推理」
        → 理解 Tool Calling：LLM 如何自动决定调用什么工具、传什么参数

    Step 2（理解原理）：手动用 StateGraph 构建相同的 Agent 循环
        → 揭开 create_react_agent 的黑盒
        → 理解节点（node）、条件边（conditional edge）、状态（state）

    Step 3（优化增强）：在 Step 2 基础上加入错误处理、安全防护、完整日志
        → 接近生产级的单 Agent 实现
        → 为后续多 Agent 协作打基础

使用方式：
    python demos/phase0_agent_demo.py --step 1    # 最小跑通版

交互命令：
    直接输入任务 → Agent 开始思考并执行
    /quit 或 /exit 或 /q → 退出

前置条件：
    1. 已配置 .env 文件中的 DEEPSEEK_API_KEY
    2. 已运行 uv pip install -e . 安装依赖

核心概念速查：
    ┌────────────────────────────────────────────────────────┐
    │  ReAct 循环 = Reasoning（推理）+ Acting（行动）          │
    │                                                        │
    │  用户输入                                               │
    │    │                                                   │
    │    ▼                                                   │
    │  ┌─────────┐   有 tool_calls    ┌──────────┐          │
    │  │  Agent  │ ─────────────────> │  Tools   │           │
    │  │  (LLM)  │                    │  (执行)   │           │
    │  └────┬────┘ <───────────────── └──────────┘          │
    │       │        返回 ToolMessage                         │
    │       │ 无 tool_calls                                   │
    │       ▼                                                │
    │     回复用户                                            │
    └────────────────────────────────────────────────────────┘

参考资料：
    - Lilian Weng: "LLM Powered Autonomous Agents"
      https://lilianweng.github.io/posts/2023-06-23-agent/
    - LangGraph Quick Start:
      https://langchain-ai.github.io/langgraph/tutorials/introduction/
"""

import sys
from typing import Annotated, Literal

# ─── LangChain 消息类型 ───────────────────────────────────
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# ─── LangGraph 核心 ────────────────────────────────────────
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from typing_extensions import TypedDict

# ─── 我们的库 ─────────────────────────────────────────────
from agent_forge.llm import create_deepseek_llm
from agent_forge.tools import ALL_TOOLS
from agent_forge.utils import print_info, print_separator, safe_print

# ============================================================
# 共享类型定义（Step 2 和 Step 3 共用）
# ============================================================

class AgentState(TypedDict):
    """Agent 的状态 —— 就是对话消息的累积列表。

    这是 LangGraph 的核心概念：StateGraph 的状态是一个 TypedDict。
    每次节点执行后，返回一个 dict，LangGraph 会把返回值合并到当前状态中。

    messages 字段用 Annotated[list, add_messages] 标记，表示：
    - 新消息不是"替换"旧消息，而是"追加"到列表末尾
    - add_messages 是 LangGraph 内置的 reducer，专门处理聊天气泡的追加逻辑
    - 重复的 ToolMessage 会被自动去重（基于 tool_call_id）

    为什么用 TypedDict 而不是 dataclass？
    - LangGraph 需要知道每个字段的类型来做状态合并
    - TypedDict 是标准 Python 类型注解，零运行时开销
    """
    messages: Annotated[list, add_messages]


# ============================================================
# Step 1: 最小跑通 —— 用 create_react_agent 一行搞定
# ============================================================

def run_step1() -> None:
    """第一步：用 LangGraph 预构建的 create_react_agent 创建 Agent。

    这是"我也能 5 分钟跑通"的版本——一行代码就创建一个能思考、能调工具的 Agent。

    但是！不要停在这里——这是别人会问的：
    "create_react_agent 内部做了什么？"
    如果你只会调 API 而答不上来，就暴露了。
    → 所以 Step 2 会带你手动实现一遍。

    学习要点：
        1. ReAct 模式：LLM 在循环中进行「推理(Reasoning) → 行动(Acting)」
        2. Tool Calling：LLM 自动决定何时调用哪个工具、传什么参数
        3. 消息流：
           HumanMessage → AIMessage(含 tool_calls) → ToolMessage → AIMessage → ...
                        └── LLM 决定调工具 ──┘  └── 工具执行结果 ──┘  └── LLM 再思考
    """
    print_separator("阶段 0 Agent Demo — 第一步：最小跑通", 60)
    print_info("这个版本用 LangGraph 预构建的 create_react_agent 一行创建 Agent")
    print_info("目标：感受 Agent 如何「自己决定」调用什么工具")
    safe_print()

    # ── 1. 创建 LLM ─────────────────────────────────────────
    # temperature=0.0 是关键：Agent 场景需要确定性，不然每次决策都可能不同
    llm = create_deepseek_llm(temperature=0.0)
    print_info(f"LLM 已连接：{llm.model_name}")
    # 2. 创建工具列表
    tools = ALL_TOOLS
    safe_print(f"[INFO] 已注册工具：{[t.name for t in tools]}")

    # 3. 一行创建 Agent
    agent = create_react_agent(llm, tools)
    safe_print("[INFO] Agent 已创建（ReAct 模式）\n")

    # 4. 交互循环
    safe_print("输入你的任务（输入 /quit 退出）：")
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

        safe_print("\n[Agent 思考中...]\n")
        result = agent.invoke({"messages": [("user", user_input)]})

        # 打印完整消息流（这样你能看到每一步发生了什么）
        for msg in result["messages"]:
            if msg.type == "human":
                # HumanMessage: 我们发给 Agent 的内容
                safe_print(f"  [你] {msg.content}")
            elif msg.type == "ai" and msg.content:
                # AIMessage: LLM 的回复（可能是最终答案，也可能是 tool_calls）
                safe_print(f"\n  [Agent] {msg.content}\n")
            elif msg.type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
                # AIMessage 包含了 tool_calls（但没有 content）
                for tc in msg.tool_calls:
                    safe_print(f"  [调用工具] {tc['name']}({tc['args']})")
            elif msg.type == "tool":
                # ToolMessage: 工具执行的结果
                preview = msg.content[:200]
                suffix = "..." if len(msg.content) > 200 else ""
                safe_print(f"  [结果: {msg.name}] {preview}{suffix}")

    # ── 5. 创建 Agent ──────────────────────────────────────
    # 一行代码，LangGraph 内部做了这些事：
    #   1. 为每个工具生成 JSON Schema（Function Calling 需要）
    #   2. 创建 StateGraph，定义 agent 节点和 tools 节点
    #   3. 设置条件边：agent 有 tool_calls → tools → agent → 循环
    #   4. 编译为可执行的 Runnable
    # Step 2 会手把手拆开这些步骤
    agent = create_react_agent(llm, ALL_TOOLS)
    print_info("Agent 已创建（ReAct 模式）")
    safe_print()

    # ── 6. 交互循环 ────────────────────────────────────────
    run_interactive_loop(
        agent=agent,
        step_name="Step 1",
        show_full_trace=True,  # Step 1 显示完整消息流，帮你理解
    )


# ============================================================
# Step 2: 理解原理 —— 手动构建 StateGraph
# ============================================================

def run_step2() -> None:
    """第二步：手动构建 StateGraph，揭开 create_react_agent 的黑盒。

    这是阶段 0最重要的学习环节。当别人问到"Agent 循环怎么实现的"，
    你不需要回忆某个框架的 API，而是直接在纸上画出这个状态图：

          用户输入
             │
             ▼
       ┌──────────┐
       │  agent   │ ← LLM 思考：该直接回复，还是调工具？
       │  node    │
       └────┬─────┘
            │
            │ should_continue 条件判断
            │
       ┌────┴────┐
       │          │
   有 tool_calls  无 tool_calls
       │          │
       ▼          ▼
   ┌──────────┐   END
   │  tools   │   （返回用户）
   │  node    │
   └────┬─────┘
        │ 执行完成后
        │ 总是返回
        ▼
   ┌──────────┐
   │  agent   │  ← LLM 拿到工具结果，重新思考
   │  node    │
   └──────────┘

    学习要点：
        1. StateGraph = 节点（函数）+ 边（条件路由）+ 状态（共享数据）
        2. bind_tools() 是让 LLM 知道有哪些工具可用的关键一步
        3. should_continue 是 Agent 循环的核心：判断何时继续、何时停止
    """
    print_separator("阶段 0 Agent Demo — 第二步：理解原理（手动 StateGraph）", 60)
    print_info("这个版本手动构建 StateGraph，相当于 create_react_agent 的内部实现")
    print_info("目标：理解 Agent 循环 = 节点 + 条件边 + 状态")
    safe_print()

    # ── 1. 创建 LLM 并绑定工具 ─────────────────────────────
    llm = create_deepseek_llm(temperature=0.0)
    tools_by_name = {t.name: t for t in ALL_TOOLS}  # 快速查找表

    # bind_tools() 是关键：它把工具的 JSON Schema 注入 LLM 的请求中
    # DeepSeek 收到 Schema 后，会在推理时"知道"有哪些工具、每个工具需要什么参数
    # 这是一个零配置的过程——不需要写规则，只需要定义工具的 docstring/type hints
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    # ── 2. 定义节点（Node）────────────────────────────────
    # 节点就是普通的 Python 函数，接收 State，返回 State 的部分更新

    def agent_node(state: AgentState) -> dict:
        """Agent 节点：调用 LLM 决定下一步。

        这是 Agent 的"大脑"：
        - 接收完整的对话历史（state["messages"]）
        - LLM 分析当前状态，决定：
          a) 直接回复用户（返回 AIMessage，content 有值，tool_calls 为空）
          b) 调用工具（返回 AIMessage，tool_calls 有值，content 为空）
        - 返回的消息会被 add_messages reducer 追加到状态中

        Args:
            state: 当前 Agent 状态，包含完整对话历史

        Returns:
            {"messages": [新消息]} — LangGraph 会自动合并到状态中
        """
        messages = state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def tool_node(state: AgentState) -> dict:
        """工具节点：执行 LLM 请求的工具调用。

        当 LLM 决定"我需要调工具"时，消息流会路由到这里。
        本节点的职责：
        1. 取出 LLM 最后一条消息中的 tool_calls 列表
        2. 逐一执行每个工具调用
        3. 将每个结果包装为 ToolMessage 返回

        ToolMessage 的 tool_call_id 很重要：它告诉 LangGraph 这个结果
        对应哪个 tool_call，这样 add_messages reducer 才能正确去重。

        Args:
            state: 当前 Agent 状态

        Returns:
            {"messages": [ToolMessage, ...]} — 每个工具调用一个 ToolMessage
        """
        messages = state["messages"]
        last_message = messages[-1]  # 最后一条是 AIMessage（含 tool_calls）
        tool_calls = last_message.tool_calls

        results: list[ToolMessage] = []
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            safe_print(f"  [工具执行] {tool_name}({tool_args})")

            tool = tools_by_name.get(tool_name)
            if tool:
                output = tool.invoke(tool_args)
            else:
                output = f"错误：未知工具 '{tool_name}'"
                safe_print(f"  [警告] 未知工具：{tool_name}")

            results.append(
                ToolMessage(
                    content=str(output),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )

        return {"messages": results}

    def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        """条件路由：判断是继续调工具还是结束。

        这是 Agent 循环的核心决策点：
        - 如果 LLM 的最后一条消息包含 tool_calls → 路由到 "tools" 节点
        - 否则（LLM 给出了最终回复） → 路由到 "__end__"（结束）

        注意：这个函数不修改状态，只做判断。LangGraph 用返回值来决定
        走哪条边。

        Args:
            state: 当前 Agent 状态

        Returns:
            "tools" — 需要执行工具调用
            "__end__" — Agent 循环结束，返回结果给用户
        """
        messages = state["messages"]
        last_message = messages[-1]

        # 检查 LLM 是否请求了工具调用
        # AIMessage.tool_calls 存在且非空 → LLM 想调工具
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "__end__"

    # ── 3. 构建状态图（StateGraph）─────────────────────────
    # 这是整个 Agent 的骨架：
    #   入口 → agent → [判断] → tools → agent → [判断] → ... → END
    #
    # 每一步的含义：
    #   add_node("agent", agent_node)     — 注册 agent 节点
    #   add_node("tools", tool_node)      — 注册 tools 节点
    #   set_entry_point("agent")          — 运行从 agent 节点开始
    #   add_conditional_edges(...)        — agent 执行完后根据条件路由
    #   add_edge("tools", "agent")        — tools 执行完后总是回到 agent

    graph = StateGraph(AgentState)

    # 注册节点
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    # 设置入口
    graph.set_entry_point("agent")

    # 设置条件边：agent 节点执行完后，根据 should_continue 的结果路由
    # - 返回 "tools" → 走 tools 节点
    # - 返回 "__end__" → 结束
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "__end__": END,
        }
    )

    # 工具执行完后，结果送回 agent 重新思考
    # 这就是 ReAct 循环的 "观察 → 推理" 环节
    graph.add_edge("tools", "agent")

    # 编译为可执行对象
    compiled_agent = graph.compile()
    print_info("StateGraph Agent 已编译（手动构建版）")
    safe_print()

    # ── 4. 交互循环 ────────────────────────────────────────
    run_interactive_loop(
        agent=compiled_agent,
        step_name="Step 2",
        show_full_trace=True,
        recursion_limit=10,  # 最多 10 轮 ReAct 循环，防止死循环
    )


# ============================================================
# Step 3: 优化增强 —— 接近生产级的单 Agent
# ============================================================

def run_step3() -> None:
    """第三步：在 Step 2 基础上加入健壮性处理。

    新增功能：
        1. LLM 调用错误处理：API 挂了不会 crash，而是优雅降级
        2. 工具执行错误处理：单个工具失败不影响其他工具
        3. 防无限循环：双重保护（recursion_limit + 轮数计数器）
        4. 详细的执行日志：每一步都清晰可见

    设计决策记录：
        - 为什么 ai_count > 5 就终止？经验值。大多数任务 2-3 轮就完成了。
          超过 5 轮通常意味着 Agent 陷入循环或任务本身不可完成。
        - 为什么不在 tool_node 中抛出异常？因为 ToolMessage 已经包含了错误信息，
          让 LLM 自己根据错误信息调整策略，比直接 crash 更优雅。
    """
    print_separator("阶段 0 Agent Demo — 第三步：优化增强", 60)
    print_info("在 Step 2 基础上加入错误处理 + 循环保护 + 详细日志")
    print_info("目标：接近生产级的单 Agent 实现")
    safe_print()

    # ── 1. 创建 LLM ─────────────────────────────────────────
    llm = create_deepseek_llm(temperature=0.0)
    tools_by_name = {t.name: t for t in ALL_TOOLS}
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    # ── 2. 增强版节点定义 ──────────────────────────────────

    def agent_node(state: AgentState) -> dict:
        """增强版 Agent 节点：带 LLM 调用错误处理。

        改进点：
            - try/except 包裹 LLM 调用，防止 API 错误导致整个 Agent 崩溃
            - 失败时返回 AIMessage（而非抛出异常），让调用者可以优雅处理
        """
        messages = state["messages"]
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            # API 挂了、网络断了、账号欠费了……各种可能
            # 不 crash，而是返回错误消息让上层处理
            error_msg = f"[LLM 调用失败] {type(e).__name__}: {e}"
            safe_print(f"  {error_msg}")
            return {"messages": [AIMessage(content=error_msg)]}
        return {"messages": [response]}

    def tool_node(state: AgentState) -> dict:
        """增强版工具节点：带逐工具错误处理。

        改进点：
            - 每个工具调用独立 try/except，一个失败不影响其他
            - 失败时返回描述性错误消息（而非 traceback）
            - 详细的执行日志
        """
        messages = state["messages"]
        last_message = messages[-1]
        tool_calls = last_message.tool_calls

        results: list[ToolMessage] = []
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            # ── 执行前日志 ──
            safe_print(f"  [调用工具] {tool_name}")
            safe_print(f"  [工具参数] {tool_args}")

            # ── 查找工具 ──
            tool = tools_by_name.get(tool_name)
            if not tool:
                output = f"错误：未知工具 '{tool_name}'。可用工具：{list(tools_by_name.keys())}"
                safe_print(f"  [失败] {output}")
            else:
                try:
                    output = tool.invoke(tool_args)
                    # 截断长输出用于日志显示
                    preview = str(output)[:200]
                    safe_print(f"  [结果] {preview}{'...' if len(str(output)) > 200 else ''}")
                except Exception as e:
                    output = f"工具 '{tool_name}' 执行失败：{type(e).__name__}: {e}"
                    safe_print(f"  [失败] {output}")

            results.append(
                ToolMessage(
                    content=str(output),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )

        return {"messages": results}

    def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        """增强版条件路由：加入轮数保护。

        改进点：
            - 统计 AI 消息数量作为循环轮数
            - 超过 MAX_AI_TURNS 时强制终止（不管 LLM 还想不想继续）
            - 防止 Agent 在"调工具 → 不满意 → 再调 → 还不满意 → ..."中无限循环

        加分点：如果你能解释"为什么要防止无限循环"和"怎么选择阈值"，
        这体现了你不仅会写代码，还有系统可靠性的意识。
        """
        messages = state["messages"]
        last_message = messages[-1]

        # ── 循环保护：统计 AI 消息数 ──
        # 每轮 ReAct = AIMessage(含 tool_calls) → ToolMessage → AIMessage
        # 所以 AIMessage 的数量 ≈ 思考轮数
        MAX_AI_TURNS = 5
        ai_count = sum(1 for m in messages if isinstance(m, AIMessage))

        if ai_count > MAX_AI_TURNS:
            safe_print(f"  [安全保护] Agent 已思考 {ai_count} 轮（超过 {MAX_AI_TURNS} 轮上限），强制终止")
            return "__end__"

        # ── 正常路由判断 ──
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "__end__"

    # ── 3. 构建图（与 Step 2 相同的结构，但节点是增强版）───
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "__end__": END,
    })
    graph.add_edge("tools", "agent")
    compiled_agent = graph.compile()
    print_info("优化版 Agent 已就绪（错误处理 + 循环保护）")
    safe_print()

    # ── 4. 交互循环 ────────────────────────────────────────
    run_interactive_loop(
        agent=compiled_agent,
        step_name="Step 3",
        show_full_trace=True,
        recursion_limit=15,  # 放宽一点，配合 ai_count 保护
    )


# ============================================================
# 共享工具函数
# ============================================================

# safe_print, print_separator, print_info 已提取到 agent_forge.utils
# phase1_demo 和 agent_forge 核心库共享这些工具函数


def run_interactive_loop(
    agent,
    step_name: str,
    show_full_trace: bool = True,
    recursion_limit: int = 10,
) -> None:
    """运行 Agent 交互循环。

    这是一个通用的交互循环，被 Step 1/2/3 共享。
    职责：
        - 接收用户输入
        - 调用 Agent
        - 格式化显示 Agent 的思考和工具调用过程

    Args:
        agent: 编译好的 LangGraph agent（Runnable）
        step_name: 当前步骤名称（用于日志）
        show_full_trace: 是否显示完整的消息流（ToolMessage 等）
        recursion_limit: LangGraph 的递归深度上限
    """
    safe_print("输入你的任务（输入 /quit 退出，直接回车跳过）：")
    safe_print("试试这些任务：")
    safe_print('  - "读一下 README.md 的内容"')
    safe_print('  - "看看当前目录下有哪些文件"')
    safe_print('  - "创建一个 hello.py，打印 Hello World"')
    safe_print()

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            safe_print("\n👋 再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "/q"):
            safe_print("👋 再见！")
            break

        # ── 执行 Agent ────────────────────────────────────
        safe_print(f"\n{'─'*40}")
        safe_print(f"  [{step_name}] Agent 思考中...")
        safe_print(f"{'─'*40}")

        try:
            result = agent.invoke(
                {"messages": [HumanMessage(content=user_input)]},
                config={"recursion_limit": recursion_limit},
            )

            # ── 格式化显示结果 ────────────────────────────
            if show_full_trace:
                # 显示完整消息流
                for msg in result["messages"]:
                    if isinstance(msg, HumanMessage):
                        safe_print(f"  [你] {msg.content}")
                    elif isinstance(msg, AIMessage) and msg.content:
                        # LLM 给用户看的文本回复
                        safe_print(f"\n  [Agent] {msg.content}\n")
                    elif isinstance(msg, ToolMessage):
                        preview = msg.content[:300]
                        if len(msg.content) > 300:
                            preview += "..."
                        safe_print(f"  [工具结果: {msg.name}] {preview}")
                    # 注意：AIMessage 只有 tool_calls 没有 content 的情况，
                    # 上面的 tool_node 执行日志已经展示了，这里不重复打印
            else:
                # 只看最终回复
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        safe_print(f"\n  [Agent] {msg.content}\n")
                        break

        except Exception as e:
            safe_print(f"  [系统错误] {type(e).__name__}: {e}")
            safe_print("  提示：检查 .env 中的 DEEPSEEK_API_KEY 是否正确配置")

        safe_print(f"{'─'*40}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    """运行入口：通过 --step 参数选择要运行的步骤。

    使用：
        python demos/phase0_agent_demo.py --step 1   # 最小跑通
        python demos/phase0_agent_demo.py --step 2   # 理解原理
        python demos/phase0_agent_demo.py --step 3   # 优化版
        python demos/phase0_agent_demo.py            # 默认 Step 1
    """
    step = "1"
    if len(sys.argv) > 2 and sys.argv[1] == "--step":
        step = sys.argv[2]

    # 步骤到函数的映射
    steps = {"1": run_step1, "2": run_step2, "3": run_step3}

    if step not in steps:
        safe_print(f"错误：未知步骤 '{step}'。可选：1, 2, 3")
        sys.exit(1)

    # Windows GBK 终端兼容：emoji 可能无法显示，降级为纯文本
    try:
        safe_print(f"\n🚀 启动阶段 0 Agent Demo — Step {step}\n")
    except UnicodeEncodeError:
        safe_print(f"\n[AgentForge] Starting Phase 0 Agent Demo — Step {step}\n")

    steps[step]()
