#!/usr/bin/env python3
"""Create, list, and inspect PRD drafts under ASST_BBMax/plans/.

Copying the template and computing progress here keeps the model from
retyping a 300-line skeleton, and makes an interrupted interview resumable:
`--status` reports exactly which sections are still unanswered.

Runs on Windows, macOS, and Linux. Python 3.7+, standard library only.

Usage:
  python3 prd.py --new "Stock News Puller"
  python3 prd.py --list
  python3 prd.py --status stock-news-puller
  python3 prd.py --next   stock-news-puller     # first unfilled section
"""

import argparse
import os
import re
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(SKILL_DIR, "prd-template.md")
PLANS_DIR = os.path.normpath(os.path.join(SKILL_DIR, os.pardir, os.pardir,
                                          os.pardir, "plans"))

H2 = re.compile(r"^##\s+(.*?)\s*$")
# An unanswered line is a placeholder in <angle brackets>, or a "- Label:" /
# "- Label" prompt with nothing written after it.
PLACEHOLDER = re.compile(r"<[^>]+>")
EMPTY_FIELD = re.compile(r"^\s*[-*]\s+[^:]+:\s*$")


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s or "untitled"


def sections(path):
    """Return [(title, unanswered_line_count, total_prompt_lines)] in order."""
    out, title, unanswered, prompts = [], None, 0, 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            h = H2.match(line)
            if h:
                if title is not None:
                    out.append((title, unanswered, prompts))
                title, unanswered, prompts = h.group(1), 0, 0
                continue
            if title is None:
                continue
            if PLACEHOLDER.search(line) or EMPTY_FIELD.match(line):
                unanswered += 1
                prompts += 1
            elif re.match(r"^\s*[-*]\s+\S+.*:\s+\S", line):
                prompts += 1
    if title is not None:
        out.append((title, unanswered, prompts))
    return out


def cmd_new(name):
    if not os.path.isfile(TEMPLATE):
        print(f"template missing: {TEMPLATE}", file=sys.stderr)
        return 2
    os.makedirs(PLANS_DIR, exist_ok=True)
    dest = os.path.join(PLANS_DIR, f"{slugify(name)}-PRD.md")
    if os.path.exists(dest):
        print(f"already exists: {dest}\nUse --status to resume it.", file=sys.stderr)
        return 3
    with open(TEMPLATE, encoding="utf-8") as src:
        body = src.read()
    body = body.replace("<Clear, short name>", name)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(dest)
    return 0


def cmd_list():
    if not os.path.isdir(PLANS_DIR):
        print("No PRDs yet. Create one with --new \"<name>\".")
        return 0
    rows = sorted(f for f in os.listdir(PLANS_DIR) if f.endswith("-PRD.md"))
    if not rows:
        print("No PRDs yet. Create one with --new \"<name>\".")
        return 0
    print("| PRD | Sections done | Unanswered lines |")
    print("|---|---|---|")
    for fn in rows:
        secs = sections(os.path.join(PLANS_DIR, fn))
        done = sum(1 for _, u, _ in secs if u == 0)
        print(f"| {fn[:-7]} | {done}/{len(secs)} | {sum(u for _, u, _ in secs)} |")
    return 0


def resolve(slug):
    cand = slug if slug.endswith("-PRD.md") else f"{slugify(slug)}-PRD.md"
    path = os.path.join(PLANS_DIR, cand)
    if not os.path.isfile(path):
        print(f"not found: {path}", file=sys.stderr)
        return None
    return path


def cmd_status(slug):
    path = resolve(slug)
    if not path:
        return 2
    print(f"**{os.path.basename(path)}**\n")
    print("| Section | Status | Unanswered |")
    print("|---|---|---|")
    for title, unanswered, _ in sections(path):
        mark = "done" if unanswered == 0 else "open"
        print(f"| {title} | {mark} | {unanswered} |")
    return 0


def cmd_next(slug):
    path = resolve(slug)
    if not path:
        return 2
    for title, unanswered, _ in sections(path):
        if unanswered:
            print(title)
            return 0
    print("COMPLETE")
    return 0


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--new", metavar="NAME")
    g.add_argument("--list", action="store_true")
    g.add_argument("--status", metavar="SLUG")
    g.add_argument("--next", metavar="SLUG")
    args = ap.parse_args()

    if args.new:
        return cmd_new(args.new)
    if args.list:
        return cmd_list()
    if args.status:
        return cmd_status(args.status)
    return cmd_next(args.next)


if __name__ == "__main__":
    sys.exit(main())
