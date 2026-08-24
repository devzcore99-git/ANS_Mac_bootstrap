#!/usr/bin/env python3
"""How many subagents may run at once, resolved per project.

The number is not a property of a task, it is a property of the machine serving
the models — so it lives in a config file that can be changed on the fly, and
carries a per-project override for the cases where one project's work is
heavier than the rest.

It lives in ../_lib rather than in either agent skill because both read it and
neither owns it: /herdr-agents is the orchestrator, /opencode-agents is the
legacy path, and a value that disagreed between them would be worse than no
value at all.

Resolution order, most specific first. The first layer that names a number wins:

  1. an explicit --parallel N on the command line          (one run)
  2. $AGENTS_MAX_PARALLEL                                   (one shell)
  3. <project>/.claude/agents-config.json                   (travels with the
                                                             repo, so a devpod
                                                             gets it too)
  4. ~/.config/opencode/agents-config.json, "projects" map  (per project, set
                                                             from one place)
  5. ~/.config/opencode/agents-config.json, top-level       (this machine)
  6. BUILTIN_DEFAULT                                        (this file)

Layers 3-5 are all optional; with no file anywhere the answer is the built-in.
There is deliberately no bundled JSON default: a config file copied into every
project by /project-bootstrap would read as drift the moment someone edited one
copy, and the audit would offer to overwrite exactly the local value they set.

Schema, both files (JSON with // comments tolerated):

  {
    "max_parallel_agents": 3,
    "projects": { "CODE_Stock_ML_Trainer": 1 }   // machine file only
  }

Usage:
  python3 agents_config.py [--project DIR] [--json]
  python  agents_config.py ...    # Windows
"""

import argparse
import json
import os
import re
import sys

# Three at once against the current endpoint. Raise it here only if the
# hardware changes for everyone; for one project or one run, use a config file
# or --parallel.
BUILTIN_DEFAULT = 3

# One endpoint, and every agent on it competes for the same weights. Past this
# the run is not faster, it is just harder to watch.
SANITY_MAX = 8

ENV_VAR = "AGENTS_MAX_PARALLEL"
FILENAME = "agents-config.json"
PROJECT_RELATIVE = os.path.join(".claude", FILENAME)
MACHINE_PATH = os.path.join("~", ".config", "opencode", FILENAME)

_COMMENT_RE = re.compile(r"^\s*//")


def _read(path):
    """Parse one config file, tolerating // comment lines. None if unusable."""
    try:
        with open(path, encoding="utf-8") as fh:
            body = "".join("" if _COMMENT_RE.match(line) else line
                           for line in fh)
        data = json.loads(body)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1 else None


def machine_path():
    return os.path.expanduser(MACHINE_PATH)


def project_path(project):
    return os.path.join(os.path.abspath(os.path.expanduser(project)),
                        PROJECT_RELATIVE)


def resolve(project=None, override=None):
    """Return {"value", "source", "warning"}. Never raises."""
    if override is not None:
        value = _positive_int(override)
        if value:
            return _capped(value, "--parallel")

    env = os.environ.get(ENV_VAR)
    if env:
        try:
            value = _positive_int(int(env.strip()))
        except ValueError:
            value = None
        if value:
            return _capped(value, "$%s" % ENV_VAR)

    if project:
        path = project_path(project)
        data = _read(path)
        if data:
            value = _positive_int(data.get("max_parallel_agents"))
            if value:
                return _capped(value, path)

    machine = _read(machine_path())
    if machine:
        name = os.path.basename(os.path.normpath(
            os.path.abspath(os.path.expanduser(project)))) if project else None
        projects = machine.get("projects")
        if name and isinstance(projects, dict):
            value = _positive_int(projects.get(name))
            if value:
                return _capped(value, "%s (projects.%s)"
                               % (machine_path(), name))
        value = _positive_int(machine.get("max_parallel_agents"))
        if value:
            return _capped(value, machine_path())

    return _capped(BUILTIN_DEFAULT, "built-in default")


def _capped(value, source):
    warning = None
    if value > SANITY_MAX:
        warning = ("%d agents share one endpoint; above %d they contend rather "
                   "than finish sooner." % (value, SANITY_MAX))
    return {"value": value, "source": source, "warning": warning}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="project directory, for its "
                                          ".claude/agents-config.json and its "
                                          "entry in the machine file")
    parser.add_argument("--parallel", type=int, help="explicit override, to "
                                                     "show what it resolves to")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = resolve(args.project, args.parallel)
    if args.json:
        result["searched"] = {
            "env": ENV_VAR,
            "project": project_path(args.project) if args.project else None,
            "machine": machine_path(),
        }
        print(json.dumps(result))
    else:
        print("%d  (from %s)" % (result["value"], result["source"]))
        if result["warning"]:
            print("warn: %s" % result["warning"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
