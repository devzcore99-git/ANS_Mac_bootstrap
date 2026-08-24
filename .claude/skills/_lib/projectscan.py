"""Shared project discovery, stack detection, and report parsing.

What is shared here is how a skill *looks at* the workspace: which directories
are projects, what each one is written in, how big it is, what housekeeping it
has, and how to read a per-project markdown report back into structured data.
Two skills consume it today — `/projects-recommendations` and
`/projects-features-suggest` — and they differ only in what they then ask an
agent to write.

The report shape is the parameter. A `ReportSpec` names the file, the
`generated-by` stamp that marks it as skill output rather than somebody's own
document, which section headings mean "settled", and which `**Field**:` lines
to parse. Everything downstream of that — the personas, the agent brief, the
report template, the reporting prose — stays in the skill that owns it, because
that is the skill, not infrastructure.

Deliberately NOT shared: the persona tables. Both skills key them on the same
`primary_stack`, but a reviewer looking for defects and an ideator looking for
capabilities are different voices, and collapsing them would mean one skill
picking through the other's phrasing to find its own.

Callers resolve this directory through `os.path.realpath(__file__)`, not
`abspath`: a skill directory reached through a link must find the real tree.

This module is itself listed in `bundled_skills`, so `/project-bootstrap` ships
it into every project beside the two sweeps that import it. What does not
travel is `skills_config.json`, a file rather than a directory: a copy
therefore falls back to the repository it was copied into and scopes itself to
that one project. See load_root.
"""

import json
import os
import re
import sys
from collections import Counter

_LIB_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_PATH = os.path.join(_LIB_DIR, os.pardir, "skills_config.json")

sys.path.insert(0, _LIB_DIR)
sys.path.insert(0, os.path.join(_LIB_DIR, os.pardir, "graphify-update"))
from gitutil import git_run  # noqa: E402
# The one implementation of "append to .git/info/exclude" lives in the
# /graphify-update skill, which is copied into every project and so cannot
# import from _lib. See exclude_paths below.
from graph_pipeline import exclude_entries  # noqa: E402

# Directories that are never projects, regardless of prefix.
IGNORED_DIRS = {".claude", ".git", "node_modules", "__pycache__"}

# Extension -> stack label. Extensions not listed here still count toward the
# file inventory, they just do not vote on the stack.
EXT_STACKS = {
    ".py": "Python", ".ipynb": "Jupyter",
    ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".js": "JavaScript/TypeScript", ".mjs": "JavaScript/TypeScript",
    ".cjs": "JavaScript/TypeScript", ".jsx": "JavaScript/TypeScript",
    ".ts": "JavaScript/TypeScript", ".tsx": "JavaScript/TypeScript",
    ".html": "Web", ".htm": "Web", ".css": "Web", ".scss": "Web",
    ".cs": "C#", ".csproj": "C#",
    ".java": "Java", ".kt": "Kotlin",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".m": "Objective-C",
    ".c": "C/C++", ".h": "C/C++", ".cpp": "C/C++", ".hpp": "C/C++",
    ".sql": "SQL",
    ".bat": "Batch", ".cmd": "Batch", ".command": "Shell",
    ".afl": "AmiBroker AFL",
    ".md": "Docs", ".markdown": "Docs", ".rst": "Docs",
}

# Consulted only when nothing above matched. A repo of pure config or pure
# spreadsheets is still worth naming, but config files should never outrank
# the language a project is actually written in.
FALLBACK_EXT_STACKS = {
    ".json": "Config", ".yml": "Config", ".yaml": "Config",
    ".toml": "Config", ".ini": "Config", ".cfg": "Config",
    ".conf": "Config", ".env": "Config",
    ".csv": "Data", ".xlsx": "Data", ".xls": "Data", ".tsv": "Data",
}

