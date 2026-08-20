#!/usr/bin/env bash
#
# Install herdr (https://herdr.dev) and its Claude Code / opencode integrations.
#
# Run once from postCreateCommand, as `vscode` with passwordless sudo. Not on
# the start path: unlike init-firewall.sh this does not need to re-run when a
# stopped container comes back, and it reaches the network, which the firewall
# has no reason to be holding open on every boot.
#
# herdr is a terminal workspace manager for coding agents — it keeps agent
# panes alive across detach, and `/herdr-agents` (in ASST_BBMax) drives opencode
# subagents through it, one git worktree per task.
#
# WHY NOT `curl https://herdr.dev/install.sh | sh`
#
# The vendor installer has no version knob — it reads latest.json and takes
# whatever is current, so two rebuilds on different days get different herdr
# builds with no record of which. That is the exact problem that got opencode
# pinned in devcontainer.json, and it matters more here: this container mounts
# live Claude Code OAuth credentials at /home/vscode/.claude and the host's
# GitHub token at /home/vscode/.config/gh. So the release asset is fetched
# directly and pinned by version AND by the SHA-256 the project publishes
# alongside it. Bumping herdr is a deliberate edit to this file: change
# HERDR_VERSION and both digests together, from https://herdr.dev/latest.json.
#
# The Linux builds are static-pie ELF binaries with no runtime dependencies, so
# there is nothing to install beside them. Both architectures are pinned because
# the template runs on amd64 and on Apple Silicon.
#
# NETWORK: the download is the only step that leaves the container, and it runs
# at create time, before postStartCommand applies the firewall. herdr.dev is
# deliberately NOT in the allow-list — see init-firewall.sh. The visible
# consequence is that once the firewall is up, `herdr update` and the
# agent-detection manifest refresh cannot reach herdr.dev. That is the pin doing
# its job, not a fault. Re-running this script by hand needs INIT_FIREWALL=false
# or a firewall re-run.
#
# Exits non-zero on any failure. The caller in devcontainer.json deliberately
# does NOT treat that as fatal — a GitHub outage should cost the container
# herdr, not the whole create.

set -euo pipefail

# Pinned release. Both digests come from https://herdr.dev/latest.json, which
# publishes one per target; they are also the digests the vendor installer
# verifies against.
HERDR_VERSION="0.8.2"
SHA256_X86_64="976150a14d490c94b243ea2e1a7eb2dfb67f12e36b182db90936f6728e6aecf4"
SHA256_AARCH64="f55610658e1c2e0d2aaef730b4b2ab885f7f8ba00285ab372bfb14f2e3d5b40d"

# /usr/local/bin, not ~/.local/bin (where herdr installs itself by default):
# it is on PATH for every shell and every lifecycle hook without depending on
# ~/.profile having run, which a non-interactive `bash -c` never does. Being
# root-owned also means an in-container `herdr update` fails on the write rather
# than silently drifting off the pin above.
INSTALL_PATH="/usr/local/bin/herdr"

arch="$(uname -m)"
case "$arch" in
    x86_64)          asset="linux-x86_64";  want_sha="$SHA256_X86_64" ;;
    aarch64 | arm64) asset="linux-aarch64"; want_sha="$SHA256_AARCH64" ;;
    *)
        echo "ERROR: no herdr build pinned for architecture '$arch'"
        exit 1
        ;;
esac

url="https://github.com/herdrdev/herdr/releases/download/v${HERDR_VERSION}/herdr-${asset}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[herdr] downloading v${HERDR_VERSION} (${asset})"
# --retry rides out a transient 5xx from the release CDN; the timeouts keep a
# hung connection from stalling container create indefinitely. The binary is
# ~21 MB, so --max-time is generous rather than tight.
curl -fsSL --retry 3 --connect-timeout 10 --max-time 180 -o "$tmp/herdr" "$url"

