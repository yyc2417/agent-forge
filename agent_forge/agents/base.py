"""Agent 基类 —— 所有 Agent 的统一抽象

设计背景：
    阶段 0我们通过 demos/phase0_agent_demo.py 手动构建了三个版本的 Agent：
    - Step 1: 用 create_react_agent 一行创建（黑盒）
    - Step 2: 手动构建 StateGraph（揭开黑盒）
    - Step 3: 加入错误处理和循环保护（增强版）

    这三个版本有大量重复代码：AgentState 定义、agent_node、tool_node、
    should_continue、StateGraph 构建……每次创建新 Agent 都要复制粘贴一遍。

    本模块将这些重复模式提取为 BaseAgent 类，使得：
    - 创建新 Agent 只需指定 name、role、tools
    - 核心循环（ReAct）对所有 Agent 是相同的
    - 定制行为只需覆盖少量方法（模板方法模式）

与 CrewAI 的对比：
    CrewAI 的 Agent 类封装了整个运行时（包括任务执行、协作编排），
    开发者很难控制内部的决策流程。

    我们的 BaseAgent 只封装 ReAct 循环本身——
    agent_node → should_continue → tool_node → 循环。
    多 Agent 的协作由 Message Bus + Orchestrator（阶段 2）负责，
    不在 Agent 基类中处理。这样 Agent 保持简单、可测试、可组合。

模板方法模式：
    BaseAgent 定义了 Agent 的骨架（__init__ → _build_graph → run），
    子类可以覆盖特定步骤来定制行为：
    - get_system_prompt(): 定制角色的 system prompt
    - _build_graph(): 添加额外的节点（如反思节点、审批节点）
    - agent_node() / tool_node(): 定制推理或工具执行逻辑

    这是经典的模板方法模式（Template Method Pattern）：
    父类定义算法骨架，子类填充具体步骤。

使用方式：
    # 最简用法
    agent = BaseAgent(name="coder", role="Python 工程师", tools=[read_file, write_file])
    result = agent.run("写一个排序函数")

    # 继承定制
    class ReviewerAgent(BaseAgent):
        def get_system_prompt(self) -> str:
            return "你是代码审查专家。请逐行审查代码，关注安全性和性能。"
"""

from typing import Annotated, Literal

# ─── LangChain 消息类型 ───────────────────────────────────
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

# ─── LangGraph 核心 ────────────────────────────────────────
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agent_forge.bus import Message, MessageBus, MessageIntent
from agent_forge.cost import CostTracker

# 阶段 3新增模块（延迟导入避免循环依赖）
from agent_forge.hooks import HookManager

# ─── AgentForge 模块 ──────────────────────────────────────
from agent_forge.llm import create_deepseek_llm
from agent_forge.memory.long_term import LongTermMemory, create_memory_tools
from agent_forge.memory.short_term import ShortTermMemory
from agent_forge.utils import safe_print

# ─── 状态定义 ──────────────────────────────────────────────

class AgentState(TypedDict):
    """Agent 的运行状态 —— LangGraph StateGraph 的状态类型。

    从 phase0_demo 提取，保持一致的设计：
    - messages: 对话消息列表，使用 add_messages reducer 追加合并

    为什么只有 messages 一个字段？
    - LangGraph 的 Agent 循环本质上是"消息的累积"
    - Agent 的所有决策信息（用户输入、工具结果、LLM 推理）都在 messages 中
    - 后续扩展（如 Shared Memory）可以在此 TypedDict 中添加字段

    后续扩展预留（阶段 3 Shared Memory）：
    # shared_context: dict    # Agent 间共享的上下文
    # task_metadata: dict     # 当前任务的元数据
    """
    messages: Annotated[list, add_messages]


# ─── 默认 System Prompt 模板 ──────────────────────────────

_DEFAULT_SYSTEM_PROMPT = """\
你是 AgentForge 框架中的 AI Agent。

你的身份信息：
- 名称：{name}
- 角色：{role}
- 可用工具：{tool_names}

工作原则：
1. 仔细分析任务需求，制定执行计划
2. 合理使用可用工具完成任务
3. 遇到问题时尝试调整策略，而非直接放弃
4. 最终给出清晰、完整的回复
"""


# ─── Agent 基类 ────────────────────────────────────────────