# Marker files are stronger evidence than a stray extension: a repo with one
# .py helper and a Dockerfile at the root is a Docker project. How far a marker
# promotes its stack depends on which of the three groups below it lands in —
# see the comment in detect_stack.
MARKER_STACKS = [
    ("Ansible", ("ansible.cfg", "site.yml", "site.yaml", "playbook.yml",
                 "playbook.yaml", "inventory", "inventory.ini")),
    ("Dev Container", (".devcontainer/devcontainer.json",)),
    ("Docker", ("dockerfile", "docker-compose.yml", "docker-compose.yaml",
                "compose.yml", "compose.yaml")),
    ("Python", ("pyproject.toml", "setup.py", "setup.cfg",
                "requirements.txt", "pipfile")),
    ("JavaScript/TypeScript", ("package.json", "tsconfig.json")),
    ("Rust", ("cargo.toml",)),
    ("Go", ("go.mod",)),
    ("Java", ("pom.xml", "build.gradle")),
    ("Ruby", ("gemfile",)),
]

# A marker whose presence says nothing about what the project is.
# /project-bootstrap scaffolds a .devcontainer/ into every project in this
# workspace, so the marker is near-universal and carries no signal.
WEAK_MARKER_STACKS = {"Dev Container"}

# Every stack an extension can vote for. A marker for one of these has to be
# backed by that much code before it outranks what the repo is mostly made of.
LOC_BEARING_STACKS = set(EXT_STACKS.values())
MARKER_LOC_FLOOR = 100

# Files whose presence is worth telling an agent about up front.
SIGNAL_FILES = {
    "readme": ("readme.md", "readme.rst", "readme.txt"),
    "claude_md": ("claude.md",),
    "license": ("license", "license.md", "license.txt"),
    "ci": (".github/workflows", ".gitlab-ci.yml"),
    "tests": ("tests", "test", "spec", "__tests__"),
    "lockfile": ("poetry.lock", "package-lock.json", "yarn.lock",
                 "cargo.lock", "pipfile.lock", "uv.lock"),
}

# Skip these when counting lines — binary or generated, and reading them is
# wasted IO.
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".exe", ".dll", ".so", ".dylib", ".woff", ".woff2", ".ttf", ".mp4",
    ".mp3", ".db", ".sqlite", ".sqlite3", ".pyc", ".bin", ".jar", ".class",
    ".lnk", ".xlsx", ".xls", ".docx", ".pptx",
}

MAX_LOC_BYTES = 1_000_000   # do not line-count anything bigger than this
MAX_FILES_LISTED = 5000     # cap the inventory walk on pathological repos

META_RE = re.compile(r"^<!--\s*([a-z-]+)\s*:\s*(.*?)\s*-->\s*$")
CATEGORY_RE = re.compile(r"^##\s+(.+?)\s*$")
ITEM_RE = re.compile(r"^###\s+\[(High|Medium|Low)\]\s+(.+?)\s*$", re.I)

# never and stale are the work; current and foreign are context.
STATE_ORDER = {"never": 0, "stale": 1, "current": 2, "foreign": 3}


class ReportSpec:
    """What a per-project markdown report looks like to the parser.

    done_categories are the `## ` headings whose items are settled rather than
    outstanding. /projects-recommendations has one ("Completed");
    /projects-features-suggest has two, because an idea can leave the open list
    by being built or by being turned down, and those are not the same fact.
    """

    def __init__(self, report_name, generated_by, done_categories, fields):
        self.report_name = report_name
        self.generated_by = generated_by
        self.done_categories = tuple(done_categories)
        self.fields = tuple(fields)
        self.field_re = re.compile(
            r"^\*\*(%s)\*\*\s*:\s*(.*?)\s*$" % "|".join(fields), re.I)


def die(message):
    print(json.dumps({"error": message}))
    sys.exit(1)


def git(repo, *args, timeout=15):
    """Run a git command in repo. Returns (ok, stdout). Never raises.

    Non-interactive: git_run pins GIT_TERMINAL_PROMPT=0 and empty askpass
    helpers, so a repo needing credentials fails fast rather than hanging an
    unattended run on a prompt nobody can see.
    """
    ok, out, _ = git_run(repo, args, timeout=timeout)
    return ok, out.strip()


