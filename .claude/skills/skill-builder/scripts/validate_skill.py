#!/usr/bin/env python3
"""Validate an Agent Skill against the agentskills.io specification.

Checks frontmatter fields and constraints, directory conventions, body size
budgets, and whether relative file references actually resolve. Reports errors
(spec violations) and warnings (quality signals) separately.

Usage:
  validate_skill.py SKILL_DIR [SKILL_DIR ...]   Validate one or more skills
  validate_skill.py --all DIR                   Validate every skill under DIR

Options:
  --json          Emit machine-readable JSON to stdout instead of text
  --strict        Treat warnings as errors (exit 1 if any warning fires)
  --quiet         Only print skills that have findings
  -h, --help      Show this message

Exit codes:
  0  All skills valid (no errors; no warnings when --strict)
  1  At least one spec violation (or warning under --strict)
  2  Usage error, or a path that does not exist / contains no skill
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontmatter import FrontmatterError, load  # noqa: E402

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
BODY_LINE_BUDGET = 500
BODY_TOKEN_BUDGET = 5000

KNOWN_FIELDS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}
REQUIRED_FIELDS = ("name", "description")

# Markdown links and bare paths pointing into the skill's own subdirectories.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
PATH_RE = re.compile(r"(?<![\w./-])((?:scripts|references|assets)/[\w.\-/]+\.[\w]+)")
# The same paths written through the $SKILL_DIR convention these skills use for
# their run commands. PATH_RE cannot see them: its lookbehind rejects a
# preceding "/", so `$SKILL_DIR/scripts/foo.py` matched nothing and a skill was
# told its own scripts were unreferenced dead weight. The variable must be
# followed *immediately* by the subdirectory — `$SKILL_DIR/../other/scripts/x.py`
# addresses a different skill and must keep not matching, or the existence check
# below would look for another skill's file in this one.
PATH_VAR_RE = re.compile(
    r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/((?:scripts|references|assets)/[\w.\-/]+\.[\w]+)")

TRIGGER_HINTS = ("use when", "use this", "when the user", "when you", "for when", "invoke when")

IGNORED_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv"}

# Scaffold placeholders look exactly like bare HTML tags (`<action>`), so shape
# alone cannot separate them. Real markup in a SKILL.md body is rare and comes
# from a small set of tags; everything else in angle brackets is treated as an
# unreplaced placeholder.
FENCE_RE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
CODE_FENCE_BLOCK_RE = re.compile(r"(?ms)^\s*(```|~~~).*?^\s*\1[ \t]*$")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
PLACEHOLDER_RE = re.compile(r"<([^<>\n]{1,80})>")
HTML_TAGS = {
    "a", "b", "br", "code", "details", "div", "em", "hr", "i", "img", "kbd",
    "li", "ol", "p", "pre", "span", "strong", "sub", "summary", "sup",
    "table", "td", "th", "tr", "ul",
    "h1", "h2", "h3", "h4", "h5", "h6",
}


class Report:
    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(os.path.abspath(path))
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.stats: dict = {}

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def as_dict(self) -> dict:
        return {
            "skill": self.name,
            "path": self.path,
            "valid": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


def _check_name(rep: Report, name, dirname: str) -> None:
    if not isinstance(name, str):
        rep.error(f"`name` must be a string, got {type(name).__name__}.")
        return
    if not name:
        rep.error("`name` is empty. It must be 1-64 characters.")
        return
    if len(name) > NAME_MAX:
        rep.error(f"`name` is {len(name)} characters; the maximum is {NAME_MAX}.")
    if not NAME_RE.match(name):
        reasons = []
        if name != name.lower():
            reasons.append("uppercase letters are not allowed")
        if name.startswith("-") or name.endswith("-"):
            reasons.append("it must not start or end with a hyphen")
        if "--" in name:
            reasons.append("consecutive hyphens are not allowed")
        if re.search(r"[^a-z0-9-]", name):
            bad = sorted(set(re.findall(r"[^a-z0-9-]", name)))
            reasons.append(f"illegal character(s): {' '.join(repr(c) for c in bad)}")
        detail = "; ".join(reasons) or "it must match ^[a-z0-9]+(-[a-z0-9]+)*$"
        rep.error(f"`name` {name!r} is invalid: {detail}.")
    if name != dirname:
        rep.error(
            f"`name` is {name!r} but the parent directory is {dirname!r}. "
            "They must match exactly."
        )


def _check_description(rep: Report, desc) -> None:
    if not isinstance(desc, str):
        rep.error(f"`description` must be a string, got {type(desc).__name__}.")
        return
    text = desc.strip()
    if not text:
        rep.error("`description` is empty. It must describe what the skill does and when to use it.")
        return
    if len(desc) > DESCRIPTION_MAX:
        rep.error(
            f"`description` is {len(desc)} characters; the maximum is {DESCRIPTION_MAX}."
        )
    if len(text) < 40:
        rep.warn(
            f"`description` is only {len(text)} characters. Short descriptions trigger "
            "unreliably — state what the skill does AND when to use it."
        )
    lowered = text.lower()
    if not any(hint in lowered for hint in TRIGGER_HINTS):
        rep.warn(
            "`description` has no explicit trigger clause. Add a 'Use when ...' sentence "
            "naming the situations that should activate this skill."
        )


def _empty(rep: Report, field: str, value) -> bool:
    """Report and return True when a present field carries no value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        rep.error(f"`{field}` is present but empty. Give it a value or remove the field.")
        return True
    return False


