"""短期记忆 —— 滑动窗口 + LLM 摘要压缩

管理 Agent 的对话上下文，核心机制：
1. 滑动窗口：保留最近 max_messages 条消息
2. 摘要压缩：超出窗口的消息用 LLM 生成摘要，保留关键信息

为什么需要短期记忆？
    默认情况下，BaseAgent.run() 每次调用都从零开始——
    用户第一轮说"写一个排序函数"，第二轮说"加上类型注解"，
    Agent 不知道"加上"指的是什么。

    短期记忆让 Agent 在多轮对话间保持上下文：
    - 用户的第一轮输入和 Agent 的回复被存入记忆
    - 第二轮调用时，记忆中的历史消息被注入到 LLM 请求中
    - Agent 能理解"加上类型注解"指的是之前的排序函数

为什么需要摘要压缩？
    LLM 上下文窗口有限（DeepSeek 128K），且越长越贵、越慢。
    如果对话很长（如 50 轮），直接注入所有历史会：
    - 消耗大量 token（成本高）
    - 降低 LLM 对最新对话的注意力（注意力分散问题）

    摘要压缩是折中方案：
    - 用少量 token（~200 字摘要）保留历史的关键信息
    - 只保留最近 N 条消息的完整内容
    - 老消息被压缩为摘要，作为 SystemMessage 注入

LLM 为 None 的降级策略：
    如果未提供 LLM（_llm=None），压缩退化为简单截断——
    直接丢弃最早的消息，不做摘要。这保证了不依赖 LLM 也能工作。

与长期记忆的区别：
    - 短期记忆：自动管理，Agent 运行过程中自动存取，用于多轮对话上下文
    - 长期记忆：手动管理，Agent 通过工具显式 store/recall，用于跨会话知识
"""

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import (
    BaseMessage,
    messages_from_dict,
    messages_to_dict,
)
from langchain_openai import ChatOpenAI

from agent_forge.utils import atomic_write_text, safe_print

# ─── 摘要 Prompt ───────────────────────────────────────────

_SUMMARY_PROMPT = """\
你是对话摘要助手。请将以下对话历史压缩为一段简洁的摘要（不超过200字）。
保留关键信息：用户的任务目标、已完成的操作、重要的工具调用结果。
忽略无关的寒暄和重复内容。

{existing_summary_section}需要压缩的对话：
{messages_text}

请直接输出更新后的摘要："""


class ShortTermMemory:
    """短期记忆 —— 滑动窗口 + LLM 摘要压缩。

    Attributes:
        _messages: 当前消息列表（窗口内）。
        _summary: 累积的摘要文本（老消息被压缩到这里）。
        _max_messages: 滑动窗口大小。
        _llm: 用于摘要压缩的 LLM 实例（可选）。
    """

    def __init__(
        self,
        max_messages: int = 20,
        llm: ChatOpenAI | None = None,
    ) -> None:
        """初始化短期记忆。

        Args:
            max_messages: 滑动窗口大小，保留最近 N 条消息。
                          超过后触发摘要压缩。默认 20。
            llm: 用于摘要压缩的 LLM 实例。
                 None 时退化为简单截断（不做摘要）。
        """
        self._messages: list[BaseMessage] = []
        self._summary: str = ""
        self._max_messages = max_messages
        self._llm = llm

    # ─── 核心方法 ──────────────────────────────────────────

    def add(self, message: BaseMessage) -> None:
        """添加一条消息到短期记忆。

        如果消息数超过 max_messages，自动触发压缩。

        Args:
            message: 要添加的消息（HumanMessage / AIMessage / ToolMessage 等）。
        """
        self._messages.append(message)
        if len(self._messages) > self._max_messages:
            self.compress()

    def get_messages(self) -> list[BaseMessage]:
        """获取当前窗口内的消息列表。

        Returns:
            窗口内消息的列表（不包含摘要，摘要由 BaseAgent.run() 单独注入）。
        """
        return list(self._messages)

    def get_summary(self) -> str:
        """获取累积的摘要文本。

        Returns:
            摘要字符串。如果没有摘要过则为空字符串。
        """
        return self._summary

    # ─── 压缩 ─────────────────────────────────────────────

    def compress(self) -> None:
        """执行摘要压缩。

        策略：
        1. 取窗口前半部分消息作为待压缩部分
        2. 调用 LLM 生成摘要（约 200 字）
        3. 将摘要合并更新到 _summary
        4. 删除已压缩的消息，只保留后半部分

        LLM 为 None 时退化为简单截断（直接丢弃前半部分）。
        """
        mid = len(self._messages) // 2
        if mid <= 0:
            return

        to_compress = self._messages[:mid]

        if self._llm:
            # 用 LLM 生成摘要
            try:
                summary_text = self._generate_summary(to_compress)
                self._summary = summary_text
                self._messages = self._messages[mid:]  # 摘要成功才删除
            except Exception as e:
                safe_print(f"  [ShortTermMemory] 摘要失败: {e}，保留消息不压缩")
                return  # 失败时不删消息
        else:
            # 无 LLM 时简单截断
            self._messages = self._messages[mid:]

    def _generate_summary(self, messages: list[BaseMessage]) -> str:
        """调用 LLM 为消息列表生成摘要。

        Args:
            messages: 待压缩的消息列表。

        Returns:
            摘要文本。
        """
        # 构建消息文本
        messages_text_parts = []
        for msg in messages:
            role = msg.type if hasattr(msg, "type") else "unknown"
            content = msg.content if hasattr(msg, "content") else str(msg)
            # 截断过长的内容
            if len(content) > 500:
                content = content[:500] + "..."
            messages_text_parts.append(f"[{role}] {content}")
        messages_text = "\n".join(messages_text_parts)

        # 构建 prompt
        existing_section = ""
        if self._summary:
            existing_section = f"当前累积摘要：\n{self._summary}\n\n"

        prompt = _SUMMARY_PROMPT.format(
            existing_summary_section=existing_section,
            messages_text=messages_text,
        )

        response = self._llm.invoke(prompt)
        return response.content.strip()

    # ─── 持久化 ───────────────────────────────────────────

    def save(self, path: str) -> None:
        """序列化短期记忆到 JSON 文件。

        使用 LangChain 内置的 messages_to_dict() 序列化消息，
        保证与 messages_from_dict() 兼容。

        Args:
            path: JSON 文件路径。
        """
        data = {
            "summary": self._summary,
            "messages": messages_to_dict(self._messages),
            "max_messages": self._max_messages,
        }
        # 原子写入：防止进程崩溃留下截断的半截 JSON
        atomic_write_text(
            path,
            json.dumps(data, ensure_ascii=False, indent=2),
        )

    def load(self, path: str) -> None:
        """从 JSON 文件恢复短期记忆。

        Args:
            path: JSON 文件路径。

        Raises:
            FileNotFoundError: 文件不存在时抛出。
        """
        file_path = Path(path)
        data: dict[str, Any] = json.loads(
            file_path.read_text(encoding="utf-8")
        )
        self._summary = data.get("summary", "")
        self._messages = messages_from_dict(data.get("messages", []))
        self._max_messages = data.get("max_messages", 20)

    # ─── 清空 ─────────────────────────────────────────────

    def clear(self) -> None:
        """清空短期记忆（消息和摘要都清空）。"""
        self._messages.clear()
        self._summary = ""

    # ─── 可读表示 ─────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"ShortTermMemory(messages={len(self._messages)}, "
            f"max={self._max_messages}, "
            f"has_summary={'yes' if self._summary else 'no'})"
        )
