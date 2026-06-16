"""工具系统单元测试。"""


from agent_forge.tools import grep_search, read_file, run_shell, write_file


class TestReadFile:
    """read_file 工具测试。"""

    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = read_file.invoke({"path": str(f)})
        assert "hello world" in result

    def test_read_nonexistent_file(self):
        result = read_file.invoke({"path": "nonexistent_file_xyz.txt"})
        assert "错误" in result or "不存在" in result

    def test_read_directory(self, tmp_path):
        result = read_file.invoke({"path": str(tmp_path)})
        assert "错误" in result or "目录" in result


class TestWriteFile:
    """write_file 工具测试。"""

    def test_write_new_file(self, tmp_path):
        f = tmp_path / "output.txt"
        result = write_file.invoke({"path": str(f), "content": "test data"})
        assert "成功" in result
        assert f.read_text(encoding="utf-8") == "test data"

    def test_write_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "file.txt"
        result = write_file.invoke({"path": str(f), "content": "nested"})
        assert "成功" in result
        assert f.exists()

    def test_write_overwrites_existing(self, tmp_path):
        f = tmp_path / "overwrite.txt"
        f.write_text("old", encoding="utf-8")
        write_file.invoke({"path": str(f), "content": "new"})
        assert f.read_text(encoding="utf-8") == "new"


class TestRunShell:
    """run_shell 工具测试。"""

    def test_simple_command(self):
        result = run_shell.invoke({"command": "echo hello"})
        assert "hello" in result

    def test_python_version(self):
        result = run_shell.invoke({"command": "python --version"})
        assert "Python" in result

    def test_forbidden_command_blocked(self):
        result = run_shell.invoke({"command": "rm -rf /"})
        assert "拦截" in result or "安全" in result


class TestGrepSearch:
    """grep_search 工具测试。"""

    def test_search_finds_pattern(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    pass\n", encoding="utf-8")
        result = grep_search.invoke({
            "pattern": "def hello",
            "path": str(tmp_path),
        })
        assert "hello" in result

    def test_search_no_match(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = grep_search.invoke({
            "pattern": "nonexistent_pattern_xyz",
            "path": str(tmp_path),
        })
        # 应该返回无结果的信息
        assert isinstance(result, str)
