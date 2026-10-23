#!/usr/bin/env bash
#
# Install Node.js from the official release tarball, pinned by version AND by
# SHA-256 per architecture. Run by the Dockerfile at image build, as root.
#
# This replaces the node devcontainer feature. Features cannot be cached by
# DevPod across workspaces, so the feature re-ran on every create; and its
# version was "lts", resolved at build time. Here it is a pinned layer of the
# shared image instead.
#
# WHERE IT GOES, AND WHY THERE
#
# /usr/local/share/nvm/current - the exact path the node feature used, though
# there is no nvm here (no `nvm` command, no nvm.sh). Keeping the path means:
#
#  * every project's setup.sh, and install-packages.sh, already exports
#    NVM_DIR=/usr/local/share/nvm and PATH=$NVM_DIR/current/bin:$PATH - the
#    explicit exports that survive DevPod's PAM reset of PATH in lifecycle
#    hooks. Those keep working unchanged.
#  * the directory is owned by vscode, as the feature's was (through its `nvm`
#    group), so `npm install -g` needs no sudo: packages.txt npm: lines at
#    create, and Claude Code's own auto-updater, behave exactly as before.
#
# node, npm and npx are also linked into /usr/local/bin, so a hook that never
# exported anything still finds node.
#
# Bumping node is a deliberate edit here: NODE_VERSION and BOTH digests,
# from https://nodejs.org/dist/v<VER>/SHASUMS256.txt (the linux-x64 and
# linux-arm64 .tar.xz lines). check.sh fails a bump that changes only one.
#
# Fatal on failure, unlike herdr or sops: node is what npm, Claude Code and
# opencode run on, and an image without it is not usefully built.

set -euo pipefail

NODE_VERSION="24.22.1"
SHA256_X64="6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6"
SHA256_ARM64="dbabf7a1cbf947e6059ffad2c27b80041db97dea1e553b62afdee7f13fca336e"

NVM_DIR="/usr/local/share/nvm"
NODE_DIR="$NVM_DIR/versions/node/v${NODE_VERSION}"

arch="$(uname -m)"
case "$arch" in
    x86_64)          asset="linux-x64";   want_sha="$SHA256_X64" ;;
    aarch64 | arm64) asset="linux-arm64"; want_sha="$SHA256_ARM64" ;;
    *)
        echo "ERROR: no node build pinned for architecture '$arch'"
        exit 1
        ;;
esac

url="https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${asset}.tar.xz"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[node] downloading v${NODE_VERSION} (${asset})"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 300 -o "$tmp/node.tar.xz" "$url"

# Verify BEFORE anything is unpacked, same rule as herdr and sops.
echo "[node] verifying SHA-256"
printf '%s  %s\n' "$want_sha" "$tmp/node.tar.xz" | sha256sum -c -

echo "[node] installing to ${NODE_DIR}"
mkdir -p "$NODE_DIR"
tar -xJf "$tmp/node.tar.xz" -C "$NODE_DIR" --strip-components=1 --no-same-owner
ln -sfn "$NODE_DIR" "$NVM_DIR/current"
for bin in node npm npx; do
    ln -sfn "$NVM_DIR/current/bin/$bin" "/usr/local/bin/$bin"
done
chown -R vscode:vscode "$NVM_DIR"

installed="$("$NVM_DIR/current/bin/node" --version)"
echo "[node] installed: ${installed}"
if [ "$installed" != "v${NODE_VERSION}" ]; then
    echo "ERROR: installed node reports '${installed}', expected v${NODE_VERSION}"
    exit 1
fi
