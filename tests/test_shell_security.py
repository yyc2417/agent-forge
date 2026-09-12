"""shell 工具安全机制单元测试（纯函数检测，不执行真实命令）。"""

from agent_forge.tools.shell_tools import (
    _apply_windows_aliases,
    _find_forbidden,
)


class TestWindowsAliases:
    """Windows 别名映射（键不带尾随空格的修复验证）。"""

    def test_exact_command(self):
        assert _apply_windows_aliases("cat", is_windows=True) == "type"

    def test_command_with_args(self):
        assert _apply_windows_aliases("cat file.txt", is_windows=True) == "type file.txt"

    def test_single_space_no_double_match(self):
        """修复验证：'cat f' 之前因键带尾随空格而无法匹配。"""
        assert _apply_windows_aliases("cat f", is_windows=True) == "type f"

    def test_prefix_word_not_matched(self):
        """'catalog' 不应以 'cat' 别名被误替换。"""
        assert _apply_windows_aliases("catalog list", is_windows=True) == "catalog list"

    def test_mv_and_cp(self):
        assert _apply_windows_aliases("mv a b", is_windows=True) == "move a b"
        assert _apply_windows_aliases("cp a b", is_windows=True) == "copy a b"

    def test_mkdir_p(self):
        assert _apply_windows_aliases("mkdir -p x/y", is_windows=True) == "mkdir x/y"

    def test_noop_on_linux(self):
        assert _apply_windows_aliases("cat file", is_windows=False) == "cat file"

    def test_unknown_command_untouched(self):
        assert _apply_windows_aliases("python --version", is_windows=True) == "python --version"


class TestForbiddenDetection:
    """黑名单检测：子串名单 + 正则名单（参数变体覆盖）。"""

    def test_literal_rm_rf(self):
        assert _find_forbidden("rm -rf /") is not None

    def test_rm_flag_variants(self):
        """修复验证：rm 的参数变体不再漏过。"""
        assert _find_forbidden("rm -fr data") is not None
        assert _find_forbidden("rm -r -f data") is not None
        assert _find_forbidden("rm --recursive data") is not None

    def test_rm_without_recursive_allowed(self):
        assert _find_forbidden("rm file.txt") is None

    def test_rm_long_flag_word_not_false_positive(self):
        """'-reasonably' 这类以 -r 开头的长单词不应触发。"""
        assert _find_forbidden("rm -reasonably-named-file") is None

    def test_windows_recursive_delete(self):
        assert _find_forbidden("rmdir /s /q data") is not None
        assert _find_forbidden("del /s /q data") is not None

    def test_chmod_recursive_variant(self):
        assert _find_forbidden("chmod -R 777 /") is not None

    def test_format_anchored_not_substring(self):
        """修复验证：clang-format / npm run format 不再误伤，format 作命令开头仍拦截。"""
        assert _find_forbidden("clang-format --help") is None
        assert _find_forbidden("npm run format") is None
        assert _find_forbidden("format C:") is not None

    def test_dev_device_redirect(self):
        assert _find_forbidden("dd if=/dev/zero of=/dev/sda") is not None
        assert _find_forbidden("cat x > /dev/sda") is not None

    def test_whitespace_evasion_normalized(self):
        assert _find_forbidden("rm   -rf   /") is not None

    def test_benign_commands_allowed(self):
        assert _find_forbidden("git status") is None
        assert _find_forbidden("python script.py") is None
        assert _find_forbidden("ls -la && cat README.md") is None
