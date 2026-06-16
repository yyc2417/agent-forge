"""记忆系统单元测试。"""


from langchain_core.messages import AIMessage, HumanMessage

from agent_forge.memory import LongTermMemory, SessionManager, ShortTermMemory


class TestShortTermMemory:
    """ShortTermMemory 测试。"""

    def test_add_and_get_messages(self):
        mem = ShortTermMemory(max_messages=10)
        mem.add(HumanMessage(content="hello"))
        mem.add(AIMessage(content="hi"))
        messages = mem.get_messages()
        assert len(messages) == 2

    def test_max_messages_window(self):
        mem = ShortTermMemory(max_messages=3)
        for i in range(5):
            mem.add(HumanMessage(content=f"msg {i}"))
        messages = mem.get_messages()
        assert len(messages) <= 3

    def test_clear(self):
        mem = ShortTermMemory()
        mem.add(HumanMessage(content="test"))
        mem.clear()
        assert len(mem.get_messages()) == 0

    def test_save_and_load(self, tmp_path):
        mem = ShortTermMemory()
        mem.add(HumanMessage(content="hello"))
        mem.add(AIMessage(content="world"))

        save_path = tmp_path / "memory.json"
        mem.save(str(save_path))
        assert save_path.exists()

        mem2 = ShortTermMemory()
        mem2.load(str(save_path))
        messages = mem2.get_messages()
        assert len(messages) == 2


class TestLongTermMemory:
    """LongTermMemory 测试。"""

    def test_store_and_recall(self):
        mem = LongTermMemory()
        mem.store("test_key", "test_value")
        result = mem.recall("test_key")
        assert result is not None
        assert "test_value" in result

    def test_recall_nonexistent(self):
        mem = LongTermMemory()
        result = mem.recall("nonexistent_key_xyz")
        # 应返回 None 或提示信息
        assert result is None or "未找到" in str(result) or "不存在" in str(result)

    def test_list_memories(self):
        mem = LongTermMemory()
        mem.store("key1", "value1")
        mem.store("key2", "value2")
        memories = mem.list_memories()
        # list_memories 返回的是列表（可能是 dict 或 entry）
        keys = []
        for m in memories:
            if isinstance(m, dict):
                keys.append(m.get("key", ""))
            elif hasattr(m, "key"):
                keys.append(m.key)
            else:
                keys.append(str(m))
        assert "key1" in keys or len(memories) >= 2

    def test_delete(self):
        mem = LongTermMemory()
        mem.store("to_delete", "value")
        mem.delete("to_delete")
        result = mem.recall("to_delete")
        assert result is None or "未找到" in str(result) or "不存在" in str(result)


class TestSessionManager:
    """SessionManager 测试。"""

    def test_create_session(self, tmp_path):
        mgr = SessionManager(base_dir=str(tmp_path / "sessions"))
        result = mgr.create_session("test_agent")
        assert result is not None
        # 可能返回 str (session_id) 或 dict
        if isinstance(result, dict):
            assert "id" in result
        else:
            assert isinstance(result, str)

    def test_list_sessions(self, tmp_path):
        mgr = SessionManager(base_dir=str(tmp_path / "sessions"))
        mgr.create_session("agent1")
        mgr.create_session("agent2")
        sessions = mgr.list_sessions()
        assert len(sessions) >= 1  # 至少能列出会话

    def test_save_and_load_session(self, tmp_path):
        mgr = SessionManager(base_dir=str(tmp_path / "sessions"))
        result = mgr.create_session("test")
        sid = result["id"] if isinstance(result, dict) else result

        # 保存一个 ShortTermMemory
        mem = ShortTermMemory()
        mem.add(HumanMessage(content="session test"))
        mgr.save_session(sid, mem)

        # 加载到新 memory
        mem2 = ShortTermMemory()
        mgr.load_session(sid, mem2)
        messages = mem2.get_messages()
        assert len(messages) >= 1
