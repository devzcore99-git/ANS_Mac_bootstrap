# Workspace Rules

Conventions shared by every project in the `~/AI_Projects` workspace. This file
is boilerplate: it is copied into each project unchanged and overwritten on
update, so **never edit it inside a project** — anything project-specific
belongs in that project's `CLAUDE.md`.

It is committed to the repository on purpose. A devpod, a fresh clone, and a
cloud run each see only this repository, so rules that live outside it would
not arrive. Loading is automatic in both tools:

| Tool | How it loads |
|------|--------------|
| Claude Code | reads `.claude/rules/` natively, every session |
| opencode | via `"instructions": [".claude/rules/*.md"]` in the host or devcontainer opencode config |

Do not add an `AGENTS.md` to a project. opencode reads `CLAUDE.md` only as a
fallback when no `AGENTS.md` exists, so adding one silently hides the project's
own guidance from opencode.

## Git Workflow

Unless this project's own `CLAUDE.md` overrides:

1. **Work in a git worktree.** `EnterWorktree` named for the work
   (`add-rsi-indicator`) puts it at `<repo>/.claude/worktrees/<name>` on branch
   `worktree-<name>`, leaving the repo directory on `main` and usable.
2. **Never commit to `main`/`master`.** Without a worktree:
   `git checkout -b claude_<short-description>`.
3. **Conventional commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
4. **Ask before merging** to `main`/`master`.
5. **Ask before pushing** — committing locally is a separate decision.
6. **Clean up with `ExitWorktree`** (`remove` drops directory and branch
   together, `keep` leaves both). A merged branch can't be deleted while its
   worktree holds it, so removing the worktree — not `git branch -d` — is what
   finishes the cycle.

Both branch prefixes are Claude's: `claude_` hand-made, `worktree-` from
`EnterWorktree`. The `worktree-` prefix isn't configurable, so never name a
worktree `claude_something` — that only yields `worktree-claude_something`.

`.claude/worktrees/` is gitignored. It lives inside the repo, so un-ignored it
would leave the repo dirty and block every merge.

A change spanning more than one repository uses `claude_` branches in each, not
a worktree — git won't check out one branch in two trees.

## Dependencies

**Never install software without asking first** — `pip install`, `uv add`, `npm
install`/`npx` of a package not already present, `apt`, `brew`, `docker pull`,
`cargo add`, `go get`, global CLIs, VS Code extensions, MCP servers. Writing the
name into `requirements.txt`, `pyproject.toml`, or `package.json` is the same
decision. Ask with specifics — package, version, why, the alternative if we skip
it — and wait for an answer rather than installing and reporting it afterward.
If a task can't be finished without one, say so and stop there; prefer the
standard library or something already in the project.

No ask needed to install what a manifest already pins (`pip install -r
requirements.txt`, `uv sync`, `npm ci`) into the project's own environment —
that restores a declared environment, it doesn't add to it — or to read what is
installed (`pip list`, `npm ls`, `which`, `--version`).

### Install into the project, never the machine

An approved dependency goes into the project's own environment, never a
system-wide or user-wide location: the project stays reproducible from its
manifest, and the machine stays clean for every other project.

| Language | Where it goes | Not this |
|----------|---------------|----------|
| Python | the project's `.venv` (`uv add`, or `.venv/bin/pip install`) | system `pip`, `pip --user`, `sudo pip` |
| Node | the project's `node_modules` (`npm install <pkg>`) | `npm install -g` |
| Rust | the project's `Cargo.toml` (`cargo add`) | `cargo install` for a library |
| Go | the project's `go.mod` (`go get`) | `go install` for a library |

Create the environment if it is missing (`uv venv`, `python -m venv .venv`)
rather than falling back to the system interpreter, and run the project through
it (`uv run`, `.venv/bin/python`). Record the dependency in the manifest in the
same step, so the next clone gets it from `uv sync` / `npm ci`. Environment
directories — `.venv`, `node_modules`, `target/`, `vendor/` — are gitignored;
only manifest and lockfile are committed.

A genuinely machine-level tool (CLI, system package, runtime) is the exception,
and exactly the case that needs the ask above: name it, say why it can't live in
the project, and wait.

## Code Graph

Code projects carry `/graphify-update` in `.claude/skills/graphify-update/` —
prose and container repositories do not, so check the directory exists before
reaching for it. It builds a **graphify** code graph into `graphify-out/`: a
map of the symbols, calls, imports and communities in this repository, produced
from the AST with no LLM call and no API key.

```bash
python3 .claude/skills/graphify-update/graphify-update.py     # build or refresh
```

Use the map before reading the tree. `graphify-out/GRAPH_REPORT.md` is the
whole architecture in about two thousand tokens — god nodes, communities with
member lists, import cycles, cross-community bridges, isolated nodes — and
these answer a specific question without a grep:

```bash
graphify query "<question>" --budget 1500   # scoped subgraph for one question
graphify explain "<symbol>"                 # a symbol and its neighbours
graphify path "<A>" "<B>"                   # how two symbols connect
graphify affected "<symbol>" --depth 2      # what a change to it reaches
```

- **Never commit `graphify-out/`.** The skill excludes it through
  `.git/info/exclude` on every run, which is local and leaves the working tree
  clean. Do not add it to `.gitignore` instead.
- **Never hand-run `graphify extract` without `--code-only`.** That flag, and
  `--no-label` on the clustering pass, are what keep the graph free: without
  them graphify sends this project's documents to an LLM backend and bills for
  them. The skill always passes both — run the skill, not the tool.
- **The graph is a map, not evidence.** It is AST-derived, `INFERRED` edges are
  model guesses, and community names are placeholders like `Community 7`. Read
  the source before asserting anything from it.
- **graphify is a per-machine install and may not be here.** The skill reports
  `unavailable` and changes nothing; work from the source as normal. Do not
  install it to satisfy this section — that is the ask above.

## Installation Files

Install steps live at the same two paths in every project:

```
INSTALL.md      # prerequisites, per-OS table, configuration, verify, uninstall
install/
  macos.sh      linux.sh      windows.ps1
```

The point is cross-repo discoverability — one predictable location in every
project, so finding the install steps anywhere is a single glob rather than a
per-project hunt. That only holds if the names are identical everywhere, so
treat them as fixed.

- Name per-OS files for the platform alone: `macos.sh`, not `install-macos.sh`.
  At a repo root instead of in `install/`, use the suffix form
  `install.macos.sh` so siblings sort together.
- Use the human platform words (`macos`, `linux`, `windows`) throughout. The
  runtime tokens (`darwin`, `win32`) are right only when a script selects the
  file programmatically — never mix the two vocabularies in one repo.
- Ship a script only for a platform the project actually runs on. Three scripts
  where only macOS was tested is three claims, two of them false; say in
  `INSTALL.md` which were verified.
- **Never leave a stub install script in place.** One with its steps commented
  out still exits 0 and prints "install complete" — it reads as a supported
  path and fails only once someone trusts it on a clean machine. Write the real
  steps from the project's own manifests, or delete the file.
- A project installed by one command does not need `install/` at all. Put the
  command in `INSTALL.md` and stop there.
