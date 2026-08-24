#!/usr/bin/env python3
"""Save and retrieve built prompts under ASST_BBMax/prompts/.

Reads the prompt body from stdin so a finished prompt never has to be retyped
into a Write call. Stores it in a fenced block with the rationale in
frontmatter, keeping the copy-paste payload cleanly separated from the notes.

Runs on Windows, macOS, and Linux. Python 3.7+, standard library only.

Usage:
  python3 prompt.py --save "Weekly Report" --why "..." < prompt.txt
  python3 prompt.py --list
  python3 prompt.py --show weekly-report          # prompt body only
  python3 prompt.py --show weekly-report --full   # with rationale
"""

import argparse
import os
import re
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.normpath(os.path.join(SKILL_DIR, os.pardir, os.pardir,
                                            os.pardir, "prompts"))
FENCE = "``````"  # 6 backticks, so a prompt containing ``` blocks survives


def slugify(name):
    return re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower() or "untitled"


def cmd_save(name, why, created, force=False):
    body = sys.stdin.read().strip()
    if not body:
        print("nothing on stdin", file=sys.stderr)
        return 2
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    dest = os.path.join(PROMPTS_DIR, f"{slugify(name)}.md")
    # Names that differ only in case or punctuation slugify to one file, so
    # "Weekly Report" would silently overwrite "weekly-report". prompts/ is
    # committed only occasionally, so there is often no history to recover
    # from. Mirrors prd.py's cmd_new, which refuses with exit 3.
    if os.path.exists(dest) and not force:
        print(f"already exists: {dest}\n"
              f"Pass --force to overwrite, or save under a different name.",
              file=sys.stderr)
        return 3
    parts = [f"# {name}", ""]
    if created:
        parts += [f"_Created {created}_", ""]
    parts += ["## Prompt", "", FENCE, body, FENCE, ""]
    if why:
        parts += ["## Why it works", "", why, ""]
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    print(dest)
    return 0


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def extract(text):
    """Return the prompt body from between the outer fences."""
    parts = text.split(FENCE)
    return parts[1].strip() if len(parts) >= 3 else text.strip()


def cmd_list():
    if not os.path.isdir(PROMPTS_DIR):
        print("No prompts yet.")
        return 0
    rows = sorted(f for f in os.listdir(PROMPTS_DIR) if f.endswith(".md"))
    if not rows:
        print("No prompts yet.")
        return 0
    print("| Prompt | Slug | Lines |")
    print("|---|---|---|")
    for fn in rows:
        # Read once, not twice, and tolerate a zero-byte .md: indexing
        # splitlines()[0] on one used to raise IndexError and take down the
        # whole listing rather than skipping the single bad file.
        text = read(os.path.join(PROMPTS_DIR, fn))
        body = extract(text)
        lines = text.splitlines()
        title = fn[:-3]
        if lines and lines[0].startswith("# "):
            title = lines[0][2:].strip()
        print(f"| {title} | {fn[:-3]} | {len(body.splitlines())} |")
    return 0


def cmd_show(slug, full):
    cand = slug if slug.endswith(".md") else f"{slugify(slug)}.md"
    path = os.path.join(PROMPTS_DIR, cand)
    if not os.path.isfile(path):
        print(f"not found: {path}", file=sys.stderr)
        return 2
    text = read(path)
    print(text if full else extract(text))
    return 0


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save", metavar="NAME")
    g.add_argument("--list", action="store_true")
    g.add_argument("--show", metavar="SLUG")
    ap.add_argument("--why", default="", help="rationale, stored below the prompt")
    ap.add_argument("--created", default="", help="date stamp, e.g. 2026-07-28")
    ap.add_argument("--full", action="store_true", help="with --show: include rationale")
    ap.add_argument("--force", action="store_true",
                    help="with --save: overwrite an existing prompt of the same slug")
    args = ap.parse_args()

    if args.save:
        return cmd_save(args.save, args.why, args.created, args.force)
    if args.list:
        return cmd_list()
    return cmd_show(args.show, args.full)


if __name__ == "__main__":
    sys.exit(main())
