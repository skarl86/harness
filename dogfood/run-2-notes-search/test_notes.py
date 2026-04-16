"""Unit tests for notes.py."""
import tempfile
import unittest
from pathlib import Path

import notes


class TestAddNote(unittest.TestCase):
    def test_appends_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.notes"
            notes.add_note("hello", p)
            notes.add_note("world", p)
            self.assertEqual(p.read_text(), "hello\nworld\n")

    def test_strips_trailing_newline(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.notes"
            notes.add_note("trailing\n", p)
            self.assertEqual(p.read_text(), "trailing\n")


class TestSearch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "x.notes"
        self.p.write_text(
            "apple\n"
            "banana\n"
            "Apple pie\n"
            "grape\n"
            "APPLE JUICE\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_plain_substring_case_insensitive(self):
        hits = notes.search_notes(self.p, "apple")
        self.assertEqual([n for n, _ in hits], [1, 3, 5])

    def test_regex_mode(self):
        hits = notes.search_notes(self.p, r"^ap", regex=True)
        # Case-insensitive: matches "apple" (line 1), "Apple pie" (3), "APPLE JUICE" (5)
        self.assertEqual([n for n, _ in hits], [1, 3, 5])

    def test_missing_file_returns_empty(self):
        missing = Path(self._tmp.name) / "does_not_exist.notes"
        self.assertEqual(notes.search_notes(missing, "whatever"), [])


class TestList(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "x.notes"

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_all(self):
        self.p.write_text("a\nb\nc\n", encoding="utf-8")
        self.assertEqual(notes.list_notes(self.p), [(1, "a"), (2, "b"), (3, "c")])

    def test_missing_file_returns_empty(self):
        missing = Path(self._tmp.name) / "does_not_exist.notes"
        self.assertEqual(notes.list_notes(missing), [])


if __name__ == "__main__":
    unittest.main()
