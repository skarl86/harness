#!/usr/bin/env python3
"""Decode URL-encoded strings from stdin."""
import sys
import argparse
import json
import urllib.parse


def decode_line(line: str) -> str:
    return urllib.parse.unquote(line.rstrip("\n"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit {input, decoded} per line")
    args = parser.parse_args()

    for line in sys.stdin:
        stripped = line.rstrip("\n")
        if not stripped.strip():
            continue
        decoded = decode_line(line)
        if args.json:
            print(json.dumps({"input": stripped, "decoded": decoded}, ensure_ascii=False))
        else:
            print(decoded)

    return 0


if __name__ == "__main__":
    sys.exit(main())