class BaseAgent:
    """Agent 基类 —— 封装 ReAct 循环的通用抽象。

    从 phase0_demo Step 3 提取的可复用模式：
    1. StateGraph 构建（agent_node + tool_node + should_continue）
    2. LLM 绑定工具（bind_tools）
    3. 错误处理（LLM 调用失败 / 工具执行失败）
    4. 循环保护（ai_count 计数器 + recursion_limit）

    新增能力（阶段 1）：
    1. 角色定义：name + role + system_prompt
    2. Message Bus 集成：Agent 的关键行为自动发布事件
    3. 事件发布：thinking / tool_call / completed 三类事件

    Attributes:
        name: Agent 的唯一标识（用于 Message Bus 路由）。
        role: 角色描述（用于生成 system prompt）。
    """

    def __init__(
        self,
        name: str,
        role: str = "",
        tools: list | None = None,
        llm: ChatOpenAI | None = None,
        bus: MessageBus | None = None,
        max_turns: int = 5,
        temperature: float = 0.0,
        # ── 阶段 3新增参数 ──
        memory: ShortTermMemory | None = None,
        long_term_memory: LongTermMemory | None = None,
        enable_memory_tools: bool = False,
        hooks: HookManager | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        """初始化 Agent。

        Args:
            name: Agent 唯一标识，如 "coder"、"reviewer"。
            role: 角色描述，如 "资深 Python 工程师"。
            tools: 可用工具列表（LangChain @tool 函数）。
                   None 或空列表表示不使用工具（纯对话模式）。
            llm: LLM 实例。默认自动创建 DeepSeek LLM。
            bus: 消息总线实例。None 表示不参与多 Agent 通信。
            max_turns: 最大思考轮数（循环保护阈值）。
            temperature: LLM 采样温度。Agent 场景建议 0.0。
            memory: 短期记忆实例。提供多轮对话上下文保持能力。
            long_term_memory: 长期记忆实例。提供跨会话知识存储。
            enable_memory_tools: 是否自动注入记忆工具（store/recall/list）。
                                需要 long_term_memory 不为 None。
            hooks: 生命周期 Hooks 管理器。
            cost_tracker: Token 成本追踪器。
        """
        self.name = name
        self.role = role
        self._tools = tools or []
        self._max_turns = max_turns
        self._bus = bus
        self._memory = memory
        self._hooks = hooks or HookManager()
        self._cost_tracker = cost_tracker

        # ── 记忆工具注入 ──
        if enable_memory_tools and long_term_memory:
            mem_tools = create_memory_tools(long_term_memory)
            self._tools = self._tools + mem_tools

        # ── 创建/接收 LLM ──
        if llm is not None:
            self._llm = llm
        else:
            self._llm = create_deepseek_llm(temperature=temperature)

        # ── 绑定工具（如果有）──
        # bind_tools() 将工具的 JSON Schema 注入 LLM 请求，
        # 让 DeepSeek 知道有哪些工具可用、每个工具需要什么参数。
        # 如果 tools 为空，不调用 bind_tools()，LLM 只做对话。
        if self._tools:
            self._llm_with_tools = self._llm.bind_tools(self._tools)
            self._tools_by_name = {t.name: t for t in self._tools}
        else:
            self._llm_with_tools = self._llm
            self._tools_by_name = {}

        # ── 构建并编译 StateGraph ──
        self._compiled = self._build_graph()

        # ── 注册到 Message Bus（如果有）──
        if self._bus:
            self._register_bus_handlers()

    # ── 公开方法 ──────────────────────────────────────────

    def run(self, user_input: str, config: dict | None = None) -> str:
        """运行 Agent —— 接收用户输入，返回最终文本回复。

        这是 Agent 的主入口，内部完成：
        1. 构建初始消息列表（SystemMessage + HumanMessage）
        2. 调用 compiled_graph.invoke()
        3. 从结果中提取最终 AIMessage.content
        4. 发布完成事件到 Message Bus

        SystemMessage 在 run() 中一次性注入（而非在 agent_node 中）：
        - add_messages reducer 是追加模式，如果在 agent_node 中注入，
          每次循环都会多一条重复的 SystemMessage
        - 在入口处注入保证只有一条，且始终在消息列表的最前面

        Args:
            user_input: 用户输入的任务描述。
            config: LangGraph 配置（如 {"recursion_limit": 15}）。

        Returns:
            Agent 的最终文本回复。如果 LLM 未返回文本，返回空字符串。
        """
        # 构建初始消息
        messages: list = []
        system_prompt = self.get_system_prompt()
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        # ── 注入短期记忆（摘要 + 历史消息）──
        if self._memory:
            summary = self._memory.get_summary()
            if summary:
                messages.append(SystemMessage(
                    content=f"[历史对话摘要]\n{summary}"
                ))
            messages.extend(self._memory.get_messages())

        messages.append(HumanMessage(content=user_input))

        # 发布"开始处理"事件
        self._publish_event(MessageIntent.EVENT, {
            "event_type": "agent.started",
            "user_input": user_input,
        })

        # 调用编译好的 StateGraph
        default_config = {"recursion_limit": self._max_turns * 3 + 5}
        if config:
            default_config.update(config)

        result = self._compiled.invoke(
            {"messages": messages},
            config=default_config,
        )

        # 提取最终回复
        final_text = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage) and msg.content:
                final_text = msg.content
                break

        # 发布"处理完成"事件
        self._publish_event(MessageIntent.EVENT, {
            "event_type": "agent.completed",
            "result": final_text[:200],
        })

        # ── 存入短期记忆 ──
        if self._memory:
            self._memory.add(HumanMessage(content=user_input))
            if final_text:
                self._memory.add(AIMessage(content=final_text))

        return final_text

    def invoke(self, messages: list) -> dict:
        """低级调用接口 —— 直接传入消息列表，返回完整状态。

        与 run() 的区别：
        - run() 是高级 API，处理输入输出格式，注入 SystemMessage
        - invoke() 是低级 API，暴露完整的 StateGraph 接口
        - Message Bus 的消息转发等场景使用 invoke()

        Args:
            messages: 消息列表（应包含完整的对话上下文）。

        Returns:
            StateGraph 的完整输出 dict，包含 "messages" 键。
        """
        config = {"recursion_limit": self._max_turns * 3 + 5}
        return self._compiled.invoke({"messages": messages}, config=config)

    # ── 公开属性 ─────────────────────────────────────────

    @property
    def memory(self) -> ShortTermMemory | None:
        """获取短期记忆实例（只读）。"""
        return self._memory

    # ── 可覆盖方法（子类定制点）────────────────────────────

    def get_system_prompt(self) -> str:
        """生成 system prompt。

        子类可以覆盖此方法以定制角色行为。
        默认实现基于 self.name 和 self.role 生成通用 prompt。

        为什么用方法而非属性？
        - 方法可以动态生成（如根据当前时间、任务类型调整 prompt）
        - 子类覆盖比 __init__ 传参更灵活

        Returns:
            system prompt 字符串。返回空字符串则不注入 SystemMessage。
        """
        if self._tools:
            tool_names = [t.name for t in self._tools]
        else:
            tool_names = ["无"]

        return _DEFAULT_SYSTEM_PROMPT.format(
            name=self.name,
            role=self.role or "通用助手",
            tool_names=", ".join(tool_names),
        )

    # ── StateGraph 节点定义 ────────────────────────────────

    def agent_node(self, state: AgentState) -> dict:
        """Agent 节点：调用 LLM 进行推理。

        从 phase0_demo Step 3 提取，增加：
        - Message Bus 事件发布
        - 生命周期 Hooks 触发（pre/post_llm_call）
        - Token 成本采集（从 response_metadata 提取）

        错误处理策略：
        - LLM 调用失败 → 返回错误 AIMessage（不抛异常）
        - 让 should_continue 判断是否需要终止
        """
        messages = state["messages"]

        self._publish_event(MessageIntent.EVENT, {
            "event_type": "agent.thinking",
        })

        # ── 触发 pre_llm_call hook ──
        self._hooks.trigger("pre_llm_call", agent=self.name, messages=messages)

        try:
            response = self._llm_with_tools.invoke(messages)
        except Exception as e:
            error_msg = f"[LLM 调用失败] {type(e).__name__}: {e}"
            safe_print(f"  [{self.name}] {error_msg}")
            return {"messages": [AIMessage(content=error_msg)]}

        # ── 触发 post_llm_call hook ──
        self._hooks.trigger("post_llm_call", agent=self.name, response=response)

        # ── Token 成本采集 ──
        if self._cost_tracker and hasattr(response, "response_metadata"):
            usage = response.response_metadata.get("token_usage", {})
            if usage:
                self._cost_tracker.record(
                    agent_name=self.name,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )

        # 如果有工具调用，发布事件
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                self._publish_event(MessageIntent.EVENT, {
                    "event_type": "agent.tool_request",
                    "tool_name": tc["name"],
                    "tool_args": tc["args"],
                })

        return {"messages": [response]}

    def tool_node(self, state: AgentState) -> dict:
        """工具节点：执行 LLM 请求的工具调用。

        从 phase0_demo Step 3 提取，增加 Message Bus 事件发布。

        每个工具调用独立 try/except：一个失败不影响其他工具。
        失败时返回描述性错误消息（而非 traceback），
        让 LLM 根据错误信息自行调整策略。
        """
        messages = state["messages"]
        last_message = messages[-1]
        tool_calls = last_message.tool_calls

        results: list[ToolMessage] = []
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            safe_print(f"  [{self.name}] 调用工具: {tool_name}")

            # ── 触发 pre_tool_use hook ──
            self._hooks.trigger(
                "pre_tool_use", agent=self.name,
                tool_name=tool_name, tool_args=tool_args,
            )

            tool = self._tools_by_name.get(tool_name)
            if not tool:
                output = f"错误：未知工具 '{tool_name}'。可用工具：{list(self._tools_by_name.keys())}"
                safe_print(f"  [{self.name}] 失败: {output}")
            else:
                try:
                    output = tool.invoke(tool_args)
                    preview = str(output)[:200]
                    safe_print(
                        f"  [{self.name}] 结果: {preview}{'...' if len(str(output)) > 200 else ''}")
                except Exception as e:
                    output = f"工具 '{tool_name}' 执行失败：{type(e).__name__}: {e}"
                    safe_print(f"  [{self.name}] 失败: {output}")

            # ── 触发 post_tool_use hook ──
            self._hooks.trigger(
                "post_tool_use", agent=self.name,
                tool_name=tool_name, output=str(output),
            )

            # 发布工具调用结果事件
            self._publish_event(MessageIntent.EVENT, {
                "event_type": "agent.tool_result",
                "tool_name": tool_name,
                "result_preview": str(output)[:100],
            })

            results.append(
                ToolMessage(
                    content=str(output),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )

        return {"messages": results}

    def should_continue(self, state: AgentState) -> Literal["tools", "__end__"]:
        """条件路由：判断继续调工具还是结束。

        从 phase0_demo Step 3 提取，逻辑一致：
        1. 循环保护：统计 AIMessage 数量，超过 max_turns 强制终止
        2. 正常路由：有 tool_calls → "tools"，否则 → "__end__"

        为什么用 AIMessage 数量而不是总消息数量？
        - 每轮 ReAct = 1 个 AIMessage + N 个 ToolMessage
        - AIMessage 数量 ≈ LLM 思考轮数
        - 总消息数量受工具调用数量影响，不稳定
        """
        messages = state["messages"]
        last_message = messages[-1]

        # ── 循环保护 ──
        ai_count = sum(1 for m in messages if isinstance(m, AIMessage))
        if ai_count > self._max_turns:
            safe_print(
                f"  [{self.name}] 已达 {ai_count} 轮思考上限"
                f"（max_turns={self._max_turns}），强制终止"
            )
            return "__end__"

        # ── 无工具时直接结束 ──
        if not self._tools:
            return "__end__"

        # ── 正常路由判断 ──
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "__end__"

    # ── 图构建 ─────────────────────────────────────────────

    def _build_graph(self):
        """构建并编译 StateGraph。

        图结构（与 phase0_demo 一致）：
            entry → agent → [should_continue] → tools → agent → ...
                                            → END

        为什么提取为独立方法？
        - 子类可以覆盖以添加额外节点（如反思节点、审批节点）
        - 便于测试（可以单独验证图结构）
        - 阶段 2 Orchestrator 需要更复杂的图（多 Agent 节点）

        Returns:
            编译好的 LangGraph Runnable。
        """
        graph = StateGraph(AgentState)

        # 注册节点
        graph.add_node("agent", self.agent_node)

        if self._tools:
            graph.add_node("tools", self.tool_node)
            graph.add_edge("tools", "agent")

        # 入口
        graph.set_entry_point("agent")

        # 条件边
        if self._tools:
            graph.add_conditional_edges(
                "agent",
                self.should_continue,
                {"tools": "tools", "__end__": END},
            )
        else:
            # 无工具时，agent 执行完直接结束
            graph.add_conditional_edges(
                "agent",
                lambda state: "__end__",
                {"__end__": END},
            )

        return graph.compile()

    # ── Message Bus 集成 ───────────────────────────────────

    def _publish_event(self, intent: MessageIntent, payload: dict) -> None:
        """发布事件到 Message Bus（如果已绑定）。

        封装了"bus 为 None 时静默跳过"的逻辑，
        避免每个发布点都做 None 检查。

        Args:
            intent: 消息意图。
            payload: 消息内容。
        """
        if self._bus:
            self._bus.publish(Message(
                role=self.name,
                intent=intent,
                payload=payload,
            ))

    def _register_bus_handlers(self) -> None:
        """注册 Message Bus 的事件处理器。

        默认行为：订阅发给自己的 REQUEST 消息。
        子类可以覆盖以添加更多订阅。

        注意：handler 中不应调用 self.run()（会导致递归），
        而是将收到的消息记录下来，由上层编排逻辑处理。
        """
        # 预留：子类可以覆盖此方法添加自定义订阅
        pass

    # ── 可读表示 ──────────────────────────────────────────

    def __repr__(self) -> str:
        tool_names = [t.name for t in self._tools]
        bus_status = "connected" if self._bus else "standalone"
        return (
            f"BaseAgent(name={self.name!r}, role={self.role!r}, "
            f"tools={tool_names}, bus={bus_status})"
        )
