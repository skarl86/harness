"""Unit tests for wc.py."""
import io
import json
import sys
import unittest
from collections import Counter
from unittest import mock

import wc


class TestCountWords(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(wc.count_words(""), Counter())

    def test_lowercase(self):
        self.assertEqual(wc.count_words("The THE the"), Counter({"the": 3}))

    def test_punctuation(self):
        self.assertEqual(
            wc.count_words("hello, world! hello."),
            Counter({"hello": 2, "world": 1}),
        )


class _MainRunner:
    @staticmethod
    def run(stdin_text: str, argv: list[str]) -> tuple[int, str]:
        full_argv = ["wc.py"] + argv
        stdin = io.StringIO(stdin_text)
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", full_argv), \
             mock.patch.object(sys, "stdin", stdin), \
             mock.patch.object(sys, "stdout", stdout):
            rc = wc.main()
        return rc, stdout.getvalue()


class TestMainTextMode(unittest.TestCase):
    def test_sorted_output(self):
        rc, out = _MainRunner.run("the quick brown fox the lazy the\n", argv=[])
        self.assertEqual(rc, 0)
        self.assertEqual(
            out,
            "the: 3\nbrown: 1\nfox: 1\nlazy: 1\nquick: 1\n",
        )


class TestMainJsonMode(unittest.TestCase):
    def test_json_roundtrip(self):
        rc, out = _MainRunner.run(
            "the quick brown fox the lazy the\n", argv=["--json"]
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(out.strip())
        self.assertEqual(parsed, {"the": 3, "brown": 1, "fox": 1, "lazy": 1, "quick": 1})
        self.assertEqual(list(parsed.keys()), ["the", "brown", "fox", "lazy", "quick"])


if __name__ == "__main__":
    unittest.main()