def _check_optional_fields(rep: Report, fm: dict) -> None:
    if "compatibility" in fm:
        compat = fm["compatibility"]
        if not _empty(rep, "compatibility", compat):
            if not isinstance(compat, str):
                rep.error(f"`compatibility` must be a string, got {type(compat).__name__}.")
            elif len(compat) > COMPATIBILITY_MAX:
                rep.error(
                    f"`compatibility` is {len(compat)} characters; "
                    f"the maximum is {COMPATIBILITY_MAX}."
                )

    if "license" in fm:
        lic = fm["license"]
        if not _empty(rep, "license", lic) and not isinstance(lic, str):
            rep.error(f"`license` must be a string, got {type(lic).__name__}.")

    if "metadata" in fm:
        meta = fm["metadata"]
        if not _empty(rep, "metadata", meta):
            if not isinstance(meta, dict):
                rep.error(
                    "`metadata` must be a map of string keys to string values, "
                    f"got {type(meta).__name__}."
                )
            else:
                for key, value in meta.items():
                    if not isinstance(value, (str, int, float, bool)):
                        rep.error(
                            f"`metadata.{key}` must be a scalar value, "
                            f"got {type(value).__name__}."
                        )

    if "allowed-tools" in fm:
        tools = fm["allowed-tools"]
        if not _empty(rep, "allowed-tools", tools):
            if not isinstance(tools, str):
                rep.error(
                    f"`allowed-tools` must be a space-separated string, "
                    f"got {type(tools).__name__}."
                )
            elif "," in tools:
                rep.warn("`allowed-tools` is space-separated, not comma-separated.")

    for key in fm:
        if key not in KNOWN_FIELDS:
            rep.warn(
                f"`{key}` is not a field in the Agent Skills spec. Clients ignore unknown "
                "fields — put custom data under `metadata:` instead."
            )


def _check_body(rep: Report, body: str) -> None:
    text = body.strip()
    lines = body.strip("\n").split("\n") if text else []
    tokens = len(body) // 4
    rep.stats["body_lines"] = len(lines)
    rep.stats["body_chars"] = len(body)
    rep.stats["body_tokens_estimate"] = tokens

    if not text:
        rep.error(
            "SKILL.md has no body. Frontmatter alone tells the agent when to activate "
            "the skill but not how to do the task."
        )
        return
    if len(lines) > BODY_LINE_BUDGET:
        rep.warn(
            f"SKILL.md body is {len(lines)} lines; the recommended budget is {BODY_LINE_BUDGET}. "
            "Move detail into references/ and tell the agent when to read each file."
        )
    if tokens > BODY_TOKEN_BUDGET:
        rep.warn(
            f"SKILL.md body is ~{tokens} tokens; the recommended budget is {BODY_TOKEN_BUDGET}. "
            "Every token competes with the conversation for the agent's attention."
        )


