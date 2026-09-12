"""MCP 接入单元测试（不依赖 mcp 包安装；真 server 集成用例标记 slow）。"""

import asyncio

import pytest
from langchain_core.tools import StructuredTool

from agent_forge.tools import ToolPermission, ToolRegistry
from agent_forge.tools.mcp_tools import (
    _MAX_DESCRIPTION_CHARS,
    McpEventLoop,
    _bridge_tool,
    load_mcp_tools_into_registry,
)

# ─── 后台事件循环桥 ──────────────────────────────────────


class TestMcpEventLoop:
    """同步框架 → 异步调用的桥接。"""

    def test_run_coro_executes_and_returns(self):
        import asyncio

        async def _add(a: int, b: int) -> int:
            await asyncio.sleep(0)
            return a + b

        host = McpEventLoop()
        try:
            assert host.run_coro(_add(2, 3), timeout=5) == 5
            assert host.run_coro(_add(10, 20), timeout=5) == 30
        finally:
            host.stop()

    def test_run_coro_timeout(self):
        import asyncio

        async def _slow() -> str:
            await asyncio.sleep(30)
            return "done"

        host = McpEventLoop()
        try:
            with pytest.raises(Exception):  # TimeoutError from future.result
                host.run_coro(_slow(), timeout=0.5)
        finally:
            host.stop()


# ─── 工具桥接与注册 ──────────────────────────────────────


class _FakeMcpTool:
    """模拟 langchain-mcp-adapters 返回的 MCP 工具对象。"""

    def __init__(self, name: str = "mcp_echo", description: str = "回声工具"):
        self.name = name
        self.description = description
        self.calls: list[dict] = []
        self._schema = StructuredTool.from_function(
            lambda text: text, name=name, description=description
        ).args_schema

    @property
    def args_schema(self):
        return self._schema

    async def ainvoke(self, kwargs: dict):
        self.calls.append(kwargs)
        return f"mcp-result: {kwargs.get('text', '')}"


class TestBridgeTool:
    def test_bridge_preserves_schema_and_truncates_description(self):
        long_desc = "A" * 2000
        pool = _FakePool()
        bridged = _bridge_tool(_FakeMcpTool(description=long_desc), pool)

        assert len(bridged.description) == _MAX_DESCRIPTION_CHARS
        assert bridged.name == "mcp_echo"
        assert bridged.args_schema is not None

    def test_bridge_routes_call_through_pool(self):
        pool = _FakePool()
        fake = _FakeMcpTool()
        bridged = _bridge_tool(fake, pool)

        result = bridged.invoke({"text": "hello"})
        assert result == "mcp-result: hello"
        assert fake.calls == [{"text": "hello"}]

    def test_registered_tool_requires_approval(self):
        """MCP 工具默认 requires_approval=True（ADR-005 安全默认）。"""
        registry = ToolRegistry()
        pool = _FakePool()
        registry.register(
            _bridge_tool(_FakeMcpTool(), pool),
            ToolPermission.EXECUTE,
            requires_approval=True,
        )
        assert registry.requires_approval("mcp_echo") is True

        # 审批拒绝 → 返回错误串而非执行
        bound = registry.bind_tools(ToolPermission.EXECUTE, approval_callback=lambda n, a: False)
        gated = next(t for t in bound if t.name == "mcp_echo")
        assert "拒绝执行" in gated.invoke({"text": "hi"})


class _FakePool:
    """假会话池：绕过 MCP 依赖，直接在测试进程内执行 ainvoke。"""

    def __init__(self):
        self._loop = asyncio.new_event_loop()

    def run_tool(self, tool, kwargs):
        return self._loop.run_until_complete(tool.ainvoke(kwargs))


# ─── 依赖提示 ────────────────────────────────────────────


def test_load_without_dependency_gives_install_hint():
    """未安装 mcp 依赖时，报错必须带安装指引（而不是裸 ImportError）。"""
    try:
        import langchain_mcp_adapters  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="mcp"):
            load_mcp_tools_into_registry({}, ToolRegistry())
        return
    pytest.skip("mcp 依赖已安装，跳过缺依赖路径测试")


# ─── 真实 server 集成（需要 API/进程开销，标记 slow）────────


@pytest.mark.slow
class TestRealServerIntegration:
    """连接内置 demo server 的端到端集成（需安装 [mcp] extra）。"""

    def test_connect_demo_server_and_call_echo(self, tmp_path):
        pytest.importorskip("mcp")
        pytest.importorskip("langchain_mcp_adapters")
        import sys

        registry = ToolRegistry()
        registered = load_mcp_tools_into_registry(
            {
                "agentforge-demo": {
                    "command": sys.executable,
                    "args": ["demos/mcp_demo_server.py"],
                    "transport": "stdio",
                },
            },
            registry,
            requires_approval=False,  # 集成测试不模拟人工
        )
        assert "echo" in registered
        bound = registry.bind_tools(ToolPermission.EXECUTE)
        echo_tool = next(t for t in bound if t.name == "echo")
        assert "AgentForge" in echo_tool.invoke({"text": "AgentForge"})
