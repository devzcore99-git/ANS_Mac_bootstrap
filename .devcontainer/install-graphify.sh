#!/usr/bin/env bash
#
# Install graphify (the `graphifyy` PyPI package) into the container.
#
# Run once from postCreateCommand, as `vscode`. Not on the start path: like
# install-herdr.sh beside it this does not need to re-run when a stopped
# container comes back, and it reaches the network, which the firewall has no
# reason to be holding open on every boot.
#
# graphify turns a repository into a queryable knowledge graph — symbols, calls,
# imports and communities, extracted from the AST. The workspace rule set every
# project carries (.claude/rules/workspace.md, "Code Graph") tells agents to
# reach for `graphify query` / `explain` / `path` / `affected` before reading the
# tree, and code projects ship a /graphify-update skill that drives the same
# binary. Until now that only worked where someone had installed graphify on the
# machine by hand, so inside a container the skill reported `unavailable` and
# every session fell back to grepping. This is what makes it present.
#
# WHY THE PACKAGE IS CALLED `graphifyy`
#
# Two y's is not a typo. The project ships on PyPI under that name while the
# `graphify` name is being reclaimed upstream; the CLI it installs is still
# `graphify`. The npm package of the same name is NOT this project — it is a
# different author's stub that re-exports @sentropic/graphify — so PyPI is the
# only correct source here. Do not "fix" the spelling and do not switch to npm.
#
# WHY pipx AND NOT `python3 -m pip install`
#
# The python devcontainer feature defaults to `os-provided`, so python3 is
# Ubuntu's, which is PEP 668 externally-managed: a plain `pip install` refuses.
# `--user` would land the CLI in ~/.local/bin, which is only on PATH via
# ~/.profile and so invisible to a non-interactive `bash -c` — exactly the trap
# documented for npm in devcontainer.json. pipx has neither problem: the same
# feature installs it and bakes PIPX_BIN_DIR into the image PATH through its
# containerEnv, so the binary is on PATH for every shell and every lifecycle
# hook, and graphify's ~25 dependencies (networkx, numpy, a tree-sitter grammar
# per language) sit in their own venv instead of on top of the system python.
#
# WHAT THIS DELIBERATELY DOES NOT DO
#
# It does not run `graphify install`. That command is the vendor's skill
# installer: it copies a /graphify SKILL.md into ~/.claude/skills, appends a
# registration block to ~/.claude/CLAUDE.md and registers a PreToolUse hook. In
# this template ~/.claude is the shared `claude-code-config` volume, so all three
# would be written once and seen by every container mounting it — and they would
# sit beside the workspace's own /graphify-update skill and Code Graph rules,
# which cover the same ground and pass the flags that keep extraction offline
# and unbilled. The CLI is what the workspace needs; the skill layer is already
# there. Anyone who wants the vendor skill can run `graphify install` by hand.
#
# NETWORK: the download is the only step that leaves the container, and it runs
# at create time, before postStartCommand applies the firewall. It would work
# with the firewall up anyway — pypi.org and files.pythonhosted.org are in
# firewall-allow.base.txt. Nothing graphify does afterwards needs the network:
# extraction and querying are local and offline.
#
# Exits non-zero on any failure. The caller in devcontainer.json deliberately
# does NOT treat that as fatal — a PyPI outage should cost the container
# graphify, not the whole create.

set -euo pipefail

# Pinned, for the same reason opencode and herdr are: everything else in this
# container is nailed to a digest or an exact version, and a floating install
# is the one part of the build two people cannot reproduce. Bumping it is a
# deliberate edit to this file. Latest is at https://pypi.org/project/graphifyy/.
GRAPHIFY_VERSION="0.9.49"

# The python feature's own paths, from its containerEnv. Restated rather than
# inherited: some runners (DevPod) execute lifecycle hooks through a switch to
# the remote user where PAM resets PATH to the login.defs default, and a hook
# that then cannot find pipx fails with "command not found" on a container where
# pipx is installed and working.
export PIPX_HOME="${PIPX_HOME:-/usr/local/py-utils}"
export PIPX_BIN_DIR="${PIPX_BIN_DIR:-$PIPX_HOME/bin}"
export PATH="/usr/local/python/current/bin:$PIPX_BIN_DIR:$PATH"

echo "[graphify] installing graphifyy==${GRAPHIFY_VERSION}"

if command -v pipx >/dev/null 2>&1; then
    # --force rather than a bare install: pipx refuses when the package is
    # already there, which would make a hand re-run fail instead of putting the
    # pinned version back.
    pipx install --force "graphifyy==${GRAPHIFY_VERSION}"
else
    # Fallback for a project that turned the feature's tools off. `--user` is
    # the only writable target on an externally-managed python, and the flag is
    # what gets past PEP 668; both are why pipx is preferred above.
    echo "[graphify] WARNING: pipx not found; falling back to pip --user"
    echo "[graphify]          the CLI lands in ~/.local/bin, which a"
    echo "[graphify]          non-interactive shell may not have on PATH"
    python3 -m pip install --user --break-system-packages \
        "graphifyy==${GRAPHIFY_VERSION}"
    export PATH="$HOME/.local/bin:$PATH"
fi

# Smoke test that also catches a pin/package mismatch. `graphify --version`
# prints "graphify <version>", and a binary that runs but reports something
# other than what was asked for means the install did not land where PATH finds
# it — an older copy earlier on PATH, most likely.
installed="$(graphify --version)"
echo "[graphify] installed: ${installed}"
case "$installed" in
    *"$GRAPHIFY_VERSION"*) ;;
    *)
        echo "ERROR: graphify on PATH reports '${installed}', expected ${GRAPHIFY_VERSION}"
        echo "       which graphify: $(command -v graphify || echo '<not on PATH>')"
        exit 1
        ;;
esac

echo "[graphify] ready — see .claude/rules/workspace.md, \"Code Graph\""
