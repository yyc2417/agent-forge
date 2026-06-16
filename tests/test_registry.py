"""ToolRegistry 单元测试。"""

from agent_forge.tools import ToolPermission, ToolRegistry, read_file, run_shell, write_file


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
