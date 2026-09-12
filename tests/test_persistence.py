"""持久化可靠性测试：原子写入、损坏恢复、会话 ID 冲突。"""

import json
import time

from langchain_core.messages import HumanMessage

from agent_forge.memory import LongTermMemory, SessionManager, ShortTermMemory
from agent_forge.utils import atomic_write_text


class TestAtomicWrite:
    """atomic_write_text 基础行为。"""

    def test_write_and_read_back(self, tmp_path):
        target = tmp_path / "data" / "file.json"
        atomic_write_text(target, '{"a": 1}')
        assert target.read_text(encoding="utf-8") == '{"a": 1}'

    def test_overwrite_replaces_content(self, tmp_path):
        target = tmp_path / "f.txt"
        atomic_write_text(target, "old")
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_tmp_files_left(self, tmp_path):
        target = tmp_path / "f.txt"
        atomic_write_text(target, "x")
        leftovers = [p for p in tmp_path.iterdir() if p.name != "f.txt"]
        assert leftovers == []


class TestShortTermPersistence:
    """ShortTermMemory.save 使用原子写。"""

    def test_save_load_roundtrip(self, tmp_path):
        mem = ShortTermMemory()
        mem.add(HumanMessage(content="hello"))
        path = tmp_path / "mem.json"
        mem.save(str(path))

        mem2 = ShortTermMemory()
        mem2.load(str(path))
        assert len(mem2.get_messages()) == 1


class TestLongTermCorruptionRecovery:
    """LongTermMemory：损坏文件先备份再重建（P1 修复验证）。"""

    def test_corrupt_file_backed_up_not_overwritten(self, tmp_path):
        target = tmp_path / "lt.json"
        target.write_text("{截断的半截 JSON", encoding="utf-8")

        mem = LongTermMemory(file_path=str(target))
        mem.store("k1", "v1")  # 触发 _persist：旧行为会用空存储覆盖损坏文件

        backup = target.with_suffix(".corrupt.bak")
        assert backup.exists(), "损坏文件应被备份，而不是被覆盖销毁"
        assert "截断" in backup.read_text(encoding="utf-8")
        # 新存储正常工作
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")).get("k1") is not None


class TestSessionManagerRobustness:
    """SessionManager：同秒创建不冲突 + 索引损坏恢复。"""

    def test_same_second_sessions_unique(self, tmp_path):
        """修复验证：秒级时间戳 ID 加随机后缀，同秒创建不再互相覆盖。"""
        mgr = SessionManager(base_dir=str(tmp_path / "sessions"))
        id1 = mgr.create_session("agent1")
        id2 = mgr.create_session("agent2")
        assert id1 != id2
        assert len(mgr.list_sessions()) >= 2

    def test_corrupt_index_backed_up(self, tmp_path):
        """修复验证：索引损坏时备份原文件（旧版返回空 dict 后会让历史会话变孤儿）。"""
        base = tmp_path / "sessions"
        base.mkdir(parents=True)
        index_path = base / "index.json"
        index_path.write_text("not-a-json{", encoding="utf-8")

        mgr = SessionManager(base_dir=str(base))
        assert mgr.list_sessions() == []
        backup = base / "index.corrupt.bak"
        assert backup.exists()
        assert "not-a-json" in backup.read_text(encoding="utf-8")

    def test_non_dict_index_treated_as_corrupt(self, tmp_path):
        base = tmp_path / "sessions"
        base.mkdir(parents=True)
        (base / "index.json").write_text('["a", "b"]', encoding="utf-8")

        mgr = SessionManager(base_dir=str(base))
        assert mgr.list_sessions() == []
        assert (base / "index.corrupt.bak").exists()


class TestTimeBasedId:
    """session_id 仍保留时间戳可读性。"""

    def test_id_format(self, tmp_path):
        mgr = SessionManager(base_dir=str(tmp_path / "s"))
        sid = mgr.create_session("a")
        assert sid.startswith("session_")
        assert time.strftime("%Y%m%d") in sid
