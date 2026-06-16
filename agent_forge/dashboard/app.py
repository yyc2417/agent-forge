"""AgentForge Dashboard —— Streamlit 可视化应用

启动方式：
    streamlit run agent_forge/dashboard/app.py

技术方案：
    - Streamlit 直连 MessageBus（不走 FastAPI/WebSocket 中间层）
    - Agent 在后台 threading.Thread 中运行，避免 UI 冻结
    - st.session_state 持有 BusCollector、Thread 等跨 rerun 状态
    - 任务运行中每 2 秒 st.rerun() 自动刷新

页面结构（4 个 Tab）：
    Tab 1: 任务总览 — 任务输入 + 执行 + 结果展示
    Tab 2: 消息流时间线 — 实时消息列表 + 过滤
    Tab 3: Agent 状态面板 — 各 Agent 当前状态卡片
    Tab 4: 成本分析 — Token 消耗统计

注意事项：
    - 所有跨 rerun 的状态必须通过 st.session_state 管理
    - 后台线程只写 st.session_state.task_result 和 st.session_state.task_error
    - BusCollector 用自己的 threading.Lock 保护数据
    - streamlit>=1.30 才有 st.rerun()（旧版是 st.experimental_rerun()）
"""

import threading
import time
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from agent_forge.agents import CoderAgent, Orchestrator, ReviewerAgent
from agent_forge.bus import LoggingInterceptor, MessageBus
from agent_forge.cost import CostTracker
from agent_forge.dashboard.collector import (
    STATUS_CALLING_TOOL,
    STATUS_COMPLETED,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_THINKING,
    BusCollector,
)

# 加载 .env（DEEPSEEK_API_KEY 等）
load_dotenv()

# ─── 页面配置 ──────────────────────────────────────────────

st.set_page_config(
    page_title="AgentForge Dashboard",
    page_icon="🔨",
    layout="wide",
)

# ─── session_state 初始化 ──────────────────────────────────

if "collector" not in st.session_state:
    st.session_state.collector = BusCollector()
if "cost_tracker" not in st.session_state:
    st.session_state.cost_tracker = CostTracker()
if "thread" not in st.session_state:
    st.session_state.thread = None
if "task_result" not in st.session_state:
    st.session_state.task_result = None
if "task_error" not in st.session_state:
    st.session_state.task_error = None
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True


# ─── 任务执行函数（在后台线程中运行）───────────────────────

def _run_task(task: str) -> None:
    """后台线程执行的任务函数。

    创建完整的 Agent 团队（Orchestrator + Coder + Reviewer），
    通过 BusCollector 采集事件，运行完毕后写入 session_state。
    """
    try:
        # 创建 Bus + Collector + CostTracker
        bus = MessageBus()
        bus.add_interceptor(LoggingInterceptor())

        collector: BusCollector = st.session_state.collector
        collector.attach(bus)
        collector.clear()

        cost_tracker: CostTracker = st.session_state.cost_tracker
        cost_tracker.clear()

        # 创建 Agent 团队
        coder = CoderAgent(bus=bus, cost_tracker=cost_tracker)
        reviewer = ReviewerAgent(bus=bus, cost_tracker=cost_tracker)
        orchestrator = Orchestrator(
            specialists={"coder": coder, "reviewer": reviewer},
            bus=bus,
            cost_tracker=cost_tracker,
        )

        # 运行编排
        result = orchestrator.run(task)
        st.session_state.task_result = result

    except Exception as e:
        st.session_state.task_error = f"{type(e).__name__}: {e}"
    finally:
        # 标记线程结束
        st.session_state.thread = None


# ─── 侧边栏 ────────────────────────────────────────────────

with st.sidebar:
    st.title("🔨 AgentForge")
    st.caption("多 Agent 协作框架 Dashboard")
    st.divider()

    # 运行状态
    is_running = (
        st.session_state.thread is not None
        and st.session_state.thread.is_alive()
    )
    if is_running:
        st.success("● 任务运行中", icon="🟢")
    else:
        st.info("○ 空闲", icon="⚪")

    st.divider()

    # Agent 状态列表
    st.subheader("Agent 列表")
    agent_states = st.session_state.collector.get_agent_states()
    if agent_states:
        for name, state in agent_states.items():
            status = state["status"]
            status_icons = {
                STATUS_IDLE: "🟢",
                STATUS_THINKING: "🔵",
                STATUS_CALLING_TOOL: "🟡",
                STATUS_RUNNING: "🟠",
                STATUS_COMPLETED: "✅",
            }
            icon = status_icons.get(status, "⚪")
            st.markdown(f"{icon} **{name}**: {status}")
    else:
        st.caption("暂无 Agent 活动")

    st.divider()

    # 控制按钮
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ 清空数据"):
            st.session_state.collector.clear()
            st.session_state.cost_tracker.clear()
            st.session_state.task_result = None
            st.session_state.task_error = None
            st.rerun()
    with col2:
        if st.button(
            "⏸️ 暂停刷新" if st.session_state.auto_refresh else "▶️ 恢复刷新"
        ):
            st.session_state.auto_refresh = not st.session_state.auto_refresh
            st.rerun()


# ─── 主区域：4 个 Tab ──────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 任务总览",
    "📜 消息流时间线",
    "🤖 Agent 状态",
    "💰 成本分析",
])

# ── Tab 1: 任务总览 ────────────────────────────────────────

