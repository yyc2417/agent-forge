"""MCP 工具生态接入 —— 客户端侧（可选依赖）

通过 langchain-mcp-adapters 把任意 MCP server 的工具接入 ToolRegistry，
让 AgentForge 的 Agent 能使用 MCP 生态的第三方工具
（文件系统、GitHub、浏览器、数据库……）。

为什么需要常驻后台事件循环？
    MCP Python SDK 是 asyncio 优先的，而 AgentForge 整个框架是同步的。
    每次工具调用都 asyncio.run() 会反复创建/销毁 MCP 会话（慢且易碎）；
    这里用 daemon 线程跑一个常驻 loop，工具调用经
    run_coroutine_threadsafe 桥接到同一 loop 上执行——
    会话在 loop 生命周期内保持打开并复用。

安全默认（见 ADR-005）：
    - MCP 工具默认 EXECUTE 权限 + requires_approval=True：
      第三方工具在 Human-in-the-Loop 审批后才真正执行
    - 工具描述截断到 _MAX_DESCRIPTION_CHARS，防止超长描述膨胀
      上下文或夹带提示注入文本（tool poisoning）

依赖（可选，不影响核心库）：uv pip install -e ".[mcp]"
"""

import asyncio
import atexit
import threading
from typing import Any

from langchain_core.tools import StructuredTool

from agent_forge.tools.registry import ToolPermission, ToolRegistry

# 工具描述截断上限（防注入膨胀 + 控制上下文占用）
_MAX_DESCRIPTION_CHARS = 500

# 已连接的会话池（进程退出时统一关闭）
_ACTIVE_POOLS: list["McpSessionPool"] = []


