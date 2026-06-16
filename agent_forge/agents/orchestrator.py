"""Orchestrator —— 多 Agent 任务编排器

核心职责：
    接收用户任务 → 用 LLM 拆解为子任务 → 调度 Specialist Agent 执行 → 汇总产出

设计思路：
    Orchestrator 继承 BaseAgent，覆盖 _build_graph() 构建编排工作流图。
    与普通 Agent（ReAct 循环）不同，Orchestrator 的 StateGraph 有四个节点：

        decompose → execute → [all_done?] → review → [passed?]
                      ↑         │ yes        │         │ yes
                      └─────────┘            │         ↓
                      (retry, not passed) ←──┘     aggregate → END

    这体现了模板方法模式的价值：同一个 BaseAgent 基类，
    - 普通 Agent 构建 ReAct 循环图（agent_node → tool_node → 循环）
    - Orchestrator 构建编排工作流图（decompose → execute → review → aggregate）

与业界的对比：
    - CrewAI：Crew 对象硬编码任务顺序，不支持动态拆解和条件回退
    - AutoGen：GroupChatManager 按轮询或选择器调度，不支持 StateGraph 建模
    - LangGraph Agent Supervisor：最接近我们的设计，但它是预构建的，
      我们是从零构建，更透明、更可控

交互模式：
    Orchestrator 通过直接调用 specialist.run() + Bus 事件发布来调度 Agent。
    - 直接调用：控制流清晰，适合当前同步模型
    - Bus 事件发布：提供可观测性（Dashboard 可以看到任务分发过程）
    - 不用纯 Bus 通信的原因：同步 Bus 下 REQUEST-RESPONSE 配对复杂度高，
      且 Bus handler 中不应调用 agent.run()（会导致递归）
"""

import json
import re
from typing import Annotated, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agent_forge.agents.base import BaseAgent
from agent_forge.bus import Message, MessageBus, MessageIntent
from agent_forge.utils import safe_print

# ─── 状态定义 ──────────────────────────────────────────────

class OrchestratorState(TypedDict):
    """编排器的运行状态 —— 比 AgentState 丰富得多。

    AgentState 只有 messages 一个字段（ReAct 循环只需要对话历史）。
    OrchestratorState 需要追踪任务拆解、执行进度、审查结果等编排元数据。

    字段说明：
    - messages: 保留 add_messages reducer，用于 Orchestrator 自身的 LLM 推理
    - task: 用户原始任务（不可变）
    - plan: LLM 拆解出的子任务列表（每个子任务包含 agent_type 和 description）
    - current_step: 当前执行到第几个子任务（execute 节点递增）
    - results: {agent_name: result} 映射，累积各 Specialist 的产出
    - review_passed: 审查是否通过（review 节点设置）
    - final_output: 汇总的最终输出（aggregate 节点设置）
    - retry_count: 回退重试计数（防无限回退）

    为什么 plan 用 list 而不是更复杂的 DAG？
    - 阶段 2先实现顺序执行，DAG（并行/分支）留给后续优化
    - 大多数编码任务是顺序的（分析 → 编码 → 审查），并行需求不高
    """
    messages: Annotated[list, add_messages]
    task: str
    plan: list
    current_step: int
    results: dict
    review_passed: bool
    final_output: str
    retry_count: int


# ─── Orchestrator ─────────────────────────────────────────