# Verify BEFORE anything is made executable or moved onto PATH. sha256sum -c
# exits non-zero on a mismatch, and `set -e` turns that into an aborted install
# with the downloaded file still confined to $tmp.
echo "[herdr] verifying SHA-256"
printf '%s  %s\n' "$want_sha" "$tmp/herdr" | sha256sum -c -

echo "[herdr] installing to ${INSTALL_PATH}"
sudo install -o root -g root -m 0755 "$tmp/herdr" "$INSTALL_PATH"

# Smoke test that also catches a pin/asset mismatch: a binary that runs but
# reports a version other than the one requested means latest.json moved under
# the digests above.
installed="$("$INSTALL_PATH" --version)"
echo "[herdr] installed: ${installed}"
case "$installed" in
    *"$HERDR_VERSION"*) ;;
    *)
        echo "ERROR: installed binary reports '${installed}', expected ${HERDR_VERSION}"
        exit 1
        ;;
esac

# Agent integrations.
#
# These are the shims that make herdr's idle/working/blocked state authoritative
# instead of screen-scraped, which is what `/herdr-agents` relies on. Their
# payloads are embedded in the herdr binary — nothing is fetched — so this works
# with the firewall up and needs no allow-list entry. Re-running overwrites in
# place, so a rebuild is idempotent.
#
#   claude   -> ~/.claude/hooks/herdr-agent-state.sh, registered as a hook in
#               ~/.claude/settings.json
#   opencode -> ~/.config/opencode/plugins/herdr-agent-state.js
#
# Two things worth knowing about where those land:
#
#  * ~/.claude is the shared `claude-code-config` volume, so both the hook
#    script and its registration are visible to every container mounting it,
#    including ones built before herdr was added here. That is safe: the hook
#    exits 0 immediately unless HERDR_ENV=1, and the script it points at lives
#    in the same volume, so the registration is never dangling. It also means
#    the integration is effectively installed once for the whole workspace.
#    (The hook shells out to python3, which the python feature provides; without
#    it the hook degrades to a no-op rather than an error.)
#  * opencode discovers plugins from ~/.config/opencode/plugins regardless of
#    OPENCODE_CONFIG, which devcontainer.json points at the repo's own
#    opencode.json. The two are independent — the plugin is still loaded.
#
# This runs AFTER the chown of /home/vscode/.claude in postCreateCommand, so the
# volume is already writable as vscode and no sudo is needed here.
#
# Each install is allowed to fail on its own. `herdr integration install claude`
# refuses outright when ~/.claude does not exist ("install claude code first"),
# and under `set -e` that one refusal would abort the script — taking the
# opencode integration with it and reporting the whole install as failed, even
# though the binary above is in place and working. The integrations are the
# optional part; the binary is not.
#
# Both installs refuse when their agent's directory is missing, and at create
# time neither is guaranteed to exist yet: ~/.config/opencode is created by
# opencode on FIRST RUN, which has not happened — and may never, since
# OPENCODE_CONFIG points opencode at the repo's own config file instead. So
# create them first. An empty ~/.config/opencode holds no config file and
# therefore does not shadow OPENCODE_CONFIG; it is just the directory opencode
# scans for plugins. ~/.claude is the mounted volume and will normally already
# be there — mkdir -p covers a project that dropped the mount.
mkdir -p "$HOME/.claude" "$HOME/.config/opencode"

integration_failed=""
for target in claude opencode; do
    echo "[herdr] installing ${target} integration"
    if ! "$INSTALL_PATH" integration install "$target"; then
        integration_failed="$integration_failed $target"
    fi
done

"$INSTALL_PATH" integration status | grep -E '^(claude|opencode):' || true

if [ -n "$integration_failed" ]; then
    echo "[herdr] WARNING: integration not installed for:${integration_failed}"
    echo "[herdr] herdr itself is installed and usable; /herdr-agents needs these."
    echo "[herdr] re-run: herdr integration install <target>"
fi
