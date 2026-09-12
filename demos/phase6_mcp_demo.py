"""阶段 6 Demo —— MCP 工具生态接入（客户端侧）

演示 AgentForge 作为 MCP 客户端消费第三方工具的完整链路：
连接 MCP server → 工具注册进 ToolRegistry（权限 + 审批门）→ Agent 调用。

三步渐进式：
    --step 1  连接内置 demo server，列出通过 MCP 拿到的工具（无需 LLM）
    --step 2  Agent 通过 MCP 工具完成任务（echo 工具，真实 LLM 调用）
    --step 3  人工审批门（Human-in-the-Loop）：MCP 工具默认需要审批，
              控制台输入 y 放行 / n 拒绝，观察拒绝路径的 Agent 行为

前置条件：
    uv pip install -e ".[mcp]"        # mcp + langchain-mcp-adapters
    .env 中配置 DEEPSEEK_API_KEY       # step 2/3 需要

运行：
    python demos/phase6_mcp_demo.py --step 1
"""

import argparse
import sys

from agent_forge.tools import ToolPermission, ToolRegistry
from agent_forge.tools.mcp_tools import load_mcp_tools_into_registry
from agent_forge.utils import (
    print_info,
    print_separator,
    safe_print,
)

_DEMO_SERVER_ARGS = ["demos/mcp_demo_server.py"]


def _server_configs() -> dict:
    """内置 demo server 的连接配置（stdio 传输，随本仓库分发）。"""
    return {
        "agentforge-demo": {
            "command": sys.executable,
            "args": _DEMO_SERVER_ARGS,
            "transport": "stdio",
        },
    }


# ─── Step 1：连接并列出工具（无需 LLM）─────────────────────

def demo_step1() -> None:
    print_separator("Step 1: 连接 MCP server 并列出工具")
    registry = ToolRegistry()
    registered = load_mcp_tools_into_registry(_server_configs(), registry)

    print_info(f"从 MCP server 注册了 {len(registered)} 个工具:")
    for entry in registry.list_tools():
        safe_print(f"  - {entry['name']}（权限: {entry['permission']}，需审批）")


# ─── Step 2：Agent 调用 MCP 工具 ──────────────────────────

def demo_step2() -> None:
    print_separator("Step 2: Agent 通过 MCP 工具完成任务")
    registry = ToolRegistry()
    load_mcp_tools_into_registry(_server_configs(), registry)

    tools = registry.bind_tools(ToolPermission.EXECUTE, approval_callback=lambda n, a: True)
    safe_print(f"  Agent 可用工具: {[t.name for t in tools]}")

    from agent_forge.agents import BaseAgent

    agent = BaseAgent(
        name="mcp-agent",
        role="使用 MCP 工具的助手",
        tools=tools,
        max_turns=5,
    )
    result = agent.run(
        "请使用 echo 工具，把文本 'AgentForge 已接入 MCP 生态' 发送过去，"
        "然后告诉我 echo 返回了什么。"
    )
    safe_print("\n最终答复:")
    safe_print(result)


# ─── Step 3：人工审批门（HITL）────────────────────────────

def _console_approval(tool_name: str, tool_args: dict) -> bool:
    safe_print(f"\n  ⏸️  Agent 请求调用 MCP 工具: {tool_name}，参数: {tool_args}")
    answer = input("     是否放行？(y=放行 / n=拒绝): ").strip().lower()
    return answer == "y"


def demo_step3() -> None:
    print_separator("Step 3: 人工审批门 —— MCP 工具默认需要审批")
    registry = ToolRegistry()
    load_mcp_tools_into_registry(_server_configs(), registry)

    tools = registry.bind_tools(
        ToolPermission.EXECUTE, approval_callback=_console_approval
    )

    from agent_forge.agents import BaseAgent

    agent = BaseAgent(
        name="mcp-agent",
        role="使用 MCP 工具的助手",
        tools=tools,
        max_turns=5,
    )
    result = agent.run("请使用 echo 工具发送 'HITL 演示' 并汇报返回值。")
    safe_print("\n最终答复:")
    safe_print(result)
    print_info("提示：选择 n 拒绝时，Agent 会收到'用户拒绝执行'的反馈并调整策略。")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentForge MCP 接入 Demo")
    parser.add_argument("--step", type=int, default=1, choices=[1, 2, 3])
    args = parser.parse_args()

    {1: demo_step1, 2: demo_step2, 3: demo_step3}[args.step]()


if __name__ == "__main__":
    main()
