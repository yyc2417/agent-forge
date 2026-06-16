"""共享 pytest fixtures。

提供跨测试文件复用的 fixture：
- bus: MessageBus 实例
- cost_tracker: CostTracker 实例
- hooks: HookManager 实例
"""

import os

import pytest

from agent_forge.bus import MessageBus
from agent_forge.cost import CostTracker
from agent_forge.hooks import HookManager


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    """为所有测试设置假的 DEEPSEEK_API_KEY，防止 Agent 实例化时缺少环境变量报错。"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-fake-key-for-ci")


@pytest.fixture
def bus():
    """创建一个新的 MessageBus 实例。"""
    return MessageBus()


@pytest.fixture
def cost_tracker():
    """创建一个新的 CostTracker 实例。"""
    return CostTracker()


@pytest.fixture
def hooks():
    """创建一个新的 HookManager 实例。"""
    return HookManager()