with tab1:
    st.header("提交任务")

    task_input = st.text_area(
        "输入任务描述",
        placeholder="例如：帮我写一个快速排序函数，包含单元测试",
        height=100,
    )

    if st.button("🚀 执行任务", type="primary", disabled=is_running):
        if task_input.strip():
            st.session_state.task_result = None
            st.session_state.task_error = None
            thread = threading.Thread(
                target=_run_task, args=(task_input.strip(),), daemon=True
            )
            st.session_state.thread = thread
            thread.start()
            st.rerun()
        else:
            st.warning("请输入任务描述")

    # 任务状态
    st.divider()
    if is_running:
        with st.spinner("Agent 正在处理任务..."):
            stats = st.session_state.collector.get_stats()
            st.metric("已采集消息数", stats["total_messages"])
            st.metric("已采集事件数", stats["total_events"])

    if st.session_state.task_error:
        st.error(f"任务执行失败: {st.session_state.task_error}")

    if st.session_state.task_result:
        st.success("任务完成!")
        with st.expander("📄 查看最终结果", expanded=True):
            st.markdown(st.session_state.task_result)

        # 完成后显示统计
        stats = st.session_state.collector.get_stats()
        cols = st.columns(4)
        cols[0].metric("总消息数", stats["total_messages"])
        cols[1].metric("事件数", stats["total_events"])
        cols[2].metric("工具调用", stats["tool_calls"])
        cols[3].metric("耗时", f"{stats['duration_seconds']}s")


# ── Tab 2: 消息流时间线 ────────────────────────────────────

with tab2:
    st.header("消息流时间线")

    # 过滤器
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        role_filter = st.selectbox(
            "按角色过滤",
            ["全部"] + sorted(agent_states.keys()) if agent_states else ["全部"],
        )
    with filter_col2:
        intent_filter = st.selectbox(
            "按意图过滤",
            ["全部", "event", "request", "response", "broadcast"],
        )

    # 获取并过滤消息
    messages = st.session_state.collector.get_messages()

    if messages:
        for msg in messages:
            # 应用过滤
            if role_filter != "全部" and msg.get("role") != role_filter:
                continue
            if intent_filter != "全部" and msg.get("intent") != intent_filter:
                continue

            # 格式化时间
            ts = msg.get("timestamp", 0)
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "??:??:??"

            intent = msg.get("intent", "?")
            role = msg.get("role", "?")
            payload = msg.get("payload", {})

            # 意图标签颜色
            intent_colors = {
                "event": "🔵",
                "request": "🟠",
                "response": "🟢",
                "broadcast": "🟣",
                "heartbeat": "⚪",
            }
            icon = intent_colors.get(intent, "⚪")

            # payload 预览
            payload_preview = str(payload)[:100]
            if len(str(payload)) > 100:
                payload_preview += "..."

            # 消息条目
            with st.expander(
                f"{icon} `{time_str}` **{intent.upper():>10}** | "
                f"`{role}` | {payload_preview}",
                expanded=False,
            ):
                st.json(msg)
    else:
        st.info("暂无消息。请先在「任务总览」中提交任务。")


# ── Tab 3: Agent 状态面板 ──────────────────────────────────

with tab3:
    st.header("Agent 状态面板")

    states = st.session_state.collector.get_agent_states()
    if states:
        cols = st.columns(min(len(states), 4))
        for i, (name, state) in enumerate(states.items()):
            with cols[i % len(cols)]:
                status = state["status"]
                status_colors = {
                    STATUS_IDLE: "normal",
                    STATUS_THINKING: "normal",
                    STATUS_CALLING_TOOL: "normal",
                    STATUS_RUNNING: "normal",
                    STATUS_COMPLETED: "complete",
                }
                st.metric(
                    label=f"🤖 {name}",
                    value=status,
                    delta=f"消息数: {state['message_count']}",
                )
                if state["current_tool"]:
                    st.caption(f"🔧 工具: {state['current_tool']}")
                if state["last_event_type"]:
                    st.caption(f"最后事件: {state['last_event_type']}")
                if state["last_active"]:
                    last_active_str = datetime.fromtimestamp(
                        state["last_active"]
                    ).strftime("%H:%M:%S")
                    st.caption(f"最后活动: {last_active_str}")
    else:
        st.info("暂无 Agent 活动。请先在「任务总览」中提交任务。")


# ── Tab 4: 成本分析 ────────────────────────────────────────

with tab4:
    st.header("Token 成本分析")

    cost_tracker: CostTracker = st.session_state.cost_tracker
    summary = cost_tracker.get_summary()

    if summary:
        # 总览指标
        total_tokens = cost_tracker.get_total_tokens()
        total_cost = cost_tracker.get_total_cost()
        total_calls = sum(s["calls"] for s in summary.values())

        cols = st.columns(4)
        cols[0].metric("总 Token", f"{total_tokens:,}")
        cols[1].metric("总成本", f"¥{total_cost:.4f}")
        cols[2].metric("LLM 调用次数", total_calls)
        cols[3].metric("Agent 数", len(summary))

        st.divider()

        # 按 Agent 维度的详细表格
        st.subheader("按 Agent 维度统计")
        table_data = []
        for name, s in sorted(summary.items()):
            table_data.append({
                "Agent": name,
                "调用次数": s["calls"],
                "输入 Token": f"{s['prompt_tokens']:,}",
                "输出 Token": f"{s['completion_tokens']:,}",
                "总 Token": f"{s['total_tokens']:,}",
                "成本": f"¥{s['cost']:.4f}",
            })
        st.table(table_data)
    else:
        st.info("暂无成本数据。请先在「任务总览」中提交任务。")


# ─── 自动刷新 ──────────────────────────────────────────────

if (
    st.session_state.auto_refresh
    and st.session_state.thread is not None
    and st.session_state.thread.is_alive()
):
    time.sleep(2)
    st.rerun()
