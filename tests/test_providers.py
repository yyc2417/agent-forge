"""LLM Provider 单元测试（不发起真实网络请求）。"""

from agent_forge.llm import create_deepseek_llm


class TestProviderDefaults:
    """兜底四件套之一：LLM 调用必须有超时与重试（旧版无限阻塞）。"""

    def test_timeout_and_retries_configured(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        llm = create_deepseek_llm()
        # langchain-openai 不同版本的属性名（timeout / request_timeout）
        timeout = getattr(llm, "request_timeout", None) or getattr(llm, "timeout", None)
        assert timeout is not None, "必须配置请求超时"
        assert llm.max_retries >= 1, "必须配置自动重试"
