"""测试用假对象（不依赖真实 LLM API）。

提供可编排响应序列的假 LLM，供 Agent / Orchestrator / 兜底机制的
单元测试使用，让"循环保护、循环检测、失败熔断"等路径可以脱离
网络被确定性验证。
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class FakeToolCallingLLM(BaseChatModel):
    """按预置脚本依次返回 AIMessage 的假 LLM。

    支持 bind_tools（返回自身，Agent 构造时无感知）。

    用法：
        llm = FakeToolCallingLLM(responses=[
            AIMessage(content="", tool_calls=[{"name": "read_file",
                                               "args": {"path": "a.py"},
                                               "id": "c1"}]),
            AIMessage(content="完成"),
        ])

    responses 依次弹出；耗尽后重复返回最后一条（便于测试终止路径）。
    """

    responses: list[AIMessage] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolCallingLLM":
        """兼容 Agent 的 bind_tools 调用：直接返回自身。"""
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.responses:
            message = AIMessage(content="")
        elif len(self.responses) == 1:
            message = self.responses[0]
        else:
            message = self.responses.pop(0)
        if not isinstance(message, AIMessage):
            message = AIMessage(content=str(message))
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"