class Orchestrator(BaseAgent):
    """多 Agent 编排器 —— 继承 BaseAgent，覆盖 _build_graph()。

    Orchestrator 自身不使用工具（tools=[]），它的"工具"就是 Specialist Agents。
    LLM 用于任务拆解（decompose 节点），而非工具调用。

    使用方式：
        coder = CoderAgent(bus=bus)
        reviewer = ReviewerAgent(bus=bus)
        orchestrator = Orchestrator(
            specialists={"coder": coder, "reviewer": reviewer},
            bus=bus,
        )
        result = orchestrator.run("帮我写一个排序函数")

    Attributes:
        _specialists: 可用的 Specialist Agent 字典
        _max_retries: 审查不通过时的最大回退重试次数
    """

    def __init__(
        self,
        specialists: dict[str, BaseAgent],
        bus: MessageBus | None = None,
        llm=None,
        max_retries: int = 2,
        # ── 透传 BaseAgent 参数 ──
        memory=None,
        hooks=None,
        cost_tracker=None,
    ):
        self._specialists = specialists
        self._max_retries = max_retries

        super().__init__(
            name="orchestrator",
            role="任务编排者",
            tools=[],  # Orchestrator 自身不使用工具
            bus=bus,
            llm=llm,
            memory=memory,
            hooks=hooks,
            cost_tracker=cost_tracker,
        )

    def get_system_prompt(self) -> str:
        """生成拆解任务的 system prompt。

        prompt 中列出了可用的 Specialist Agent 信息，
        让 LLM 知道有哪些角色可以分配任务。
        """
        specialist_info = "\n".join(
            f"  - {name}: {s.role}" for name, s in self._specialists.items()
        )
        return f"""\
你是 AgentForge 的任务编排者。

你的职责：
1. 分析用户任务，将其拆解为子任务
2. 为每个子任务分配给合适的 Specialist Agent
3. 汇总所有 Specialist 的产出，生成最终报告

可用的 Specialist Agent：
{specialist_info}

拆解规则：
- 每个子任务应清晰、独立、可执行
- 通常一个编码任务需要：coder 编码 → reviewer 审查
- 输出严格的 JSON 格式（不要添加 markdown 代码块标记）

输出格式（严格遵守，直接输出 JSON）：
{{
  "analysis": "任务分析...",
  "subtasks": [
    {{"id": 1, "agent": "coder", "description": "具体任务描述"}},
    {{"id": 2, "agent": "reviewer", "description": "具体任务描述"}}
  ]
}}"""

    # ─── StateGraph 节点 ──────────────────────────────────

    def _decompose_node(self, state: OrchestratorState) -> dict:
        """任务拆解节点：用 LLM 将用户任务拆解为子任务计划。

        三层防护确保拆解不会失败：
        1. 正则提取 JSON（LLM 输出可能包含多余文本）
        2. json.loads 解析（格式可能不对）
        3. fallback 到默认的单步 coder 计划

        Returns:
            包含 plan、current_step、retry_count 的状态更新。
        """
        task = state["task"]
        safe_print(f"  [Orchestrator] 正在拆解任务: {task[:80]}...")
        self._publish_event(MessageIntent.EVENT, {
            "event_type": "orchestrator.decomposing",
            "task": task[:100],
        })

        # 调用 LLM 拆解
        messages = [
            SystemMessage(content=self.get_system_prompt()),
            HumanMessage(content=f"请拆解以下任务：\n{task}"),
        ]

        try:
            response = self._llm.invoke(messages)
            plan = self._parse_plan(response.content)
        except Exception as e:
            safe_print(f"  [Orchestrator] LLM 拆解异常: {e}")
            plan = self._fallback_plan(task)

        safe_print(f"  [Orchestrator] 拆解为 {len(plan)} 个子任务:")
        for sub in plan:
            safe_print(
                f"    - [{sub['agent_type']}] {sub['description'][:60]}")

        return {"plan": plan, "current_step": 0, "retry_count": 0}

    def _execute_node(self, state: OrchestratorState) -> dict:
        """执行节点：取出当前子任务，路由到对应 Specialist 执行。

        每次调用只执行一个子任务（由 current_step 指定），
        然后通过条件边 should_continue_execute 判断是否继续。

        关键：results 字段是覆盖式更新（非追加），
        所以需要先复制旧 results 再合并新值。

        Returns:
            包含更新后的 plan、current_step、results 的状态更新。
        """
        plan = state["plan"]
        step = state["current_step"]
        results = dict(state.get("results", {}))  # 复制旧值

        if step >= len(plan):
            return {"current_step": step}

        subtask = plan[step]
        agent_type = subtask["agent_type"]
        agent = self._specialists.get(agent_type)

        safe_print(f"\n  [Orchestrator] 步骤 {step + 1}/{len(plan)}: "
                   f"分发给 {agent_type}")
        self._publish_event(MessageIntent.EVENT, {
            "event_type": "orchestrator.dispatching",
            "step": step + 1,
            "total": len(plan),
            "target_agent": agent_type,
        })

        if not agent:
            safe_print(f"  [Orchestrator] 警告: 未知 Agent 类型 '{agent_type}'，跳过")
            results[agent_type] = f"[错误] 未知 Agent 类型: {agent_type}"
            return {
                "current_step": step + 1,
                "results": results,
            }

        # 构建上下文（包含前序 Agent 的产出）
        context = self._build_context(subtask, results)
        result = self._dispatch_to_agent(agent, context)

        results[agent_type] = result

        # 更新 plan 中该子任务的状态
        updated_plan = list(plan)
        updated_plan[step] = {
            **subtask,
            "status": "done",
            "result": result[:200],
        }

        return {
            "plan": updated_plan,
            "current_step": step + 1,
            "results": results,
        }

    # ─── 审查节点的子方法（职责分离）──────────────────────

    def _should_skip_review(
        self, coder_output: str, reviewer: BaseAgent | None
    ) -> tuple[bool, str]:
        """检查是否应该跳过审查。

        两种情况跳过：
        1. Coder 没有产出（空字符串）—— 没有东西可审查
        2. 没有可用的 Reviewer Agent —— 没人来审查

        Args:
            coder_output: Coder Agent 的输出文本。
            reviewer: Reviewer Agent 实例，可能为 None。

        Returns:
            (是否跳过, 原因描述) 元组。
        """
        if not coder_output:
            return True, "无 Coder 产出，跳过审查"
        if not reviewer:
            return True, "无 Reviewer，跳过审查"
        return False, ""

    def _should_force_pass(self, retry_count: int) -> tuple[bool, str]:
        """检查是否应该强制通过（达到最大重试次数）。

        当审查反复不通过时，需要有终止条件防止无限循环。
        达到 max_retries 后强制通过，使用当前版本的代码。

        Args:
            retry_count: 当前已重试的次数。

        Returns:
            (是否强制通过, 原因描述) 元组。
        """
        if retry_count >= self._max_retries:
            return True, f"已达最大重试次数 ({self._max_retries})，强制通过"
        return False, ""

    def _call_reviewer(
        self, reviewer: BaseAgent, task: str, coder_output: str
    ) -> str:
        """构建审查 prompt 并调用 Reviewer Agent。

        将原始需求和 Coder 产出组合成审查 prompt，
        通过 _dispatch_to_agent 调用 Reviewer（同时发布 Bus 事件）。

        Args:
            reviewer: Reviewer Agent 实例。
            task: 用户原始任务描述。
            coder_output: Coder Agent 的代码产出。

        Returns:
            Reviewer 的审查结果文本（包含【通过】或【不通过】判定）。
        """
        return self._dispatch_to_agent(
            reviewer,
            f"请审查以下代码产出并给出判定（【通过】或【不通过】）：\n\n"
            f"原始需求：{task[:200]}\n\n"
            f"Coder 的产出：\n{coder_output[:2000]}",
        )

    def _parse_review_result(self, review_result: str) -> bool:
        """解析审查结果，判定是否通过。

        采用双条件判定，减少 LLM 输出的模糊性导致的误判：
        - 必须包含"通过"
        - 不能包含"不通过"（"不通过"是"通过"的子串，单条件会误判）

        Args:
            review_result: Reviewer Agent 的审查结果文本。

        Returns:
            True 表示审查通过，False 表示不通过。
        """
        return "通过" in review_result and "不通过" not in review_result

    def _reset_execution_state(
        self, state: OrchestratorState, results: dict
    ) -> dict:
        """审查不通过时重置执行状态，让 execute 节点重新运行。

        智能回退策略：
        - 找到最后一个 agent_type="coder" 的步骤，只从该步骤开始重跑
        - 保留 coder 之前的步骤结果（如 analyst 的分析不需要重做）
        - retry_count 递增，plan 中需要重跑的步骤重置为 pending

        Args:
            state: 当前 OrchestratorState。
            results: 已收集的 Agent 产出（包含最新的 review 结果）。

        Returns:
            完整的状态更新 dict，供 StateGraph 合并。
        """
        retry_count = state.get("retry_count", 0)
        plan = state.get("plan", [])

        # 找到最后一个 coder 步骤的索引
        last_coder_idx = -1
        for i, sub in enumerate(plan):
            if sub.get("agent_type") == "coder":
                last_coder_idx = i

        # 如果找到 coder 步骤，从该步骤开始重跑；否则从头开始
        restart_from = last_coder_idx if last_coder_idx >= 0 else 0

        # 只重置需要重跑的步骤
        reset_plan = []
        for i, sub in enumerate(plan):
            if i >= restart_from:
                reset_plan.append({**sub, "status": "pending", "result": ""})
            else:
                reset_plan.append(sub)  # 保留已完成的步骤

        return {
            "review_passed": False,
            "current_step": restart_from,
            "retry_count": retry_count + 1,
            "results": results,
            "plan": reset_plan,
        }

    # ─── StateGraph 节点：审查 ─────────────────────────────

    def _review_node(self, state: OrchestratorState) -> dict:
        """审查节点：编排 Reviewer 审查 Coder 产出的完整流程。

        本方法只做流程编排，具体逻辑委托给 5 个子方法：
        - _should_skip_review: 前置检查（无产出/无 Reviewer → 跳过）
        - _should_force_pass: 重试控制（达到上限 → 强制通过）
        - _call_reviewer: Agent 调用（构建 prompt + 调用 + Bus 事件）
        - _parse_review_result: 结果判定（双条件：通过/不通过）
        - _reset_execution_state: 状态重置（回退到 execute 重新运行）

        Returns:
            包含 review_passed 的状态更新 dict。
        """
        results = dict(state.get("results", {}))
        coder_output = results.get("coder", "")
        reviewer = self._specialists.get("reviewer")
        retry_count = state.get("retry_count", 0)

        # 前置检查
        should_skip, skip_reason = self._should_skip_review(coder_output, reviewer)
        if should_skip:
            safe_print(f"  [Orchestrator] {skip_reason}")
            return {"review_passed": True}

        # 重试检查
        should_force, force_reason = self._should_force_pass(retry_count)
        if should_force:
            safe_print(f"  [Orchestrator] {force_reason}")
            return {"review_passed": True}

        # 执行审查
        safe_print(f"\n  [Orchestrator] 审查阶段 (尝试 {retry_count + 1}):")
        self._publish_event(MessageIntent.EVENT, {
            "event_type": "orchestrator.reviewing",
            "retry_count": retry_count,
        })

        review_result = self._call_reviewer(reviewer, state["task"], coder_output)
        passed = self._parse_review_result(review_result)

        safe_print(f"  [Orchestrator] 审查结果: {'【通过】' if passed else '【不通过】'}")
        results["review"] = review_result

        if passed:
            return {"review_passed": True, "results": results}
        else:
            return self._reset_execution_state(state, results)

    def _aggregate_node(self, state: OrchestratorState) -> dict:
        """汇总节点：将所有 Specialist 的产出汇总为最终报告。

        Returns:
            包含 final_output 的状态更新。
        """
        results = state.get("results", {})
        task = state["task"]

        safe_print("\n  [Orchestrator] 汇总所有产出")
        self._publish_event(MessageIntent.EVENT, {
            "event_type": "orchestrator.aggregating",
        })

        sections = [f"# 任务完成报告\n\n原始任务: {task}\n"]
        for agent_name, result in results.items():
            if agent_name == "review":
                sections.append(f"## 审查意见\n\n{result}\n")
            else:
                sections.append(f"## {agent_name} 的产出\n\n{result}\n")

        final = "\n---\n".join(sections)

        self._publish_event(MessageIntent.EVENT, {
            "event_type": "orchestrator.completed",
            "result_preview": final[:200],
        })

        return {"final_output": final}

    # ─── 条件路由 ─────────────────────────────────────────

    def _should_continue_execute(
        self, state: OrchestratorState
    ) -> Literal["execute", "review"]:
        """判断是否还有未执行的子任务。"""
        plan = state.get("plan", [])
        step = state.get("current_step", 0)
        if step < len(plan):
            return "execute"
        return "review"

    def _should_retry(
        self, state: OrchestratorState
    ) -> Literal["execute", "aggregate"]:
        """审查结果路由：通过 → aggregate，不通过 → execute（回退）。"""
        if state.get("review_passed", False):
            return "aggregate"
        return "execute"

    # ─── 图构建（覆盖 BaseAgent）─────────────────────────

    def _build_graph(self):
        """构建编排工作流 StateGraph。

        图结构：
            decompose → execute → [all_done?] → review → [passed?]
                          ↑         │ yes        │         │ yes
                          └─────────┘            │         ↓
                          (retry, not passed) ←──┘     aggregate → END
        """
        graph = StateGraph(OrchestratorState)

        # 注册节点
        graph.add_node("decompose", self._decompose_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("review", self._review_node)
        graph.add_node("aggregate", self._aggregate_node)

        # 入口
        graph.set_entry_point("decompose")

        # decompose → execute（固定边）
        graph.add_edge("decompose", "execute")

        # execute 循环执行子任务，全部完成后进入 review
        graph.add_conditional_edges(
            "execute",
            self._should_continue_execute,
            {"execute": "execute", "review": "review"},
        )

        # review 通过后 aggregate，不通过回退到 execute
        graph.add_conditional_edges(
            "review",
            self._should_retry,
            {"execute": "execute", "aggregate": "aggregate"},
        )

        # aggregate → END
        graph.add_edge("aggregate", END)

        return graph.compile()

    # ─── 公开接口 ──────────────────────────────────────────

    def run(self, user_input: str, config: dict | None = None) -> str:
        """运行编排工作流。

        与 BaseAgent.run() 的区别：
        - 初始状态不是 messages，而是 OrchestratorState
        - recursion_limit 更高（50），因为嵌套调用 Specialist 需要更多递归
        - 返回 final_output 而非最后一条 AIMessage

        Args:
            user_input: 用户输入的任务描述。
            config: LangGraph 配置（可选）。

        Returns:
            汇总后的最终报告字符串。
        """
        default_config = {"recursion_limit": 50}
        if config:
            default_config.update(config)

        self._publish_event(MessageIntent.EVENT, {
            "event_type": "orchestrator.started",
            "task": user_input[:100],
        })

        initial_state: OrchestratorState = {
            "messages": [],
            "task": user_input,
            "plan": [],
            "current_step": 0,
            "results": {},
            "review_passed": False,
            "final_output": "",
            "retry_count": 0,
        }

        result = self._compiled.invoke(initial_state, config=default_config)
        return result.get("final_output", "")

    # ─── 内部工具方法 ──────────────────────────────────────

    def _parse_plan(self, llm_output: str) -> list[dict]:
        """解析 LLM 输出的 JSON 拆解计划。

        三层防护：
        1. 正则提取 {...} 块（LLM 可能在 JSON 前后添加解释文本）
        2. json.loads 解析（JSON 格式可能不对）
        3. 返回 fallback 计划（确保不会崩溃）

        Args:
            llm_output: LLM 的原始输出文本。

        Returns:
            SubTask 字典列表。
        """
        # 尝试从 LLM 输出中提取 JSON
        json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                subtasks = []
                for i, st in enumerate(data.get("subtasks", [])):
                    subtasks.append({
                        "id": st.get("id", i + 1),
                        "description": st.get("description", ""),
                        "agent_type": st.get("agent", "coder"),
                        "status": "pending",
                        "result": "",
                    })
                if subtasks:
                    return subtasks
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # 解析失败，使用兜底方案
        safe_print("  [Orchestrator] JSON 解析失败，使用默认计划")
        return self._fallback_plan(llm_output[:200])

    def _fallback_plan(self, task: str) -> list[dict]:
        """兜底计划：当 LLM 拆解失败时，使用 coder → reviewer 默认流程。

        这是"宁可降级运行，不可崩溃"的设计原则。
        大多数编程任务用 coder → reviewer 两步就够了。
        """
        return [
            {
                "id": 1,
                "description": task or "完成编码任务",
                "agent_type": "coder",
                "status": "pending",
                "result": "",
            },
            {
                "id": 2,
                "description": "审查代码质量",
                "agent_type": "reviewer",
                "status": "pending",
                "result": "",
            },
        ]

    def _build_context(self, subtask: dict, results: dict) -> str:
        """为子任务构建上下文提示（包含前序 Agent 的产出）。

        当执行 reviewer 任务时，需要把 coder 的产出作为上下文传入，
        否则 reviewer 不知道要审查什么。

        Args:
            subtask: 当前子任务字典。
            results: 已完成的 Agent 产出映射。

        Returns:
            包含任务描述和前序产出的上下文文本。
        """
        parts = [f"任务: {subtask['description']}"]
        for agent_name, result in results.items():
            if agent_name != subtask["agent_type"] and agent_name != "review":
                parts.append(f"\n{agent_name} 的前序产出:\n{result[:1500]}")
        return "\n".join(parts)

    def _dispatch_to_agent(self, agent: BaseAgent, task: str) -> str:
        """分发任务给 Specialist 并通过 Bus 发布事件。

        混合模式：直接调用 agent.run() + Bus 事件发布。
        - 直接调用保证控制流清晰
        - Bus 事件保证可观测性

        Args:
            agent: 目标 Specialist Agent。
            task: 任务描述文本。

        Returns:
            Specialist Agent 的执行结果。
        """
        request_msg = None
        if self._bus:
            request_msg = Message(
                role=self.name,
                intent=MessageIntent.REQUEST,
                payload={"target_agent": agent.name, "task": task[:200]},
            )
            self._bus.publish(request_msg)

        safe_print(f"  [Orchestrator -> {agent.name}] 分发任务")
        result = agent.run(task)

        if self._bus:
            response_msg = Message(
                role=agent.name,
                intent=MessageIntent.RESPONSE,
                payload={"result_preview": result[:200]},
                reply_to=request_msg.message_id if request_msg else None,
            )
            self._bus.publish(response_msg)

        return result
