"""LLM Provider 工厂函数

阶段 0：仅支持 DeepSeek（兼容 OpenAI API 格式）。
后续扩展：可在本模块添加 create_openai_llm()、create_local_llm() 等。

DeepSeek 连接说明：
    - DeepSeek API 完全兼容 OpenAI SDK，直接用 langchain-openai 的 ChatOpenAI
    - 只需修改 base_url 和 api_key，不需要额外适配
    - 模型推荐 deepseek-v4-flash（V4 系列，性价比最优）
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

# 加载 .env 文件中的环境变量
# 注意: load_dotenv() 不会覆盖已存在的环境变量，确保手动设置的环境变量优先级更高
load_dotenv()


def create_deepseek_llm(
    model: str | None = None,
    temperature: float = 0.0,
) -> ChatOpenAI:
    """创建 DeepSeek LLM 实例（兼容 OpenAI SDK 格式）

    设计决策：
        - temperature 默认 0.0：Agent 场景需要确定性输出，避免 LLM 随机性
          导致不可复现的决策错误
        - 所有配置从环境变量读取：方便 CI/CD 和 Docker 部署时切换环境

    Args:
        model: 模型名称。
               默认从 DEEPSEEK_MODEL 环境变量读取。
               可选值：deepseek-v4-flash（默认，性价比最优）
        temperature: 采样温度，范围 0.0-2.0。
                     Agent 场景建议 0.0，创意生成场景可适当提高

    Returns:
        ChatOpenAI 实例，已配置好 API Key 和 Base URL

    Raises:
        ValueError: 如果 DEEPSEEK_API_KEY 环境变量未设置

    Example:
        >>> llm = create_deepseek_llm()
        >>> response = llm.invoke("你好，请介绍一下你自己")
        >>> print(response.content)
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError(
            "未找到 DEEPSEEK_API_KEY 环境变量。\n"
            "请复制 .env.example 为 .env 并填入真实的 API Key。\n"
            "获取地址：https://platform.deepseek.com/api_keys"
        )

    return ChatOpenAI(
        model=model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        api_key=SecretStr(api_key),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        temperature=temperature,
        # 单次请求超时 + HTTP 层自动重试：
        # 防止一次挂起的 API 调用把同步 Agent 循环无限阻塞
        timeout=60,
        max_retries=2,
    )