def enclosing_repo():
    """The repository this copy of the library lives in, or None.

    /project-bootstrap copies these skills into each project, so in a devpod or
    a clone this resolves to the one project that exists there — the only
    honest answer to "which projects can I see?" when everything above the
    repository is missing.
    """
    path = _LIB_DIR
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def load_root(override):
    """The directory to look for projects under.

    Three answers, in order: an explicit --root; the configured workspace, when
    skills_config.json is present and that directory exists; otherwise the
    repository this skill was copied into.

    The last is what makes a copied skill work in a devpod. Only ASST_BBMax
    carries skills_config.json — copy_skill copies directories, and the config
    is a file beside them — so a project copy always lands on the fallback and
    scopes itself to the single repository it can see. A configured workspace
    that does not exist is the same situation and takes the same answer.
    """
    if override:
        return os.path.abspath(os.path.expanduser(override))
    root = None
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            root = json.load(fh).get("projects_root_workspace")
    except (OSError, ValueError):
        root = None
    if root:
        root = os.path.abspath(os.path.expanduser(root))
        if os.path.isdir(root):
            return root
    fallback = enclosing_repo()
    if fallback:
        return fallback
    if root:
        die("The configured workspace root %s does not exist, and this copy "
            "of the skill is not inside a git repository either. Pass --root "
            "DIR." % root)
    die("skills_config.json was not found at %s and this copy of the skill is "
        "not inside a git repository. Pass --root DIR."
        % os.path.normpath(CONFIG_PATH))


_DATA_PREFIXES = None


def data_prefixes_from_config():
    """data_prefixes from skills_config.json, read once. Empty on any problem —
    a missing key should not stop a run."""
    global _DATA_PREFIXES
    if _DATA_PREFIXES is None:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                _DATA_PREFIXES = tuple(json.load(fh).get("data_prefixes") or ())
        except (OSError, ValueError):
            _DATA_PREFIXES = ()
    return _DATA_PREFIXES


def discover(root, wanted=None, data_prefixes=None):
    """Return [(name, path)] for every directory under root holding a .git.

    Directories matching data_prefixes are skipped: DBX_ holds databases and
    data files, and neither a code review nor a feature proposal has anything
    to say about a SQLite file. Checked by prefix so the exclusion survives one
    of them acquiring a repository.
    """
    if not os.path.isdir(root):
        die("Workspace root does not exist: %s" % root)
    if data_prefixes is None:
        data_prefixes = data_prefixes_from_config()
    if os.path.exists(os.path.join(root, ".git")):
        # The root is itself a repository, not a directory of them: a devpod,
        # a clone, or --root pointed straight at a project. The only project
        # in scope is the one we are standing in, and listing its
        # subdirectories would find none.
        name = os.path.basename(os.path.normpath(root))
        if wanted and name not in wanted:
            return []
        return [(name, root)]
    found = []
    for name in sorted(os.listdir(root)):
        if name in IGNORED_DIRS or name.startswith("."):
            continue
        # A leading underscore parks a directory as under test: not part of
        # the workspace, so it is invisible to tooling rather than merely
        # excluded from one check. See CLAUDE-WORKSPACE.md.
        if name.startswith("_"):
            continue
        if any(name.startswith(p) for p in data_prefixes):
            continue
        path = os.path.join(root, name)
        if not os.path.isdir(path) or not os.path.exists(
                os.path.join(path, ".git")):
            continue
        if wanted and name not in wanted:
            continue
        found.append((name, path))
    return found


def scope_of(root):
    """"project" when root is a single repository, "workspace" when it holds
    them. The two skills report it so a run in a devpod cannot be mistaken for
    a run that swept everything."""
    return "project" if os.path.exists(os.path.join(root, ".git")) \
        else "workspace"


def resolve_projects(root, wanted):
    """discover(), but a name that matches nothing is an error rather than a
    silently empty result. Every caller wants this; none wants to be told it
    reviewed zero projects because of a typo."""
    repos = discover(root, set(wanted) if wanted else None)
    if wanted:
        missing = set(wanted) - {name for name, _ in repos}
        if missing:
            die("Not a git repo under %s: %s" % (root, ", ".join(sorted(missing))))
    return repos


