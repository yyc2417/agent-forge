"""CostTracker 单元测试。"""



class TestCostTracker:
    """CostTracker 核心功能测试。"""

    def test_record_and_summary(self, cost_tracker):
        cost_tracker.record("coder", prompt_tokens=100, completion_tokens=50)
        summary = cost_tracker.get_summary()
        assert "coder" in summary
        assert summary["coder"]["calls"] == 1
        assert summary["coder"]["prompt_tokens"] == 100
        assert summary["coder"]["completion_tokens"] == 50

    def test_multiple_records_same_agent(self, cost_tracker):
        cost_tracker.record("coder", prompt_tokens=100, completion_tokens=50)
        cost_tracker.record("coder", prompt_tokens=200, completion_tokens=80)
        summary = cost_tracker.get_summary()
        assert summary["coder"]["calls"] == 2
        assert summary["coder"]["prompt_tokens"] == 300
        assert summary["coder"]["completion_tokens"] == 130

    def test_multiple_agents(self, cost_tracker):
        cost_tracker.record("coder", prompt_tokens=100, completion_tokens=50)
        cost_tracker.record("reviewer", prompt_tokens=50, completion_tokens=30)
        summary = cost_tracker.get_summary()
        assert len(summary) == 2
        assert "coder" in summary
        assert "reviewer" in summary

    def test_get_total_tokens(self, cost_tracker):
        cost_tracker.record("a", prompt_tokens=100, completion_tokens=50)
        cost_tracker.record("b", prompt_tokens=200, completion_tokens=100)
        assert cost_tracker.get_total_tokens() == 450

    def test_get_total_cost(self, cost_tracker):
        cost_tracker.record("a", prompt_tokens=1000, completion_tokens=500)
        cost = cost_tracker.get_total_cost()
        assert cost > 0

    def test_zero_tokens_ignored(self, cost_tracker):
        cost_tracker.record("a", prompt_tokens=0, completion_tokens=0)
        assert len(cost_tracker.get_summary()) == 0

    def test_clear(self, cost_tracker):
        cost_tracker.record("a", prompt_tokens=100, completion_tokens=50)
        cost_tracker.clear()
        assert len(cost_tracker.get_summary()) == 0

    def test_print_report_no_error(self, cost_tracker):
        cost_tracker.record("coder", prompt_tokens=100, completion_tokens=50)
        cost_tracker.print_report()  # 不应抛异常

    def test_print_report_empty(self, cost_tracker):
        cost_tracker.print_report()  # 空记录也不应抛异常
