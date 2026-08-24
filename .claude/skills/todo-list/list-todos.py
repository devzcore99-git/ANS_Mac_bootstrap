#!/usr/bin/env python3
"""Render TODOs.md as a table on stdout.

The script does the parsing, counting, and formatting so the model can pass
the output straight through instead of reading the file and retyping every
item. Filters run here too, so a request for one section never pulls the
whole list into context.

Runs on Windows, macOS, and Linux. Python 3.7+, standard library only.

Usage:
  python3 list-todos.py                 # open items, grouped by section
  python3 list-todos.py --all           # include completed
  python3 list-todos.py --done          # completed only
  python3 list-todos.py --section stock # sections matching "stock" (substring, case-insensitive)
  python3 list-todos.py --counts        # section/status totals only
  python3 list-todos.py --json          # machine-readable
"""

import argparse
import json
import os
import re
import sys

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            os.pardir, os.pardir, os.pardir, "TODOs.md")

HEADING = re.compile(r"^##\s+(.*?)\s*$")
ITEM = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s*(.+?)\s*$")


def parse(path):
    """Return [{section, text, detail, done}] in file order."""
    items, section = [], "(none)"
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            h = HEADING.match(line)
            if h:
                section = h.group(1)
                continue
            m = ITEM.match(line)
            if m:
                # Items are written "Name - detail"; split so the table stays
                # narrow, but only on the first dash surrounded by spaces.
                text = m.group(2)
                name, _, detail = text.partition(" - ")
                items.append({
                    "section": section,
                    "text": name if detail else text,
                    "detail": detail,
                    "done": m.group(1).lower() == "x",
                })
    return items


def table(items, show_detail):
    """Markdown table, grouped by section in file order."""
    if not items:
        return "_No matching items._"
    out, seen, n = [], None, 0
    header = "| # | Item | Detail |" if show_detail else "| # | Item |"
    rule = "|---|---|---|" if show_detail else "|---|---|"
    for it in items:
        if it["section"] != seen:
            seen = it["section"]
            out += ["", f"**{seen}**", "", header, rule]
        n += 1
        mark = "~~" if it["done"] else ""
        cell = f"{mark}{it['text']}{mark}"
        out.append(f"| {n} | {cell} | {it['detail']} |" if show_detail
                   else f"| {n} | {cell} |")
    return "\n".join(out).lstrip("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--all", action="store_true", help="include completed items")
    ap.add_argument("--done", action="store_true", help="completed items only")
    ap.add_argument("--section", help="substring match on section name")
    ap.add_argument("--counts", action="store_true", help="totals only")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--detail", action="store_true",
                    help="add the Detail column (omitted by default to stay narrow)")
    args = ap.parse_args()

    path = os.path.normpath(args.file)
    if not os.path.isfile(path):
        print(f"TODO file not found: {path}", file=sys.stderr)
        return 2

    items = parse(path)
    total_open = sum(1 for i in items if not i["done"])
    total_done = len(items) - total_open

    sel = items
    if args.done:
        sel = [i for i in sel if i["done"]]
    elif not args.all:
        sel = [i for i in sel if not i["done"]]
    if args.section:
        needle = args.section.lower()
        sel = [i for i in sel if needle in i["section"].lower()]

    if args.json:
        json.dump({"file": path, "open": total_open, "done": total_done,
                   "items": sel}, sys.stdout, separators=(",", ":"))
        return 0

    if args.counts:
        # Scope by --section, but deliberately NOT by --done/--all: this table
        # has an Open and a Done column, so applying the status filter would
        # zero one of them. Iterating the unfiltered `items` was the bug —
        # `--counts --section stock` reported every section in the file.
        scoped = items
        if args.section:
            needle = args.section.lower()
            scoped = [i for i in scoped if needle in i["section"].lower()]
        per = {}
        for i in scoped:
            o, d = per.get(i["section"], (0, 0))
            per[i["section"]] = (o + (0 if i["done"] else 1), d + (1 if i["done"] else 0))
        print("| Section | Open | Done |")
        print("|---|---|---|")
        for s, (o, d) in per.items():
            print(f"| {s} | {o} | {d} |")
        scoped_open = sum(1 for i in scoped if not i["done"])
        scoped_done = len(scoped) - scoped_open
        # The summary follows the filter, so it can never contradict the table
        # above it. The whole-file figure is still shown when it differs, since
        # a filtered count with no denominator invites the wrong conclusion.
        summary = f"\n**{scoped_open} open · {scoped_done} completed**"
        if args.section and len(scoped) != len(items):
            summary += f" in sections matching '{args.section}'" \
                       f" · {total_open} open · {total_done} completed file-wide"
        print(summary)
        return 0

    print(table(sel, args.detail))
    print(f"\n**{total_open} open · {total_done} completed**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
