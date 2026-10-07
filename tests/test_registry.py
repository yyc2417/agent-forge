"""ToolRegistry 单元测试。"""

from langchain_core.tools import tool

from agent_forge.tools import (
    ToolPermission,
    ToolRegistry,
    grep_search,
    read_file,
    run_shell,
    write_file,
)


class TestToolRegistry:
    """ToolRegistry 核心功能测试。"""

    def test_register_and_get(self):
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        tools = registry.get_all_tools()
        assert any(t.name == "read_file" for t in tools)

    def test_unregister(self):
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.unregister("read_file")
        tools = registry.get_all_tools()
        assert not any(t.name == "read_file" for t in tools)

    def test_get_by_permission_read(self):
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.register(write_file, ToolPermission.WRITE)
        registry.register(run_shell, ToolPermission.EXECUTE)
        read_tools = registry.get_tools(ToolPermission.READ)
        assert any(t.name == "read_file" for t in read_tools)
        assert not any(t.name == "write_file" for t in read_tools)

    def test_get_by_permission_write(self):
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.register(write_file, ToolPermission.WRITE)
        write_tools = registry.get_tools(ToolPermission.WRITE)
        assert any(t.name == "write_file" for t in write_tools)

    def test_has_tool(self):
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        assert registry.has_tool("read_file") is True
        assert registry.has_tool("nonexistent") is False

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.register(write_file, ToolPermission.WRITE)
        tools = registry.list_tools()
        names = [t["name"] if isinstance(t, dict) else t.name for t in tools]
        assert "read_file" in names
        assert "write_file" in names

    def test_get_permission(self):
        registry = ToolRegistry()
        registry.register(run_shell, ToolPermission.EXECUTE)
        perm = registry.get_permission("run_shell")
        assert perm == ToolPermission.EXECUTE


@tool
def _echo(text: str) -> str:
    """回显输入文本（测试辅助工具）。"""
    return f"echo: {text}"


class TestApprovalGate:
    """bind_tools 审批门（HITL 地基）。"""

    def _make_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.register(_echo, ToolPermission.READ, requires_approval=True)
        return registry

    def test_non_approval_tool_passthrough(self):
        registry = self._make_registry()
        bound = registry.bind_tools(ToolPermission.READ, approval_callback=lambda n, a: True)
        t = next(t for t in bound if t.name == "read_file")
        result = t.invoke({"path": "some_file.txt"})
        assert isinstance(result, str)

    def test_denied_approval_returns_error_string(self):
        registry = self._make_registry()
        bound = registry.bind_tools(ToolPermission.READ, approval_callback=lambda n, a: False)
        gated = next(t for t in bound if t.name == "_echo")
        result = gated.invoke({"text": "hi"})
        assert "拒绝执行" in result
        assert "echo: hi" not in result

    def test_granted_approval_executes(self):
        registry = self._make_registry()
        bound = registry.bind_tools(ToolPermission.READ, approval_callback=lambda n, a: True)
        gated = next(t for t in bound if t.name == "_echo")
        assert gated.invoke({"text": "hi"}) == "echo: hi"

    def test_no_callback_defaults_to_deny(self):
        """注册了 requires_approval 但未提供回调 → fail-safe 全部拒绝。"""
        registry = self._make_registry()
        bound = registry.bind_tools(ToolPermission.READ)
        gated = next(t for t in bound if t.name == "_echo")
        assert "拒绝执行" in gated.invoke({"text": "hi"})

    def test_schema_preserved_after_wrap(self):
        """审批包装对 LLM 透明：name/description/args_schema 不变。"""
        registry = self._make_registry()
        bound = registry.bind_tools(ToolPermission.READ, approval_callback=lambda n, a: True)
        gated = next(t for t in bound if t.name == "_echo")
        assert gated.name == "_echo"
        assert gated.description == _echo.description
        assert gated.args_schema == _echo.args_schema

    def test_permission_filter_still_applies(self):
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.register(run_shell, ToolPermission.EXECUTE, requires_approval=True)
        bound = registry.bind_tools(ToolPermission.READ, approval_callback=lambda n, a: True)
        assert [t.name for t in bound] == ["read_file"]

    def test_requires_approval_query(self):
        registry = self._make_registry()
        assert registry.requires_approval("_echo") is True
        assert registry.requires_approval("read_file") is False
        assert registry.requires_approval("nonexistent") is False


class TestSpecialistsRegistryBinding:
    """Specialist 经 ToolRegistry 按权限绑定工具（权限模型接线验证）。"""

    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(read_file, ToolPermission.READ)
        registry.register(grep_search, ToolPermission.READ)
        registry.register(write_file, ToolPermission.WRITE)
        registry.register(run_shell, ToolPermission.EXECUTE)
        return registry

    def test_reviewer_gets_read_only(self):
        from agent_forge.agents import ReviewerAgent

        agent = ReviewerAgent(registry=self._registry())
        names = [t.name for t in agent._tools]
        assert names == ["read_file"] or set(names) <= {"read_file", "grep_search"}
        assert "run_shell" not in names
        assert "write_file" not in names

    def test_coder_gets_full_tools(self):
        from agent_forge.agents import CoderAgent

        agent = CoderAgent(registry=self._registry())
        names = [t.name for t in agent._tools]
        assert set(names) == {"read_file", "grep_search", "write_file", "run_shell"}

    def test_default_tools_unchanged_without_registry(self):
        """不传 registry 保持向后兼容（现有硬编码工具列表）。

        硬编码列表必须与各自 registry 路径（bind_tools(max_permission)
        对默认注册表的过滤结果）一致——2026-09-13 benchmark 实测发现
        Coder/Reviewer 硬编码路径缺 grep_search，两种构造路径曾不对等。
        """
        from agent_forge.agents import CoderAgent, ReviewerAgent, WriterAgent

        coder = [t.name for t in CoderAgent()._tools]
        assert set(coder) == {"read_file", "grep_search", "write_file", "run_shell"}

        reviewer = [t.name for t in ReviewerAgent()._tools]
        assert set(reviewer) == {"read_file", "grep_search"}

        writer = [t.name for t in WriterAgent()._tools]
        assert set(writer) == {"read_file", "write_file"}
