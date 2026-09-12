"""会话管理器 —— 会话自动保存/加载

管理 Agent 的会话生命周期：
- 创建新会话
- 保存 ShortTermMemory 到文件
- 加载已保存的会话
- 列出所有可用会话

存储结构：
    .agentforge/sessions/
    ├── index.json                        # 会话索引
    ├── session_20260612_143022.json       # 会话数据
    └── session_20260612_150100.json

设计理念：
    会话管理让 Agent 能在程序重启后恢复上次的对话上下文。
    用户退出 Demo 再重新进入时，可以选择恢复之前的会话，
    而不需要从头开始对话。

    与 ShortTermMemory.save()/load() 的关系：
    - ShortTermMemory 负责单条记忆的序列化/反序列化
    - SessionManager 负责会话的生命周期管理（创建/索引/选择/删除）
    - SessionManager 内部调用 ShortTermMemory.save()/load()

使用方式：
    mgr = SessionManager()
    sid = mgr.create_session("coder")
    mgr.save_session(sid, coder_memory)

    # 下次启动时
    sessions = mgr.list_sessions()
    latest = mgr.get_latest_session("coder")
    mgr.load_session(latest, coder_memory)
"""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_forge.utils import atomic_write_text, safe_print


class SessionManager:
    """会话管理器 —— 创建/保存/加载/列出会话。

    存储位置默认为 `.agentforge/sessions/`。
    会话数据使用 ShortTermMemory 的 save()/load() 方法序列化。
    """

    def __init__(self, base_dir: str = ".agentforge/sessions") -> None:
        """初始化会话管理器。

        Args:
            base_dir: 会话文件存储目录。
        """
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._base_dir / "index.json"
        self._index: dict[str, dict[str, Any]] = self._load_index()

    # ─── 核心操作 ──────────────────────────────────────────

    def create_session(self, agent_name: str) -> str:
        """创建新会话。

        Args:
            agent_name: Agent 名称（用于标记会话来源）。

        Returns:
            会话 ID（格式：session_YYYYMMDD_HHMMSS_xxxx，末尾为随机后缀）。
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 追加 4 位短随机后缀：秒级时间戳在同一秒内创建多个会话时
        # 会互相覆盖（索引条目丢失 + 数据文件共用）
        suffix = uuid.uuid4().hex[:4]
        session_id = f"session_{timestamp}_{suffix}"

        self._index[session_id] = {
            "agent_name": agent_name,
            "created": time.time(),
            "created_readable": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_count": 0,
            "file": f"{session_id}.json",
        }
        self._save_index()
        return session_id

    def save_session(self, session_id: str, memory) -> None:
        """保存会话数据到文件。

        内部调用 ShortTermMemory.save() 序列化消息。

        Args:
            session_id: 会话 ID。
            memory: ShortTermMemory 实例。
        """
        if session_id not in self._index:
            safe_print(f"  [SessionManager] 警告: 会话 '{session_id}' 不在索引中")
            return

        file_path = self._base_dir / self._index[session_id]["file"]
        memory.save(str(file_path))

        # 更新索引中的消息数
        self._index[session_id]["message_count"] = len(memory.get_messages())
        self._index[session_id]["last_saved"] = time.time()
        self._save_index()

    def load_session(self, session_id: str, memory) -> bool:
        """从文件加载会话数据到 ShortTermMemory。

        Args:
            session_id: 会话 ID。
            memory: ShortTermMemory 实例（会被覆盖为加载的内容）。

        Returns:
            True 加载成功，False 加载失败。
        """
        if session_id not in self._index:
            safe_print(f"  [SessionManager] 会话 '{session_id}' 不存在")
            return False

        file_path = self._base_dir / self._index[session_id]["file"]
        if not file_path.exists():
            safe_print(f"  [SessionManager] 会话文件不存在: {file_path}")
            return False

        try:
            memory.load(str(file_path))
            return True
        except Exception as e:
            safe_print(f"  [SessionManager] 加载失败: {e}")
            return False

    def list_sessions(self) -> list[dict]:
        """列出所有会话的摘要信息。

        Returns:
            会话信息列表，按创建时间倒序。
        """
        sessions = []
        for sid, info in self._index.items():
            sessions.append({
                "id": sid,
                "agent_name": info.get("agent_name", "unknown"),
                "created": info.get("created_readable", ""),
                "message_count": info.get("message_count", 0),
            })
        # 按创建时间倒序
        sessions.sort(key=lambda s: s["created"], reverse=True)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """删除一个会话。

        Args:
            session_id: 会话 ID。

        Returns:
            True 删除成功，False 会话不存在。
        """
        if session_id not in self._index:
            return False

        # 删除文件
        file_path = self._base_dir / self._index[session_id]["file"]
        if file_path.exists():
            file_path.unlink()

        del self._index[session_id]
        self._save_index()
        return True

    def get_latest_session(self, agent_name: str) -> str | None:
        """获取指定 Agent 的最近一次会话 ID。

        Args:
            agent_name: Agent 名称。

        Returns:
            会话 ID，或 None（没有该 Agent 的会话）。
        """
        agent_sessions = [
            (sid, info)
            for sid, info in self._index.items()
            if info.get("agent_name") == agent_name
        ]
        if not agent_sessions:
            return None

        # 按创建时间排序，取最新的
        agent_sessions.sort(key=lambda x: x[1].get("created", 0))
        return agent_sessions[-1][0]

    # ─── 内部方法 ──────────────────────────────────────────

    def _save_index(self) -> None:
        """保存会话索引到 JSON 文件（原子写入）。"""
        atomic_write_text(
            self._index_path,
            json.dumps(self._index, ensure_ascii=False, indent=2),
        )

    def _load_index(self) -> dict[str, dict[str, Any]]:
        """从 JSON 文件加载会话索引。

        损坏（JSON 解析失败或类型不是 dict）时先备份原文件再返回空：
        否则下次 _save_index() 会让所有历史会话变成孤儿文件。
        """
        if not self._index_path.exists():
            return {}
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("index 根元素不是 dict")
            return data
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            backup = self._index_path.with_suffix(".corrupt.bak")
            try:
                self._index_path.rename(backup)
                safe_print(
                    f"  [SessionManager] 索引损坏: {e}，"
                    f"已备份到 {backup.name}，从空索引开始"
                )
            except OSError:
                safe_print(f"  [SessionManager] 索引损坏: {e}，从空索引开始")
            return {}

    def __repr__(self) -> str:
        return f"SessionManager(sessions={len(self._index)}, dir={self._base_dir})"
