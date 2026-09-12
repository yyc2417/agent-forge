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
from agent_forge.tools.sandbox import clear_sandbox_root, set_sandbox_root


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    """为所有测试设置假的 DEEPSEEK_API_KEY，防止 Agent 实例化时缺少环境变量报错。"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-fake-key-for-ci")


@pytest.fixture(autouse=True)
def _sandbox_tmp(tmp_path):
    """为所有测试设置沙箱根目录到 tmp_path。

    工具沙箱默认以进程 cwd 为根（secure-by-default），而测试大量使用
    tmp_path 下的绝对路径——统一把沙箱根指到 tmp_path，
    既有测试无需逐个改造；越界路径的用例再自行 set_sandbox_root 覆盖。
    """
    set_sandbox_root(tmp_path)
    yield
    clear_sandbox_root()


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
