"""ApprovalBroker（Dashboard 人工审批门）单元测试。

纯线程实现，不依赖 streamlit、不调用 LLM。
"""

import threading
import time

from agent_forge.dashboard.approval import ApprovalBroker


def _request_in_thread(broker: ApprovalBroker, results: list, tool_args: dict | None = None):
    """在后台线程中发起一次审批请求，结束后把结果 append 到 results。"""

    def _run():
        results.append(broker.request("run_shell", tool_args or {"command": "echo hi"}))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


class TestApprovalBroker:
    """批准 / 拒绝 / 超时三条路径。"""

    def test_approve_path(self):
        broker = ApprovalBroker(timeout=5)
        results: list[bool] = []
        worker = _request_in_thread(broker, results)

        # 等请求出现
        deadline = time.time() + 2
        while not broker.pending() and time.time() < deadline:
            time.sleep(0.01)
        pending = broker.pending()
        assert len(pending) == 1
        assert pending[0].tool_name == "run_shell"
        assert pending[0].tool_args == {"command": "echo hi"}

        broker.resolve(pending[0].request_id, True)
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert results == [True]
        assert broker.pending() == []
        # 决定保留在历史中
        history = broker.resolved_history()
        assert len(history) == 1 and history[0].approved is True

    def test_deny_path(self):
        broker = ApprovalBroker(timeout=5)
        results: list[bool] = []
        worker = _request_in_thread(broker, results)

        deadline = time.time() + 2
        while not broker.pending() and time.time() < deadline:
            time.sleep(0.01)
        broker.resolve(broker.pending()[0].request_id, False)
        worker.join(timeout=2)
        assert results == [False]

    def test_timeout_auto_denies(self):
        """修复默认 fail-safe：超时无人决定 → 自动拒绝。"""
        broker = ApprovalBroker(timeout=0.2)
        results: list[bool] = []
        worker = _request_in_thread(broker, results)

        worker.join(timeout=2)
        assert results == [False]
        # UI 侧能看到"超时自动拒绝"标记
        history = broker.resolved_history()
        assert len(history) == 1
        assert history[0].approved is False
        assert history[0].timed_out is True

    def test_late_resolve_is_ignored(self):
        """晚到的点击不炸 UI：超时拒绝后再 resolve 静默忽略。"""
        broker = ApprovalBroker(timeout=0.2)
        results: list[bool] = []
        worker = _request_in_thread(broker, results)
        worker.join(timeout=2)
        assert results == [False]

        req = broker.resolved_history()[0]
        broker.resolve(req.request_id, True)  # 不应抛异常，也不应改结果
        assert broker.resolved_history()[0].approved is False

    def test_multiple_sequential_requests(self):
        broker = ApprovalBroker(timeout=5)
        results: list[bool] = []
        workers = [
            _request_in_thread(broker, results, {"command": f"cmd{i}"})
            for i in range(3)
        ]

        deadline = time.time() + 2
        while len(broker.pending()) < 3 and time.time() < deadline:
            time.sleep(0.01)
        assert len(broker.pending()) == 3

        # 逐一批准
        for req in broker.pending():
            broker.resolve(req.request_id, True)
        for w in workers:
            w.join(timeout=2)
        assert results == [True, True, True]
        assert broker.pending() == []