class McpEventLoop:
    """常驻后台事件循环 —— 同步框架调用异步 MCP 工具的桥。

    daemon 线程跑 run_forever()，同步侧通过 run_coro() 提交协程并
    阻塞等待结果。所有 MCP 会话与调用都在同一 loop 上，连接可复用。
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="mcp-event-loop"
        )
        self._started = False
        self._lock = threading.Lock()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self._thread.start()
                self._started = True

    def run_coro(self, coro, timeout: float = 120.0) -> Any:
        """在后台 loop 上执行协程并阻塞等待结果（线程安全）。

        Args:
            coro: 要执行的协程对象。
            timeout: 等待结果的超时（秒）——同步侧不能被异步调用无限阻塞。
        """
        self.start()
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout)

    def stop(self) -> None:
        if self._started:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                pass  # loop 已关闭


class McpSessionPool:
    """MCP 会话宿主 —— 在后台 loop 中保持会话打开并复用。

    生命周期：connect() 建立连接并拉取工具列表 → 工具调用经
    run_tool() 在同一 loop 上执行 → stop() 关闭会话。
    """

    def __init__(
        self,
        server_configs: dict,
        connect_timeout: float = 60.0,
        call_timeout: float = 120.0,
    ) -> None:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as e:
            raise ImportError(
                'MCP 支持需要可选依赖：uv pip install -e ".[mcp]" '
                "(mcp + langchain-mcp-adapters)"
            ) from e

        self._client = MultiServerMCPClient(server_configs)
        self._loop_host = McpEventLoop()
        self._connect_timeout = connect_timeout
        self._call_timeout = call_timeout
        self._tools: list = []
        self._connected = False
        self._error: Exception | None = None
        self._ready = threading.Event()
        self._stop_event: asyncio.Event | None = None

    # ── 连接管理 ──────────────────────────────────────────

    def connect(self) -> list:
        """连接所有 server 并返回工具列表（阻塞直至完成或超时）。

        会话通过 async with 保持打开（stdio/HTTP 连接持续有效），
        后续 run_tool() 复用这些会话。

        Returns:
            langchain 工具对象列表（来自所有 server）。

        Raises:
            ImportError: 未安装 mcp 可选依赖。
            TimeoutError: 连接超时。
            Exception: 连接失败（server 启动失败、协议错误等）。
        """
        self._loop_host.start()
        asyncio.run_coroutine_threadsafe(self._session_coro(), self._loop_host.loop)
        if not self._ready.wait(self._connect_timeout):
            raise TimeoutError(f"MCP 连接超时（{self._connect_timeout}s）")
        if self._error:
            raise self._error
        return self._tools

    async def _session_coro(self) -> None:
        """加载工具列表并保持就绪（兼容 adapters 新旧两种 API 形态）。

        - 0.1.x：get_tools() 是 async context manager，返回的工具
          在每次调用时自建会话（stdio 传输 = 每次调用拉起 server 子进程）
        - 0.0.x：get_tools() 是普通协程，会话持久保存在 client 内
        """
        try:
            loader = self._client.get_tools()
            if asyncio.iscoroutine(loader):
                # 0.0.x 形态：直接等待协程结果
                tools = await loader
            else:
                # 0.1.x 形态：进入 context manager 加载工具定义
                async with loader as loaded:
                    tools = list(loaded)
            self._tools = list(tools)
            self._connected = True
            self._stop_event = asyncio.Event()
            self._ready.set()
            await self._stop_event.wait()
        except Exception as e:  # noqa: BLE001 - 连接失败要完整传回同步侧
            self._error = e
            self._ready.set()

    def stop(self) -> None:
        """关闭会话与后台事件循环。"""
        if self._stop_event is not None:
            def _signal() -> None:
                if self._stop_event is not None:
                    self._stop_event.set()
            try:
                self._loop_host.loop.call_soon_threadsafe(_signal)
            except RuntimeError:
                pass
        self._loop_host.stop()

    # ── 工具调用 ──────────────────────────────────────────

    def run_tool(self, tool, kwargs: dict) -> Any:
        """在后台 loop 上执行一次 MCP 工具调用（同步阻塞）。"""
        if not self._connected:
            raise RuntimeError("MCP 会话未连接，请先调用 connect()")
        return self._loop_host.run_coro(tool.ainvoke(kwargs), self._call_timeout)


def _bridge_tool(tool, pool: McpSessionPool) -> StructuredTool:
    """把异步 MCP 工具桥接为同步 LangChain 工具。

    - 调用经 pool 的后台 loop 执行（会话复用）
    - 描述截断到 _MAX_DESCRIPTION_CHARS（防注入膨胀）
    - name/args_schema 原样保留，对 LLM 透明
    """
    description = (tool.description or "")[:_MAX_DESCRIPTION_CHARS]

    def _call(**kwargs):
        return pool.run_tool(tool, kwargs)

    return StructuredTool.from_function(
        func=_call,
        name=tool.name,
        description=description,
        args_schema=tool.args_schema,
    )


def load_mcp_tools_into_registry(
    server_configs: dict,
    registry: ToolRegistry,
    permission: ToolPermission = ToolPermission.EXECUTE,
    requires_approval: bool = True,
    connect_timeout: float = 60.0,
    call_timeout: float = 120.0,
) -> list[str]:
    """连接 MCP servers 并把工具注册进 ToolRegistry。

    Args:
        server_configs: MultiServerMCPClient 连接配置，例如
            {
                "demo": {
                    "command": sys.executable,
                    "args": ["demos/mcp_demo_server.py"],
                    "transport": "stdio",
                },
            }
        registry: 目标工具注册表。
        permission: 注册的权限级别（默认 EXECUTE——第三方工具按最高
                   风险等级对待）。
        requires_approval: 是否要求人工审批（默认 True，
                          配合 registry.bind_tools 的 approval_callback）。
        connect_timeout: 连接超时（秒）。
        call_timeout: 单次工具调用超时（秒）。

    Returns:
        注册成功的工具名列表。

    Raises:
        ImportError: 未安装 mcp 可选依赖（附安装提示）。
        Exception: 连接失败。
    """
    pool = McpSessionPool(
        server_configs, connect_timeout=connect_timeout, call_timeout=call_timeout
    )
    raw_tools = pool.connect()

    registered: list[str] = []
    for tool in raw_tools:
        registry.register(
            _bridge_tool(tool, pool),
            permission,
            requires_approval=requires_approval,
        )
        registered.append(tool.name)

    # 会话池保活引用 + 进程退出时统一关闭
    _ACTIVE_POOLS.append(pool)
    return registered


@atexit.register
def _close_active_pools() -> None:
    """进程退出时关闭所有仍打开的 MCP 会话。"""
    for pool in list(_ACTIVE_POOLS):
        try:
            pool.stop()
        except Exception:
            pass
    _ACTIVE_POOLS.clear()
