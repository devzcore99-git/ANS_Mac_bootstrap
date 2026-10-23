#!/usr/bin/env bash
#
# Install the GitHub CLI (gh) from its release tarball, pinned by version AND by
# SHA-256 per architecture. Run by the Dockerfile at image build, as root.
#
# This replaces the github-cli devcontainer feature, for the same reason the
# node feature went: DevPod re-ran it on every create, and it installed
# whatever release was current that day. Authentication is unchanged - it comes
# from the readonly ~/.config/gh bind in devcontainer.json, which gh reads at
# run time; nothing about it is in the image.
#
# Bumping gh is a deliberate edit here: GH_VERSION and BOTH digests, from the
# release's gh_<VER>_checksums.txt (the linux_amd64 and linux_arm64 .tar.gz
# lines). check.sh fails a bump that changes only one.
#
# Fatal on failure, as the feature was: gh is how every project here talks to
# GitHub, and git's credential helper goes through it.

set -euo pipefail

GH_VERSION="2.103.0"
SHA256_AMD64="fdd768eb70f6409f80fcfa9f3a1c0adf0fc98d827ab3ce0bed2ac22762c5d786"
SHA256_ARM64="7f322df34e624d14f5ec0c4acb121fd6dfa14392fdbbd1066aa8e0a05ac3721e"

# Root-owned in /usr/local/bin, like herdr and sops: on PATH for every hook,
# and not replaceable from inside the container without sudo.
INSTALL_PATH="/usr/local/bin/gh"

arch="$(uname -m)"
case "$arch" in
    x86_64)          asset="linux_amd64"; want_sha="$SHA256_AMD64" ;;
    aarch64 | arm64) asset="linux_arm64"; want_sha="$SHA256_ARM64" ;;
    *)
        echo "ERROR: no gh build pinned for architecture '$arch'"
        exit 1
        ;;
esac

name="gh_${GH_VERSION}_${asset}"
url="https://github.com/cli/cli/releases/download/v${GH_VERSION}/${name}.tar.gz"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[gh] downloading v${GH_VERSION} (${asset})"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 180 -o "$tmp/gh.tar.gz" "$url"

echo "[gh] verifying SHA-256"
printf '%s  %s\n' "$want_sha" "$tmp/gh.tar.gz" | sha256sum -c -

tar -xzf "$tmp/gh.tar.gz" -C "$tmp"
echo "[gh] installing to ${INSTALL_PATH}"
install -o root -g root -m 0755 "$tmp/$name/bin/gh" "$INSTALL_PATH"

installed="$("$INSTALL_PATH" --version | head -1)"
echo "[gh] installed: ${installed}"
case "$installed" in
    *" ${GH_VERSION} "*) ;;
    *)
        echo "ERROR: installed gh reports '${installed}', expected ${GH_VERSION}"
        exit 1
        ;;
esac
