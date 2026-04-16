#!/usr/bin/env python3
"""Minimal notes CLI. Appends a line to a notes file."""
import argparse
import re
import sys
from pathlib import Path

DEFAULT_NOTES_PATH = Path.home() / ".notes"


def add_note(text: str, notes_path: Path) -> None:
    """Append `text` as a new line to `notes_path`."""
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    with notes_path.open("a", encoding="utf-8") as f:
        f.write(text.rstrip("\n") + "\n")


def search_notes(notes_path: Path, query: str, regex: bool = False) -> list[tuple[int, str]]:
    """Return (line_number, line) pairs matching `query`. 1-indexed."""
    if not notes_path.exists():
        return []
    matches: list[tuple[int, str]] = []
    if regex:
        pattern = re.compile(query, re.IGNORECASE)
        check = lambda s: pattern.search(s) is not None
    else:
        q = query.lower()
        check = lambda s: q in s.lower()
    with notes_path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if check(line):
                matches.append((idx, line))
    return matches


def list_notes(notes_path: Path) -> list[tuple[int, str]]:
    """Return all notes as (line_number, line) pairs. 1-indexed."""
    if not notes_path.exists():
        return []
    with notes_path.open(encoding="utf-8") as f:
        return [(idx, line.rstrip("\n")) for idx, line in enumerate(f, start=1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes-path", type=Path, default=DEFAULT_NOTES_PATH)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="append a note")
    s.add_argument("text", help="note text")

    s = sub.add_parser("search", help="print notes matching a query")
    s.add_argument("query", help="substring (default) or regex pattern (--regex)")
    s.add_argument("--regex", action="store_true", help="treat query as a regex")

    s = sub.add_parser("list", help="print all notes with line numbers")

    args = parser.parse_args()

    if args.cmd == "add":
        add_note(args.text, args.notes_path)
        return 0
    if args.cmd == "search":
        for n, line in search_notes(args.notes_path, args.query, args.regex):
            print(f"{n}: {line}")
        return 0
    if args.cmd == "list":
        for n, line in list_notes(args.notes_path):
            print(f"{n}: {line}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
