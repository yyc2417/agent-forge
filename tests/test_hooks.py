"""HookManager 单元测试。"""



class TestHookManager:
    """HookManager 核心功能测试。"""

    def test_register_and_trigger(self, hooks):
        called = []
        hooks.register("pre_llm_call", lambda **kw: called.append(kw))
        hooks.trigger("pre_llm_call", agent="coder", messages=[])
        assert len(called) == 1
        assert called[0]["agent"] == "coder"

    def test_multiple_callbacks(self, hooks):
        count = [0]
        hooks.register("post_llm_call", lambda **kw: count.__setitem__(0, count[0] + 1))
        hooks.register("post_llm_call", lambda **kw: count.__setitem__(0, count[0] + 1))
        hooks.trigger("post_llm_call", agent="a", response=None)
        assert count[0] == 2

    def test_callback_exception_isolation(self, hooks):
        """单个回调异常不影响其他回调。"""
        called = []
        hooks.register("pre_tool_use", lambda **kw: 1 / 0)
        hooks.register("pre_tool_use", lambda **kw: called.append(True))
        hooks.trigger("pre_tool_use", agent="a", tool_name="x", tool_args={})
        assert len(called) == 1

    def test_unregister(self, hooks):
        called = []

        def callback(**kw):
            called.append(True)

        hooks.register("post_tool_use", callback)
        hooks.unregister("post_tool_use", callback)
        hooks.trigger("post_tool_use", agent="a", tool_name="x", output="ok")
        assert len(called) == 0

    def test_clear_specific_event(self, hooks):
        hooks.register("pre_llm_call", lambda **kw: None)
        hooks.register("post_llm_call", lambda **kw: None)
        hooks.clear("pre_llm_call")
        assert "pre_llm_call" not in hooks.get_registered_events()
        assert "post_llm_call" in hooks.get_registered_events()

    def test_clear_all(self, hooks):
        hooks.register("pre_llm_call", lambda **kw: None)
        hooks.register("post_tool_use", lambda **kw: None)
        hooks.clear()
        assert len(hooks.get_registered_events()) == 0

    def test_get_registered_events(self, hooks):
        hooks.register("pre_llm_call", lambda **kw: None)
        hooks.register("pre_tool_use", lambda **kw: None)
        events = hooks.get_registered_events()
        assert "pre_llm_call" in events
        assert "pre_tool_use" in events

    def test_trigger_unregistered_event(self, hooks):
        """触发未注册的事件不应抛异常。"""
        hooks.trigger("pre_llm_call", agent="a", messages=[])  # 无回调，不应报错
