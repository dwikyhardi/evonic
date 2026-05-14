"""Tests for backend.dotenv_loader — the internal python-dotenv replacement."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.dotenv_loader import load_dotenv, _parse_and_set


def _cleanup_tempdir(path: str) -> None:
    """Remove temporary .env file and its parent directory."""
    if os.path.isfile(path):
        os.unlink(path)
    parent = os.path.dirname(path)
    if parent and os.path.isdir(parent):
        try:
            os.rmdir(parent)
        except OSError:
            pass


class TestParseAndSet(unittest.TestCase):
    """Unit tests for the internal _parse_and_set function."""

    def setUp(self):
        self.env_backup = os.environ.copy()
        # Remove keys we might set during tests
        for k in list(os.environ.keys()):
            if k.startswith("_TEST_DOTENV_"):
                del os.environ[k]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)

    def test_simple_key_value(self):
        _parse_and_set("_TEST_DOTENV_FOO=bar", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_FOO"], "bar")

    def test_empty_line_does_nothing(self):
        _parse_and_set("", override=False)
        _parse_and_set("   ", override=False)

    def test_comment_line_skipped(self):
        _parse_and_set("# this is a comment", override=False)
        _parse_and_set("  # indented comment", override=False)

    def test_inline_comment_stripped(self):
        _parse_and_set("_TEST_DOTENV_KEY=value # comment", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_KEY"], "value")

    def test_export_prefix_ignored(self):
        _parse_and_set("export _TEST_DOTENV_EXPORT=hello", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_EXPORT"], "hello")

    def test_double_quoted_value(self):
        _parse_and_set('_TEST_DOTENV_DQ="hello world"', override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_DQ"], "hello world")

    def test_single_quoted_value(self):
        _parse_and_set("_TEST_DOTENV_SQ='hello world'", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_SQ"], "hello world")

    def test_double_quote_escape_sequences(self):
        _parse_and_set('_TEST_DOTENV_ESC="line1\\nline2"', override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_ESC"], "line1\nline2")

    def test_double_quote_tab_escape(self):
        _parse_and_set('_TEST_DOTENV_TAB="col1\\tcol2"', override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_TAB"], "col1\tcol2")

    def test_override_false_does_not_overwrite(self):
        os.environ["_TEST_DOTENV_EXISTING"] = "original"
        _parse_and_set("_TEST_DOTENV_EXISTING=new", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_EXISTING"], "original")

    def test_override_true_overwrites(self):
        os.environ["_TEST_DOTENV_OVERWRITE"] = "original"
        _parse_and_set("_TEST_DOTENV_OVERWRITE=new", override=True)
        self.assertEqual(os.environ["_TEST_DOTENV_OVERWRITE"], "new")

    def test_empty_value(self):
        _parse_and_set("_TEST_DOTENV_EMPTY=", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_EMPTY"], "")

    def test_value_with_spaces(self):
        _parse_and_set("_TEST_DOTENV_SPACE=   spaced   ", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_SPACE"], "spaced")

    def test_key_with_underscores(self):
        _parse_and_set("_TEST_DOTENV_DEEP_KEY=deep", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_DEEP_KEY"], "deep")

    def test_escaped_hash_in_unquoted_value(self):
        _parse_and_set(r"_TEST_DOTENV_HASH=value\#notcomment", override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_HASH"], "value#notcomment")

    def test_malformed_no_equals(self):
        _parse_and_set("_TEST_DOTENV_BAD", override=False)
        self.assertNotIn("_TEST_DOTENV_BAD", os.environ)

    def test_empty_key(self):
        _parse_and_set("=value", override=False)
        # Should not raise or set anything with empty key

    def test_value_with_equals_sign(self):
        _parse_and_set('_TEST_DOTENV_EQ="a=b=c"', override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_EQ"], "a=b=c")

    def test_value_with_hash_in_quotes(self):
        _parse_and_set('_TEST_DOTENV_HQ="value#notacomment"', override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_HQ"], "value#notacomment")


class TestLoadDotenv(unittest.TestCase):
    """Integration tests for the full load_dotenv() function."""

    def setUp(self):
        self.env_backup = os.environ.copy()
        for k in list(os.environ.keys()):
            if k.startswith("_TEST_DOTENV_"):
                del os.environ[k]
        self.temp_dir = tempfile.mkdtemp(prefix="dotenv_test_")
        self.dotenv_path = os.path.join(self.temp_dir, ".env")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)
        if os.path.isfile(self.dotenv_path):
            os.unlink(self.dotenv_path)
        if os.path.isdir(self.temp_dir):
            os.rmdir(self.temp_dir)

    def _write_dotenv(self, content: str):
        with open(self.dotenv_path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_file_not_found_returns_false(self):
        result = load_dotenv("/nonexistent/.env")
        self.assertFalse(result)

    def test_custom_path_loaded(self):
        self._write_dotenv("_TEST_DOTENV_CUSTOM=yes\n")
        result = load_dotenv(self.dotenv_path)
        self.assertTrue(result)
        self.assertEqual(os.environ["_TEST_DOTENV_CUSTOM"], "yes")

    def test_default_path_loaded(self):
        cwd_dotenv = os.path.join(os.getcwd(), ".env")
        original = None
        if os.path.isfile(cwd_dotenv):
            with open(cwd_dotenv) as f:
                original = f.read()
        try:
            with open(cwd_dotenv, "w") as f:
                f.write("_TEST_DOTENV_DEFAULT=present\n")
            result = load_dotenv()
            self.assertTrue(result)
            self.assertEqual(os.environ["_TEST_DOTENV_DEFAULT"], "present")
        finally:
            if original is not None:
                with open(cwd_dotenv, "w") as f:
                    f.write(original)
            elif os.path.isfile(cwd_dotenv):
                os.unlink(cwd_dotenv)

    def test_multiline_dotenv(self):
        self._write_dotenv(
            "# Comment line\n"
            "_TEST_DOTENV_ML_A=first\n"
            "\n"
            "_TEST_DOTENV_ML_B=second\n"
            "   \n"
            'export _TEST_DOTENV_ML_C="third"\n'
        )
        load_dotenv(self.dotenv_path)
        self.assertEqual(os.environ["_TEST_DOTENV_ML_A"], "first")
        self.assertEqual(os.environ["_TEST_DOTENV_ML_B"], "second")
        self.assertEqual(os.environ["_TEST_DOTENV_ML_C"], "third")

    def test_override_default_does_not_overwrite(self):
        os.environ["_TEST_DOTENV_PRESET"] = "existing"
        self._write_dotenv("_TEST_DOTENV_PRESET=new\n")
        load_dotenv(self.dotenv_path, override=False)
        self.assertEqual(os.environ["_TEST_DOTENV_PRESET"], "existing")

    def test_override_true_overwrites(self):
        os.environ["_TEST_DOTENV_PRESET"] = "existing"
        self._write_dotenv("_TEST_DOTENV_PRESET=new\n")
        load_dotenv(self.dotenv_path, override=True)
        self.assertEqual(os.environ["_TEST_DOTENV_PRESET"], "new")

    def test_special_chars_in_value(self):
        self._write_dotenv('_TEST_DOTENV_SPECIAL="!@#$%^&*()"\n')
        load_dotenv(self.dotenv_path)
        self.assertEqual(os.environ["_TEST_DOTENV_SPECIAL"], "!@#$%^&*()")

    def test_quoted_value_with_escape_sequences(self):
        self._write_dotenv('_TEST_DOTENV_NEWLINE="hello\\nworld"\n')
        load_dotenv(self.dotenv_path)
        self.assertEqual(os.environ["_TEST_DOTENV_NEWLINE"], "hello\nworld")


if __name__ == "__main__":
    unittest.main()