def _check_placeholders(rep: Report, body: str) -> None:
    """Flag scaffold placeholders left in prose.

    Angle brackets inside code fences and inline code are documentation of
    command syntax (`--out-dir <dir>`) and are left alone; a bare `<action>` in
    a sentence or a list item is a skeleton nobody finished. That distinction
    is what makes this checkable at all — see the templates, where every
    placeholder sits in prose.
    """
    prose = CODE_FENCE_BLOCK_RE.sub("", body)
    prose = INLINE_CODE_RE.sub("", prose)

    found: list[str] = []
    for match in PLACEHOLDER_RE.finditer(prose):
        inner = match.group(1).strip()
        if not inner or not any(ch.isalpha() for ch in inner):
            continue
        # Markdown autolinks: <https://example.com>, <user@example.com>.
        if "://" in inner or inner.startswith("mailto:") or "@" in inner.split()[0]:
            continue
        # Real markup, opening or closing, with or without attributes.
        tag = inner.lstrip("/").split()[0].rstrip("/").lower()
        if tag in HTML_TAGS:
            continue
        text = f"<{inner}>"
        if text not in found:
            found.append(text)

    if found:
        shown = ", ".join(found[:5])
        more = f" (and {len(found) - 5} more)" if len(found) > 5 else ""
        rep.error(
            f"{len(found)} unreplaced placeholder(s) in the body: {shown}{more}. "
            "Replace or delete every one — a shipped skill containing skeleton "
            "text is worse than no skill. Placeholders inside code fences or "
            "`backticks` are treated as command syntax and ignored."
        )


def _check_references(rep: Report, body: str, skill_dir: str) -> None:
    candidates: set[str] = set()
    for match in LINK_RE.finditer(body):
        target = match.group(1)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(("#", "/")):
            continue
        candidates.add(target.split("#", 1)[0])
    for match in PATH_RE.finditer(body):
        candidates.add(match.group(1))
    for match in PATH_VAR_RE.finditer(body):
        candidates.add(match.group(1))

    missing = sorted(
        target
        for target in candidates
        if target and not os.path.exists(os.path.join(skill_dir, target))
    )
    rep.stats["referenced_files"] = len(candidates)
    for target in missing:
        rep.error(f"SKILL.md references `{target}`, which does not exist in the skill directory.")

    # Unreferenced bundled files are dead weight the agent will never load.
    for subdir in ("scripts", "references", "assets"):
        root = os.path.join(skill_dir, subdir)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
            for filename in filenames:
                if filename.startswith(".") or filename.endswith((".pyc", ".pyo")):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, filename), skill_dir)
                if rel not in candidates and rel.replace(os.sep, "/") not in candidates:
                    rep.warn(
                        f"`{rel}` is bundled but never referenced from SKILL.md. "
                        "The agent will not know it exists."
                    )


def _check_layout(rep: Report, skill_dir: str) -> None:
    for entry in sorted(os.listdir(skill_dir)):
        full = os.path.join(skill_dir, entry)
        if os.path.isdir(full) and entry.lower() in ("script", "reference", "asset"):
            rep.warn(
                f"Directory `{entry}/` is misnamed. The conventional names are "
                "`scripts/`, `references/`, and `assets/`."
            )
    scripts_dir = os.path.join(skill_dir, "scripts")
    if os.path.isdir(scripts_dir):
        for filename in sorted(os.listdir(scripts_dir)):
            if filename.endswith(".sh"):
                path = os.path.join(scripts_dir, filename)
                if os.path.isfile(path) and not os.access(path, os.X_OK):
                    rep.warn(
                        f"`scripts/{filename}` is not executable. Either `chmod +x` it or "
                        "invoke it as `bash scripts/{0}` in SKILL.md.".format(filename)
                    )


