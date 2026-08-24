#!/usr/bin/env python3
"""Scaffold a new Agent Skill directory from an archetype template.

Creates <out-dir>/<name>/SKILL.md with valid frontmatter plus the subdirectories
the chosen archetype uses. The generated SKILL.md is a skeleton: it contains
`<angle-bracket>` placeholders that you must replace with real, task-specific
content before the skill is worth anything.

Usage:
  new_skill.py --name NAME --description TEXT [options]

Required:
  --name NAME            Skill name. Lowercase letters, digits and single
                         hyphens only; 1-64 chars; no leading/trailing hyphen.
  --description TEXT     What the skill does and when to use it (max 1024
                         chars). Include an explicit "Use when ..." clause.

Options:
  --template NAME        Archetype to scaffold (default: minimal). One of:
                           minimal   Plain instructions, no bundled files
                           workflow  Ordered procedure with a checklist
                           reference Knowledge-heavy, uses references/
                           script    Script-driven, plan-validate-execute
                           review    Rubric / judgement-based guidance
  --out-dir DIR          Parent directory for the skill (default: skills)
  --compatibility TEXT   Environment requirements (max 500 chars). Omit unless
                         the skill genuinely needs specific tooling.
  --license TEXT         License name or bundled license filename
  --with-evals           Also create evals/evals.json from the eval template
  --force                Overwrite an existing skill directory
  --dry-run              Print what would be created without writing anything
  --json                 Emit machine-readable JSON to stdout
  -h, --help             Show this message

Examples:
  new_skill.py --name pdf-forms --description "Fill and validate PDF forms. Use when the user has a fillable PDF." --template script
  new_skill.py --name api-review --description "Review REST API changes against our conventions. Use when reviewing endpoint diffs." --template review --with-evals

Exit codes:
  0  Skill created (or dry run completed)
  1  Invalid argument value (bad name, oversized description, unknown template)
  2  Usage error, or destination exists without --force
"""

from __future__ import annotations

import json
import os
import re
import sys

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(os.path.dirname(HERE), "assets", "templates")

# Archetype -> subdirectories to create, and extra template files to copy in as
# (template filename, destination path relative to the skill root).
ARCHETYPE_DIRS = {
    "minimal": [],
    "workflow": [],
    "reference": ["references"],
    "script": ["scripts"],
    "review": ["references"],
}
ARCHETYPE_FILES = {
    "reference": [("reference-doc.md", "references/REFERENCE.md")],
}


def die(msg: str, code: int) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    if code == 2:
        print("Run with --help for usage.", file=sys.stderr)
    return code


def title_case(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split("-"))


def validate_name(name: str) -> str | None:
    if not name:
        return "--name is empty."
    if len(name) > NAME_MAX:
        return f"--name is {len(name)} characters; the maximum is {NAME_MAX}."
    if not NAME_RE.match(name):
        reasons = []
        if name != name.lower():
            reasons.append("uppercase letters are not allowed")
        if name.startswith("-") or name.endswith("-"):
            reasons.append("it must not start or end with a hyphen")
        if "--" in name:
            reasons.append("consecutive hyphens are not allowed")
        bad = sorted(set(re.findall(r"[^a-z0-9-]", name)))
        if bad:
            reasons.append(f"illegal character(s): {' '.join(repr(c) for c in bad)}")
        detail = "; ".join(reasons) or "it must match ^[a-z0-9]+(-[a-z0-9]+)*$"
        suggestion = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")
        hint = f" Try --name {suggestion}" if suggestion and NAME_RE.match(suggestion) else ""
        return f"--name {name!r} is invalid: {detail}.{hint}"
    return None


