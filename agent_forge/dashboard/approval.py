"""Dashboard 人工审批门（HITL）—— 后台线程与 UI 之间的审批信箱。

解决的问题：
    Agent 在后台线程执行工具（如 run_shell），Streamlit 主脚本每 2 秒
    rerun 一次。危险工具执行前需要"人来批准"，但 UI 不能阻塞在
    worker 线程里、worker 也不能直接碰 st.session_state。

机制（生产者-消费者 + 事件）：
    - worker 线程调用 request()：请求入队，阻塞在 threading.Event 上
      等待用户决定（带超时）
    - 主脚本每轮 rerun 调用 pending() 拿到未决请求快照，渲染成
      "批准 / 拒绝"卡片
    - 用户点击按钮 → resolve(request_id, approved) 写回结果并唤醒
      worker；随后 st.rerun() 刷新界面

安全默认（fail-safe）：
    - 超时（默认 300 秒）无人决定 → 自动拒绝
    - resolve 一个不存在/已决定的请求 → 静默忽略，不影响 worker

与 ToolRegistry 审批门的关系：
    registry.bind_tools(EXECUTE, approval_callback=broker.request)
    —— broker.request 的签名 (tool_name, tool_args) -> bool 与审批
    回调契约一致，作为回调直接传入即可。
"""

import threading
import time
import uuid
from copy import copy
from dataclasses import dataclass


@dataclass
class ApprovalRequest:
    """一条待审批（或已审批）的工具调用请求。"""

    request_id: str
    tool_name: str
    tool_args: dict
    created_at: float
    # None = 未决定；True/False = 批准/拒绝
    approved: bool | None = None
    # 是否因超时被自动拒绝（UI 可据此提示"超时自动拒绝"）
    timed_out: bool = False


class ApprovalBroker:
    """人工审批信箱 —— worker 提交请求，UI 决定，worker 恢复执行。"""

    def __init__(self, timeout: float = 300.0) -> None:
        """
        Args:
            timeout: 默认审批等待时长（秒）。超时无人决定 → 自动拒绝。
        """
        self._timeout = timeout
        self._lock = threading.Lock()
        self._requests: dict[str, ApprovalRequest] = {}
        self._events: dict[str, threading.Event] = {}

    # ── worker 线程侧 ─────────────────────────────────────

    def request(
        self, tool_name: str, tool_args: dict, timeout: float | None = None
    ) -> bool:
        """提交一次工具调用审批并阻塞等待决定。

        由 ToolRegistry 审批门在 worker 线程中调用。

        Args:
            tool_name: 请求调用的工具名。
            tool_args: 工具参数。
            timeout: 本次请求的等待时长；None 用构造时的默认值。

        Returns:
            True = 用户批准；False = 用户拒绝或超时自动拒绝。
        """
        request_id = uuid.uuid4().hex[:12]
        event = threading.Event()
        with self._lock:
            self._requests[request_id] = ApprovalRequest(
                request_id=request_id,
                tool_name=tool_name,
                tool_args=dict(tool_args),
                created_at=time.time(),
            )
            self._events[request_id] = event

        event.wait(self._timeout if timeout is None else timeout)

        with self._lock:
            self._events.pop(request_id, None)
            req = self._requests.get(request_id)

        if req is not None and req.approved is not None:
            return req.approved

        # 超时未决定：标记为自动拒绝（fail-safe）
        with self._lock:
            req = self._requests.get(request_id)
            if req is not None and req.approved is None:
                req.approved = False
                req.timed_out = True
        return False

    # ── 主脚本（UI）侧 ────────────────────────────────────

    def pending(self) -> list[ApprovalRequest]:
        """获取所有未决定请求的快照（供 UI 渲染审批卡片）。"""
        with self._lock:
            return [
                copy(r) for r in self._requests.values() if r.approved is None
            ]

    def resolved_history(self) -> list[ApprovalRequest]:
        """获取所有已决定请求的快照（UI 可展示审批记录）。"""
        with self._lock:
            return [
                copy(r) for r in self._requests.values() if r.approved is not None
            ]

    def resolve(self, request_id: str, approved: bool) -> None:
        """写回用户的审批决定并唤醒等待中的 worker。

        对不存在或已决定的请求静默忽略（不抛异常——UI 与 worker
        天然异构，晚到的点击不应炸掉界面）。
        """
        with self._lock:
            req = self._requests.get(request_id)
            event = self._events.get(request_id)
            if req is None or event is None or req.approved is not None:
                return
            req.approved = approved
            event.set()
