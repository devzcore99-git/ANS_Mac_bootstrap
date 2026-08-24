"""Minimal YAML frontmatter reader for SKILL.md files.

Uses PyYAML when available; otherwise falls back to a small parser that covers
the subset of YAML the Agent Skills spec allows in frontmatter:

    key: scalar
    key: "quoted scalar"
    key: >          (folded block scalar)
    key: |          (literal block scalar)
    key:            (nested one-level string map, e.g. `metadata:`)
      sub: value

Anything outside that subset raises FrontmatterError with a message telling the
caller how to simplify it. Shared by validate_skill.py and new_skill.py.
"""

from __future__ import annotations

try:  # pragma: no cover - depends on environment
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None


class FrontmatterError(Exception):
    """Raised when frontmatter is missing or cannot be parsed."""


def split(text: str) -> tuple[str, str]:
    """Split a SKILL.md into (frontmatter_text, body_text).

    Raises FrontmatterError if the file does not open with a `---` fence or the
    closing fence is missing.
    """
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError(
            "SKILL.md must begin with a YAML frontmatter fence. "
            "Expected the very first line to be exactly '---'."
        )
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise FrontmatterError(
        "Frontmatter is never closed. Add a line containing exactly '---' "
        "after the last frontmatter field."
    )


def parse(fm_text: str) -> dict:
    """Parse frontmatter text into a dict."""
    if _yaml is not None:
        try:
            data = _yaml.safe_load(fm_text)
        except Exception as exc:  # noqa: BLE001 - surface the YAML error verbatim
            raise FrontmatterError(f"Invalid YAML in frontmatter: {exc}") from exc
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise FrontmatterError(
                f"Frontmatter must be a mapping of fields, got {type(data).__name__}."
            )
        return data
    return _parse_fallback(fm_text)


def load(path) -> tuple[dict, str]:
    """Read a SKILL.md path and return (frontmatter_dict, body_text)."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    fm_text, body = split(text)
    return parse(fm_text), body


# --------------------------------------------------------------------------- #
# Fallback parser
# --------------------------------------------------------------------------- #

def _strip_comment(value: str) -> str:
    """Remove a trailing ` # comment` from an unquoted scalar."""
    out = []
    quote = None
    prev = ""
    for ch in value:
        if quote:
            if ch == quote and prev != "\\":
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (not out or out[-1] in (" ", "\t")):
            break
        out.append(ch)
        prev = ch
    return "".join(out).rstrip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        return inner.replace("''", "'")
    return value


def _dedent(lines: list[str]) -> list[str]:
    indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
    pad = min(indents) if indents else 0
    return [ln[pad:] if len(ln) >= pad else ln.lstrip() for ln in lines]


def _parse_fallback(fm_text: str) -> dict:
    lines = fm_text.split("\n")
    data: dict = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if raw[:1] in (" ", "\t"):
            raise FrontmatterError(
                f"Unexpected indentation at frontmatter line {i + 1}: {raw!r}. "
                "Only one level of nesting (e.g. under `metadata:`) is supported."
            )
        if stripped.startswith("- "):
            raise FrontmatterError(
                f"Top-level YAML lists are not valid frontmatter (line {i + 1})."
            )
        if ":" not in stripped:
            raise FrontmatterError(
                f"Frontmatter line {i + 1} is not a `key: value` pair: {raw!r}"
            )

        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()

        # Block scalar: `key: >` or `key: |` (with optional chomping indicator).
        if rest and rest[0] in ("|", ">") and rest.rstrip("+-0123456789") in ("|", ">"):
            fold = rest[0] == ">"
            block: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and not nxt[:1].isspace():
                    break
                block.append(nxt)
                i += 1
            while block and not block[-1].strip():
                block.pop()
            body_lines = _dedent(block)
            if fold:
                # Folded: blank lines become paragraph breaks, others join with a space.
                paragraphs, current = [], []
                for ln in body_lines:
                    if ln.strip():
                        current.append(ln.strip())
                    else:
                        paragraphs.append(" ".join(current))
                        current = []
                paragraphs.append(" ".join(current))
                data[key] = "\n".join(p for p in paragraphs).strip()
            else:
                data[key] = "\n".join(body_lines)
            continue

        # Nested one-level map: `key:` followed by indented `sub: value` lines.
        if rest == "":
            nested: dict = {}
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if not nxt[:1].isspace():
                    break
                sub = nxt.strip()
                if sub.startswith("#"):
                    i += 1
                    continue
                if sub.startswith("- "):
                    raise FrontmatterError(
                        f"Lists are not supported under `{key}:` (line {i + 1}). "
                        "Use a string map or a space-separated string."
                    )
                if ":" not in sub:
                    raise FrontmatterError(
                        f"Line {i + 1} under `{key}:` is not a `key: value` pair: {nxt!r}"
                    )
                sk, _, sv = sub.partition(":")
                nested[sk.strip()] = _unquote(_strip_comment(sv.strip()))
                i += 1
            # `key:` with no indented children is a null scalar, not an empty map.
            data[key] = nested if nested else None
            continue

        # Inline flow collections are legal YAML but not worth supporting here.
        if rest[0] in ("[", "{"):
            raise FrontmatterError(
                f"Inline collections are not supported for `{key}` (line {i + 1}). "
                "Write `metadata:` as an indented map, or use a plain string."
            )

        data[key] = _unquote(_strip_comment(rest))
        i += 1
    return data