def repo_files(path):
    """Tracked plus untracked-but-not-ignored files, relative to the repo.

    Using git rather than os.walk means .gitignore is respected for free, so
    virtualenvs and build output never reach the inventory.
    """
    ok_tracked, tracked = git(path, "ls-files")
    ok_other, other = git(path, "ls-files", "--others", "--exclude-standard")
    if not ok_tracked and not ok_other:
        return [], True
    names = []
    for blob in (tracked, other):
        names.extend(line for line in blob.splitlines() if line.strip())
    truncated = len(names) > MAX_FILES_LISTED
    return names[:MAX_FILES_LISTED], truncated


def count_lines(full_path):
    try:
        if os.path.getsize(full_path) > MAX_LOC_BYTES:
            return 0
        with open(full_path, "rb") as fh:
            return fh.read().count(b"\n")
    except OSError:
        return 0


def detect_stack(path, files):
    """Return (stacks_ranked, ext_counts, loc_by_stack, signals).

    Marker files pin a stack in regardless of how few source files carry the
    matching extension; extensions then rank by lines of code, which tracks
    where the substance of a repo actually is better than file count does.
    """
    lower = {name.lower() for name in files}

    ext_counts = Counter()
    loc_by_stack = Counter()
    for name in files:
        ext = os.path.splitext(name)[1].lower()
        if ext in BINARY_EXTS:
            continue
        ext_counts[ext] += 1
        stack = EXT_STACKS.get(ext)
        if stack:
            loc_by_stack[stack] += count_lines(os.path.join(path, name))

    markers = []
    for stack, needles in MARKER_STACKS:
        for needle in needles:
            if needle in lower or any(
                    n == needle or n.endswith("/" + needle) for n in lower):
                markers.append(stack)
                break

    # A marker jumps the queue only where it is real evidence of what the repo
    # is. Three cases:
    #
    #  - Weak markers say nothing. A .devcontainer/ is scaffolded into every
    #    project in this workspace, so it was typing 26 of 38 repos here as
    #    "Dev Container" — handing 90k lines of Python to a container expert.
    #    They rank last, and lead only a repo with nothing else in it.
    #  - Language markers must be backed by code. A stray package.json beside
    #    twenty lines of JavaScript should not outrank the language the project
    #    is actually written in; MARKER_LOC_FLOOR is what "actually" means.
    #  - Infrastructure markers (ansible.cfg, a Dockerfile) promote on the
    #    marker alone: no extension maps to those stacks, so their LOC is
    #    always zero and any floor would demote them every time.
    strong, weak = [], []
    for stack in markers:
        if stack in WEAK_MARKER_STACKS:
            weak.append(stack)
        elif (stack in LOC_BEARING_STACKS
                and loc_by_stack[stack] < MARKER_LOC_FLOOR):
            continue                            # let it rank on its own LOC
        else:
            strong.append(stack)

    # Among promoted markers the one carrying the most code leads. Without
    # this the persona is decided by the declaration order of MARKER_STACKS,
    # which is arbitrary.
    strong.sort(key=lambda s: loc_by_stack[s], reverse=True)

    ranked = [s for s, _ in loc_by_stack.most_common()
              if s not in strong and s not in weak]
    ranked = strong + ranked + weak

    # A repo of nothing but prose is a knowledge base, not a codebase, and
    # wants different treatment.
    code_stacks = [s for s in ranked if s != "Docs"]
    if not code_stacks:
        fallback = Counter()
        for name in files:
            stack = FALLBACK_EXT_STACKS.get(os.path.splitext(name)[1].lower())
            if stack:
                fallback[stack] += 1
        extra = [s for s, _ in fallback.most_common()]
        # Prose still leads if there is any: a knowledge base with a config
        # file in it is a knowledge base.
        ranked = ranked + extra if ranked else (extra or ["Unknown"])

    # Markdown lines are cheap. A well-documented Python project routinely
    # carries more prose than code — ASST_BBMax itself is 10.1k lines of Docs
    # against 8.7k of Python — and letting Docs win on raw LOC would frame the
    # whole job around the documentation. Docs leads only where there is no
    # real code, which is exactly the knowledge-base case.
    #
    # Demoted by exactly one place, not buried: prose is still a real part of
    # these repos and the agent should be told about it, so Docs keeps its LOC
    # rank everywhere except the top spot.
    has_code = any(s != "Docs" and loc_by_stack[s] >= MARKER_LOC_FLOOR
                   for s in ranked)
    if ranked and ranked[0] == "Docs" and has_code:
        ranked.remove("Docs")
        ranked.insert(1, "Docs")

    # Directory needles ("tests", ".github/workflows") match on whole path
    # components, so a nested layout counts. The old test was anchored to the
    # top level — exact dirname, or a "needle/" prefix — so src/tests/test_x.py
    # produced the dirname "src/tests" and matched nothing, reporting
    # tests: false for a repo that has them. The agent brief then states "no
    # tests" as fact, so the false negative became a fabricated finding in
    # another project's report. This repo is its own reproduction:
    # .claude/skills/food-finder/tests/food-finder.test.js.
    #
    # File needles ("readme.md", "poetry.lock") stay anchored: a lock file three
    # directories down belongs to something vendored, not to this project.
    components = set()
    for name in files:
        parts = name.lower().split("/")
        components.update(parts[:-1])
        for i in range(len(parts) - 1):
            components.add("/".join(parts[i:-1]))

    signals = {}
    for label, needles in SIGNAL_FILES.items():
        hit = False
        for n in needles:
            if n in lower or any(f.startswith(n + "/") for f in lower):
                hit = True
                break
            # A needle naming a directory rather than a file matches any path
            # component, at any depth.
            if "." not in os.path.basename(n) or "/" in n:
                if n in components:
                    hit = True
                    break
        signals[label] = hit

    return ranked, ext_counts, loc_by_stack, signals


