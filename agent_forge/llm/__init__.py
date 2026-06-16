"""LLM Provider 模块

提供统一的 LLM 工厂函数，当前支持 DeepSeek。
后续可扩展多 Provider 支持（OpenAI / 本地模型 / 等）。

设计原则：
    - 统一接口：所有 Provider 返回 ChatOpenAI 兼容实例
    - 环境变量驱动：API Key 和 Base URL 从 .env 读取，不硬编码
    - 低耦合：切换模型只需改环境变量，无需改代码
"""

from .providers import create_deepseek_llm

__all__ = ["create_deepseek_llm"]
