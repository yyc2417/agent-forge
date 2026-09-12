"""AgentForge 内置 MCP 演示服务器（FastMCP，stdio 传输）。

供 demos/phase6_mcp_demo.py 连接使用，暴露两个最小工具，
演示"AgentForge 作为 MCP 客户端消费第三方工具"的完整链路。

单独运行（调试用）：
    python demos/mcp_demo_server.py
"""

from datetime import datetime

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agentforge-demo")


@mcp.tool()
def echo(text: str) -> str:
    """原样返回输入文本（演示用回声工具）。"""
    return f"echo: {text}"


@mcp.tool()
def get_now() -> str:
    """返回服务器当前的本地时间（ISO 格式，演示用）。"""
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    mcp.run()  # 默认 stdio 传输