def read_report(path, spec):
    """Parse a project's report into metadata plus its items."""
    report_path = os.path.join(path, spec.report_name)
    try:
        with open(report_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None

    meta, items, summary = {}, [], []
    category, current = None, None
    in_summary = False

    for line in text.splitlines():
        hit = META_RE.match(line)
        if hit:
            meta[hit.group(1)] = hit.group(2)
            continue

        hit = ITEM_RE.match(line)
        if hit:
            current = {"priority": hit.group(1).title(), "title": hit.group(2),
                       "category": category or "Uncategorized",
                       "done": (category or "").strip() in spec.done_categories}
            items.append(current)
            in_summary = False
            continue

        hit = CATEGORY_RE.match(line)
        if hit:
            category = hit.group(1)
            current = None
            in_summary = category.lower() == "summary"
            continue

        hit = spec.field_re.match(line)
        if hit and current is not None:
            current[hit.group(1).lower()] = hit.group(2)
            continue

        if in_summary and line.strip():
            summary.append(line.strip())

    return {
        "path": report_path,
        "meta": meta,
        "summary": " ".join(summary),
        "items": items,
        "raw": text,
    }


def commits_since(path, sha):
    ok, out = git(path, "rev-list", "--count", "%s..HEAD" % sha)
    if not ok or not out.isdigit():
        return None
    return int(out)


def scan_one(name, path, spec):
    """Everything one project looks like: stack, size, signals, report state."""
    ok_head, head = git(path, "rev-parse", "HEAD")
    _, head_date = git(path, "log", "-1", "--format=%cI")
    ok_dirty, dirty_out = git(path, "status", "--porcelain")
    dirty = bool(ok_dirty and dirty_out.strip())

    files, truncated = repo_files(path)
    ranked, ext_counts, loc_by_stack, signals = detect_stack(path, files)
    report = read_report(path, spec)

    if report is None:
        state, reason = "never", "no %s yet" % spec.report_name
    elif report["meta"].get("generated-by") != spec.generated_by:
        # Somebody wrote a file of this name here for their own reasons.
        # Overwriting it would destroy real content, so this repo is out of
        # bounds until the user says otherwise.
        state, reason = "foreign", (
            "an unrelated %s already exists here — not skill output"
            % spec.report_name)
    else:
        analyzed = report["meta"].get("analyzed-commit", "")
        if not analyzed:
            state, reason = "stale", "existing report has no analyzed-commit stamp"
        elif ok_head and analyzed != head:
            state, reason = "stale", "%d commit(s) since the last analysis" % (
                commits_since(path, analyzed) or 0)
        elif dirty:
            state, reason = "stale", "uncommitted changes since the last analysis"
        else:
            state, reason = "current", "up to date with HEAD"

    return {
        "project": name,
        "path": path,
        "head": head[:8] if ok_head else None,
        "head_full": head if ok_head else None,
        "head_date": head_date or None,
        "dirty": dirty,
        "state": state,
        "reason": reason,
        "stacks": ranked[:4],
        "primary_stack": ranked[0] if ranked else "Unknown",
        "file_count": len(files),
        "files_truncated": truncated,
        "loc_by_stack": dict(loc_by_stack.most_common(6)),
        "total_loc": sum(loc_by_stack.values()),
        "signals": signals,
        "report": None if report is None else {
            "analyzed_at": report["meta"].get("analyzed-at"),
            "analyzed_commit": (report["meta"].get("analyzed-commit") or "")[:8],
            "item_count": sum(1 for i in report["items"] if not i["done"]),
            "completed_count": sum(1 for i in report["items"] if i["done"]),
            "undated_count": sum(1 for i in report["items"]
                                 if not i["done"] and not i.get("raised")),
            "foreign": state == "foreign",
        },
    }


def short_loc(loc):
    if loc >= 1000:
        return "%.1fk" % (loc / 1000.0)
    return str(loc)


def print_scan_table(results, counts):
    """The picker table, ready to paste.

    The model was reading ~6k tokens of JSON and re-emitting the same rows as
    output tokens. Formatting here costs nothing and skips both halves.
    """
    rows = sorted(results, key=lambda r: (STATE_ORDER.get(r["state"], 9),
                                          r["project"].lower()))
    widths = [7, 5, 4]
    for r in rows:
        widths = [max(widths[0], len(r["project"])),
                  max(widths[1], len(r["primary_stack"])),
                  max(widths[2], len("%s f / %s" % (
                      "{:,}".format(r["file_count"]),
                      short_loc(r["total_loc"]))))]

    header = "  %s  %-*s  %-*s  %-*s  %s" % (
        "#".rjust(2), widths[0], "Project", widths[1], "Stack",
        widths[2], "Size", "State")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, r in enumerate(rows, 1):
        size = "%s f / %s" % ("{:,}".format(r["file_count"]),
                              short_loc(r["total_loc"]))
        print("  %2d  %-*s  %-*s  %-*s  %s" % (
            i, widths[0], r["project"], widths[1], r["primary_stack"],
            widths[2], size, r["state"]))
    print("")
    print("  %d repos: %d never, %d stale, %d current, %d foreign" % (
        len(rows), counts["never"], counts["stale"], counts["current"],
        counts["foreign"]))


def exclude_paths(path, entries, generated_by):
    """Add entries to one repo's .git/info/exclude, skipping any already there.

    The implementation is graph_pipeline.exclude_entries, in the
    /graphify-update skill: that skill is copied into every project and cannot
    import from here, so it owns the one copy and this delegates to it.
    """
    return exclude_entries(path, entries, generated_by)


def exclude_report(root, wanted, spec, extra=()):
    """exclude_paths across a set of repos, for the report and anything in
    extra.

    extra carries the working files the skills drop beside the report,
    `graphify-out/` above all: it is a generated code graph of tens of
    megabytes, and it has exactly as little business in the repo as the report
    does.
    """
    entries = [spec.report_name] + [e for e in extra if e != spec.report_name]
    results = []
    for name, path in resolve_projects(root, wanted):
        existing = read_report(path, spec)
        if existing and existing["meta"].get("generated-by") != spec.generated_by:
            results.append({"project": name, "status": "skipped-foreign",
                            "detail": "%s here is not skill output"
                                      % spec.report_name})
            continue
        result = exclude_paths(path, entries, spec.generated_by)
        result["project"] = name
        results.append(result)
    return results
