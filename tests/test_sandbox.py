"""工具沙箱（sandbox.py）单元测试。"""

from pathlib import Path

from agent_forge.tools.sandbox import (
    clear_sandbox_root,
    get_sandbox_root,
    is_sensitive_file,
    resolve_in_sandbox,
    set_sandbox_root,
)


class TestSandboxRoot:
    """沙箱根目录的设置与获取。"""

    def test_default_root_is_cwd(self, tmp_path, monkeypatch):
        """未设置沙箱根时，回退到进程 cwd（secure-by-default）。"""
        monkeypatch.chdir(tmp_path)
        clear_sandbox_root()
        assert get_sandbox_root() == tmp_path.resolve()

    def test_set_and_get(self, tmp_path):
        set_sandbox_root(tmp_path)
        assert get_sandbox_root() == tmp_path.resolve()

    def test_clear_falls_back_to_cwd(self, tmp_path, monkeypatch):
        set_sandbox_root(tmp_path)
        clear_sandbox_root()
        monkeypatch.chdir(tmp_path)
        assert get_sandbox_root() == tmp_path.resolve()


class TestResolveInSandbox:
    """resolve_in_sandbox 的路径校验规则。"""

    def test_relative_path_anchors_to_root(self, tmp_path):
        set_sandbox_root(tmp_path)
        resolved, err = resolve_in_sandbox("sub/file.txt")
        assert err is None
        assert resolved == (tmp_path / "sub" / "file.txt").resolve()

    def test_absolute_path_inside_root_allowed(self, tmp_path):
        set_sandbox_root(tmp_path)
        target = tmp_path / "a.txt"
        resolved, err = resolve_in_sandbox(str(target))
        assert err is None
        assert resolved == target.resolve()

    def test_absolute_path_outside_root_rejected(self, tmp_path):
        set_sandbox_root(tmp_path)
        outside = tmp_path.parent / "elsewhere.txt"
        _, err = resolve_in_sandbox(str(outside))
        assert err is not None
        assert "超出沙箱" in err

    def test_dotdot_escape_rejected(self, tmp_path):
        set_sandbox_root(tmp_path / "inner")
        _, err = resolve_in_sandbox("../escape.txt")
        assert err is not None
        assert "超出沙箱" in err

    def test_dotdot_that_stays_inside_allowed(self, tmp_path):
        set_sandbox_root(tmp_path)
        resolved, err = resolve_in_sandbox("sub/../a.txt")
        assert err is None
        assert resolved == (tmp_path / "a.txt").resolve()


class TestSensitiveFiles:
    """敏感文件（.env*）保护。"""

    def test_env_file_detected(self):
        assert is_sensitive_file(Path(".env"))
        assert is_sensitive_file(Path("conf/.env.local"))
        assert not is_sensitive_file(Path("environment.yml"))

    def test_env_read_rejected_anywhere(self, tmp_path):
        set_sandbox_root(tmp_path)
        (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
        _, err = resolve_in_sandbox(".env")
        assert err is not None
        assert "敏感文件" in err

    def test_env_write_rejected(self, tmp_path):
        set_sandbox_root(tmp_path)
        from agent_forge.tools import write_file

        result = write_file.invoke({"path": ".env", "content": "A=1"})
        assert "敏感文件" in result
        assert not (tmp_path / ".env").exists()
