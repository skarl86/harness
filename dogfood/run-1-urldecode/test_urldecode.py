"""Unit tests for urldecode.py."""
import io
import json
import sys
import unittest
from unittest import mock

import urldecode


class TestDecodeLine(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(urldecode.decode_line("a%20b\n"), "a b")

    def test_empty_string(self):
        self.assertEqual(urldecode.decode_line(""), "")

    def test_percent_hex(self):
        self.assertEqual(urldecode.decode_line("%2Fpath"), "/path")


class TestMain(unittest.TestCase):
    def _run_with_stdin(self, stdin_text: str, argv=None):
        argv = ["urldecode.py"] + (argv or [])
        stdin = io.StringIO(stdin_text)
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(sys, "stdin", stdin), \
             mock.patch.object(sys, "stdout", stdout):
            rc = urldecode.main()
        return rc, stdout.getvalue()

    def test_text_mode_skips_blank_lines(self):
        rc, out = self._run_with_stdin("a%20b\n\n%2F\n")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "a b\n/\n")

    def test_json_mode(self):
        rc, out = self._run_with_stdin("a%20b\n", argv=["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(out.strip())
        self.assertEqual(parsed, {"input": "a%20b", "decoded": "a b"})


if __name__ == "__main__":
    unittest.main()