def validate(skill_dir: str) -> Report:
    skill_dir = os.path.abspath(skill_dir)
    rep = Report(skill_dir)

    if not os.path.isdir(skill_dir):
        rep.error(f"{skill_dir} is not a directory.")
        return rep

    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        for entry in os.listdir(skill_dir):
            if entry.lower() == "skill.md":
                rep.error(
                    f"Found `{entry}` but the file must be named exactly `SKILL.md` (uppercase)."
                )
                return rep
        rep.error("No SKILL.md found. Every skill directory must contain one.")
        return rep

    try:
        fm, body = load(skill_md)
    except FrontmatterError as exc:
        rep.error(str(exc))
        return rep
    except UnicodeDecodeError as exc:
        rep.error(f"SKILL.md is not valid UTF-8: {exc}")
        return rep

    for field in REQUIRED_FIELDS:
        if field not in fm:
            rep.error(f"Required frontmatter field `{field}` is missing.")

    if "name" in fm:
        _check_name(rep, fm["name"], os.path.basename(skill_dir))
    if "description" in fm:
        _check_description(rep, fm["description"])
        if isinstance(fm["description"], str):
            rep.stats["description_chars"] = len(fm["description"])

    _check_optional_fields(rep, fm)
    _check_body(rep, body)
    _check_placeholders(rep, body)
    _check_references(rep, body, skill_dir)
    _check_layout(rep, skill_dir)
    return rep


def discover(root: str) -> list[str]:
    """Find every directory under root that contains a SKILL.md."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
        if "SKILL.md" in filenames:
            found.append(dirpath)
            dirnames[:] = []
    return sorted(found)


def render_text(reports: list[Report], quiet: bool) -> str:
    out = []
    for rep in reports:
        if quiet and not rep.errors and not rep.warnings:
            continue
        status = "FAIL" if rep.errors else ("WARN" if rep.warnings else "OK")
        out.append(f"[{status}] {rep.name}  ({rep.path})")
        for msg in rep.errors:
            out.append(f"  error:   {msg}")
        for msg in rep.warnings:
            out.append(f"  warning: {msg}")
        if rep.stats:
            bits = [f"{k}={v}" for k, v in rep.stats.items()]
            out.append(f"  stats:   {', '.join(bits)}")
        out.append("")
    total = len(reports)
    failed = sum(1 for r in reports if r.errors)
    warned = sum(1 for r in reports if r.warnings and not r.errors)
    out.append(f"{total} skill(s): {total - failed - warned} clean, {warned} with warnings, {failed} failing")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0 if args else 2

    as_json = "--json" in args
    strict = "--strict" in args
    quiet = "--quiet" in args
    use_all = "--all" in args
    paths = [a for a in args if not a.startswith("-")]

    unknown = [a for a in args if a.startswith("-") and a not in
               ("--json", "--strict", "--quiet", "--all")]
    if unknown:
        print(f"Error: unknown option(s): {' '.join(unknown)}", file=sys.stderr)
        print("Run with --help for usage.", file=sys.stderr)
        return 2

    if not paths:
        print("Error: no SKILL_DIR given.", file=sys.stderr)
        print("Usage: validate_skill.py SKILL_DIR [SKILL_DIR ...] | --all DIR", file=sys.stderr)
        return 2

    targets: list[str] = []
    for path in paths:
        if not os.path.exists(path):
            print(f"Error: path does not exist: {path}", file=sys.stderr)
            return 2
        if use_all:
            found = discover(path)
            if not found:
                print(f"Error: no SKILL.md found anywhere under {path}", file=sys.stderr)
                return 2
            targets.extend(found)
        else:
            targets.append(path)

    reports = [validate(t) for t in targets]

    if as_json:
        payload = {
            "skills": [r.as_dict() for r in reports],
            "summary": {
                "total": len(reports),
                "failing": sum(1 for r in reports if r.errors),
                "with_warnings": sum(1 for r in reports if r.warnings),
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render_text(reports, quiet))

    if any(r.errors for r in reports):
        return 1
    if strict and any(r.warnings for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
