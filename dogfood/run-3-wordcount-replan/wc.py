#!/usr/bin/env python3
"""Word frequency counter. Reads text from stdin, prints word: count per line."""
import argparse
import json
import re
import sys
from collections import Counter


def count_words(text: str) -> Counter:
    """Return a Counter of lowercased word tokens in `text`."""
    return Counter(re.findall(r"\w+", text.lower()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON dict instead of text")
    args = parser.parse_args()
    counts = count_words(sys.stdin.read())
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    if args.json:
        print(json.dumps(ordered, ensure_ascii=False))
    else:
        for word, n in ordered.items():
            print(f"{word}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