def parse_args(argv: list[str]) -> tuple[dict | None, int]:
    opts = {
        "name": None,
        "description": None,
        "template": "minimal",
        "out_dir": "skills",
        "compatibility": None,
        "license": None,
        "with_evals": False,
        "force": False,
        "dry_run": False,
        "json": False,
    }
    flags = {
        "--name": "name",
        "--description": "description",
        "--template": "template",
        "--out-dir": "out_dir",
        "--compatibility": "compatibility",
        "--license": "license",
    }
    switches = {
        "--with-evals": "with_evals",
        "--force": "force",
        "--dry-run": "dry_run",
        "--json": "json",
    }

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in flags:
            if i + 1 >= len(argv):
                return None, die(f"{arg} requires a value.", 2)
            opts[flags[arg]] = argv[i + 1]
            i += 2
        elif "=" in arg and arg.split("=", 1)[0] in flags:
            key, value = arg.split("=", 1)
            opts[flags[key]] = value
            i += 1
        elif arg in switches:
            opts[switches[arg]] = True
            i += 1
        else:
            return None, die(f"unknown argument: {arg}", 2)
    return opts, 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0 if args else 2

    opts, code = parse_args(args)
    if opts is None:
        return code

    if not opts["name"]:
        return die("--name is required.", 2)
    if not opts["description"]:
        return die("--description is required.", 2)

    problem = validate_name(opts["name"])
    if problem:
        return die(problem, 1)

    description = opts["description"].strip()
    if len(description) > DESCRIPTION_MAX:
        return die(
            f"--description is {len(description)} characters; the maximum is {DESCRIPTION_MAX}.", 1
        )
    if opts["compatibility"] and len(opts["compatibility"]) > COMPATIBILITY_MAX:
        return die(
            f"--compatibility is {len(opts['compatibility'])} characters; "
            f"the maximum is {COMPATIBILITY_MAX}.",
            1,
        )

    template = opts["template"]
    if template not in ARCHETYPE_DIRS:
        return die(
            f"unknown --template {template!r}. Choose one of: "
            f"{', '.join(sorted(ARCHETYPE_DIRS))}.",
            1,
        )

    template_path = os.path.join(TEMPLATE_DIR, f"{template}.md")
    if not os.path.isfile(template_path):
        return die(f"template file missing: {template_path}", 1)

    skill_dir = os.path.join(opts["out_dir"], opts["name"])
    if os.path.exists(skill_dir) and not opts["force"]:
        return die(
            f"{skill_dir} already exists. Pass --force to overwrite, or pick another --name.", 2
        )

    with open(template_path, "r", encoding="utf-8") as handle:
        body = handle.read()

    extra_fm = ""
    if opts["license"]:
        extra_fm += f"license: {opts['license']}\n"
    if opts["compatibility"]:
        extra_fm += f"compatibility: {opts['compatibility']}\n"

    content = (
        body.replace("{{NAME}}", opts["name"])
        .replace("{{DESCRIPTION}}", yaml_scalar(description))
        .replace("{{TITLE}}", title_case(opts["name"]))
        .replace("{{EXTRA_FRONTMATTER}}", extra_fm)
    )

    extra_files = list(ARCHETYPE_FILES.get(template, []))
    created = [os.path.join(skill_dir, "SKILL.md")]
    created += [os.path.join(skill_dir, dest) for _, dest in extra_files]
    dirs = [skill_dir] + [os.path.join(skill_dir, d) for d in ARCHETYPE_DIRS[template]]
    if opts["with_evals"]:
        dirs.append(os.path.join(skill_dir, "evals"))
        created.append(os.path.join(skill_dir, "evals", "evals.json"))

    if opts["dry_run"]:
        result = {"dry_run": True, "skill_dir": skill_dir, "would_create": created}
        print(json.dumps(result, indent=2) if opts["json"] else
              "Would create:\n  " + "\n  ".join(created))
        return 0

    for directory in dirs:
        os.makedirs(directory, exist_ok=True)

    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write(content)

    for source, dest in extra_files:
        with open(os.path.join(TEMPLATE_DIR, source), "r", encoding="utf-8") as handle:
            extra = handle.read()
        with open(os.path.join(skill_dir, dest), "w", encoding="utf-8") as handle:
            handle.write(extra.replace("{{NAME}}", opts["name"]).replace("{{TITLE}}", title_case(opts["name"])))

    if opts["with_evals"]:
        eval_template = os.path.join(TEMPLATE_DIR, "evals.json")
        with open(eval_template, "r", encoding="utf-8") as handle:
            eval_content = handle.read().replace("{{NAME}}", opts["name"])
        with open(os.path.join(skill_dir, "evals", "evals.json"), "w", encoding="utf-8") as handle:
            handle.write(eval_content)

    validator = os.path.relpath(os.path.join(HERE, "validate_skill.py"))
    result = {
        "skill_dir": skill_dir,
        "template": template,
        "created": created,
        "next_steps": [
            f"Replace every <angle-bracket> placeholder in {skill_dir}/SKILL.md",
            f"python3 {validator} {skill_dir}",
        ],
    }
    if opts["json"]:
        print(json.dumps(result, indent=2))
    else:
        print(f"Created {template} skill at {skill_dir}")
        for path in created:
            print(f"  {path}")
        print("\nNext:")
        for step in result["next_steps"]:
            print(f"  - {step}")
    return 0


def yaml_scalar(text: str) -> str:
    """Render a description safely as a YAML frontmatter value.

    Multi-line or punctuation-heavy text becomes a folded block scalar so the
    generated frontmatter always parses.
    """
    single_line = " ".join(text.split())
    risky = single_line.startswith(("&", "*", "!", "%", "@", "`", "-", "?", ">", "|", "{", "[", '"', "'"))
    if len(single_line) <= 90 and ": " not in single_line and not single_line.endswith(":") and not risky:
        return single_line
    indented = "\n".join(f"  {line}" for line in wrap(single_line, 88))
    return ">-\n" + indented


def wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
