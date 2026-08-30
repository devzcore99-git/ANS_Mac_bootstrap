#!/usr/bin/env bash
#
# Install sops (https://github.com/getsops/sops), the secrets editor that reads
# the age key bound in at ~/.config/sops.
#
# Run once from postCreateCommand, as `vscode` with passwordless sudo. Not on
# the start path: nothing here has to re-run when a stopped container comes
# back, and it reaches the network, which the firewall has no reason to be
# holding open on every boot.
#
# WHY A SCRIPT AND NOT A LINE IN packages.base.txt
#
# Its companion IS a package line — `apt:age` — because age is in the Ubuntu
# archives. sops is not, in any Ubuntu release, so there is no apt: line to
# write; it ships as a bare binary on GitHub Releases. That is the same shape as
# herdr next door, so it gets the same treatment: pinned by version AND by the
# SHA-256 the project publishes alongside the asset, rather than a `| sh`
# installer or an unpinned "latest". This container mounts live Claude Code
# OAuth credentials at /home/vscode/.claude, the host's GitHub token at
# /home/vscode/.config/gh, and — the reason this script exists at all — a real
# age private key at /home/vscode/.config/sops. Nothing here should be resolved
# at create time from whatever a vendor is publishing that day.
#
# Bumping sops is a deliberate edit to this file: change SOPS_VERSION and BOTH
# digests together, from the release's own checksums file —
#
#   https://github.com/getsops/sops/releases/download/v<VER>/sops-v<VER>.checksums.txt
#
# check.sh fails a bump that changes only one digest, since that passes on the
# machine it was edited on and breaks every create on the other architecture.
#
# The published binaries are statically linked Go builds, so there is nothing to
# install beside them. Both architectures are pinned because the template runs
# on amd64 and on Apple Silicon.
#
# NETWORK: the download is the only step that leaves the container, and it runs
# at create time, before postStartCommand applies the firewall. GitHub's release
# CDN is therefore reachable without an allow-list entry, and nothing is added
# for it — same rule as everywhere else here, a host goes in firewall-allow.txt
# only when it is observed to be blocked. sops itself needs no network at all
# for local age encryption and decryption; it reaches out only for cloud KMS
# backends and for its own version check, which is why the smoke test below
# passes --disable-version-check.
#
# Exits non-zero on any failure. The caller in devcontainer.json deliberately
# does NOT treat that as fatal — a GitHub outage should cost the container sops,
# not the whole create.

set -euo pipefail

# Pinned release. Both digests come from the checksums.txt published with it.
SOPS_VERSION="3.13.3"
SHA256_X86_64="e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b"
SHA256_AARCH64="53b0abacd38ef1b12a66d6c100956691b9cefce018d91f81e73ddf7438b94d77"

# /usr/local/bin for the same two reasons as herdr: it is on PATH for every
# shell and every lifecycle hook without depending on ~/.profile having run,
# which a non-interactive `bash -c` never does, and being root-owned means the
# binary cannot be replaced from inside the container without sudo.
INSTALL_PATH="/usr/local/bin/sops"

arch="$(uname -m)"
case "$arch" in
    x86_64)          asset="linux.amd64"; want_sha="$SHA256_X86_64" ;;
    aarch64 | arm64) asset="linux.arm64"; want_sha="$SHA256_AARCH64" ;;
    *)
        echo "ERROR: no sops build pinned for architecture '$arch'"
        exit 1
        ;;
esac

url="https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.${asset}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[sops] downloading v${SOPS_VERSION} (${asset})"
# --retry rides out a transient 5xx from the release CDN; the timeouts keep a
# hung connection from stalling container create indefinitely.
curl -fsSL --retry 3 --connect-timeout 10 --max-time 180 -o "$tmp/sops" "$url"

# Verify BEFORE anything is made executable or moved onto PATH. sha256sum -c
# exits non-zero on a mismatch, and `set -e` turns that into an aborted install
# with the downloaded file still confined to $tmp.
echo "[sops] verifying SHA-256"
printf '%s  %s\n' "$want_sha" "$tmp/sops" | sha256sum -c -

echo "[sops] installing to ${INSTALL_PATH}"
sudo install -o root -g root -m 0755 "$tmp/sops" "$INSTALL_PATH"

# Smoke test that also catches a pin/asset mismatch. --disable-version-check
# keeps this local: without it sops asks GitHub whether a newer release exists,
# which is a network round trip in the middle of container create and, once the
# firewall is up, a hang for anyone who runs the same command by hand.
installed="$("$INSTALL_PATH" --disable-version-check --version)"
echo "[sops] installed: ${installed}"
case "$installed" in
    *"$SOPS_VERSION"*) ;;
    *)
        echo "ERROR: installed binary reports '${installed}', expected ${SOPS_VERSION}"
        exit 1
        ;;
esac

# The key this is all for arrives as a readonly bind of the host's
# ~/.config/sops (see mounts in devcontainer.json). Report on it rather than
# create anything: an empty mount is a real state — a machine that has no age
# key, or one where the bind source did not exist — and the failure it causes
# later ("no identity matched any of the recipients") is a good deal easier to
# place when the create log already said the directory was empty.
if [ -s "$HOME/.config/sops/age/keys.txt" ]; then
    echo "[sops] age key present: ~/.config/sops/age/keys.txt"
else
    echo "[sops] NOTE: ~/.config/sops/age/keys.txt is missing or empty."
    echo "[sops] Decryption will fail until the host has one. On the HOST:"
    echo "[sops]   mkdir -p ~/.config/sops/age && age-keygen -o ~/.config/sops/age/keys.txt"
    echo "[sops] then Rebuild Container."
fi
