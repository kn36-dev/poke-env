"""Utility to convert exported (Showdown) team strings to packed team strings.

This reuses the project's Teambuilder parsing/formatting utilities so results
match how the library handles teams.

Usage (CLI):
  python -m scripts.convert_team path/to/team.txt
  echo "<team text>" | python -m scripts.convert_team

API:
  from scripts.convert_team import export_to_packed
  packed = export_to_packed(exported_team_string)
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from poke_env.teambuilder.teambuilder import Teambuilder


def export_to_packed(team_str: str) -> str:
    """Convert a Showdown export-format team to a packed-format string.

    If the input already looks like a packed team (contains ']' or is a one-line
    string containing '|' characters), the input is returned unchanged.

    This function relies on Teambuilder.parse_showdown_team and
    Teambuilder.join_team, so it supports the same export-format syntax as the
    project's teambuilder.
    """
    if not team_str:
        return ""

    s = team_str.strip()

    # Heuristics: packed teams normally contain ']' delimiters or are a single
    # line using '|' separators. If so, assume already packed.
    if "]" in s or ("\n" not in s and "|" in s):
        return s

    mons = Teambuilder.parse_showdown_team(s)
    return Teambuilder.join_team(mons)


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert exported team to packed team")
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to file containing exported team (or omit to read stdin)",
    )
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            content = fh.read()
    else:
        content = sys.stdin.read()

    packed = export_to_packed(content)
    print(packed)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
