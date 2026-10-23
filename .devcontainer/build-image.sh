#!/usr/bin/env bash
#
# Build this template's container image, once per machine, under a fixed tag.
#
# Run on the HOST by initializeCommand, before DevPod or VS Code look for the
# image named by "image" in devcontainer.json. When an image with that tag
# already exists it does nothing and returns at once - the normal case, and
# the point: no project builds anything, every container on the machine starts
# from the same local image, and Docker stores it once however many projects
# use it.
#
# THE TAG IS THE CONTENT
#
# dev-template:<first 12 hex of a SHA-256 over the Dockerfile and every file it
# COPYs>. Change any of them and the tag changes, so a template edit can never
# be served from a stale image that happens to carry the old name. The tag in
# devcontainer.json is a literal (DevPod reads it before any script runs), so a
# template edit means updating that literal too:
#
#     .devcontainer/build-image.sh --print-tag
#
# This script refuses to build when the literal and the content disagree, and
# check.sh fails on it, so the two cannot drift silently.
#
# Images for older tags are left in place: a project not yet refreshed still
# names one. `docker image ls dev-template` lists them; remove any that no
# container uses.
#
#   --print-tag   print the tag the current files produce, build nothing
#   --rebuild     build again with --no-cache even if the tag exists - for an
#                 image whose non-fatal tool step failed, since that failure
#                 is cached like a success and a plain rebuild reuses it
#
# Needs only docker and a SHA-256 tool on the host (sha256sum on Linux,
# shasum on macOS).

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="dev-template"

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi
}

# The Dockerfile plus each COPY source, in Dockerfile order. Names go into the
# hash as well as contents, so renaming a file changes the tag too.
inputs() {
    echo Dockerfile
    awk '/^COPY[[:space:]]/ { for (i = 2; i < NF; i++) print $i }' "$DIR/Dockerfile"
}

compute_tag() {
    local f
    for f in $(inputs); do
        printf '%s\n' "$f"
        cat "$DIR/$f"
    done | sha256 | cut -c1-12
}

tag="$REPO:$(compute_tag)"

if [ "${1:-}" = "--print-tag" ]; then
    echo "$tag"
    exit 0
fi

wanted="$(sed -nE 's/^[[:space:]]*"image"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' \
    "$DIR/devcontainer.json" | head -1)"
if [ "$wanted" != "$tag" ]; then
    echo "ERROR: devcontainer.json names image '${wanted:-<none>}', but the files in"
    echo "       .devcontainer/ produce '$tag'. A template file changed without the"
    echo "       tag being updated. Set \"image\" to \"$tag\"."
    exit 1
fi

if [ "${1:-}" = "--rebuild" ]; then
    echo "[image] rebuilding $tag without cache"
    exec docker build --no-cache -t "$tag" "$DIR"
fi

if docker image inspect "$tag" >/dev/null 2>&1; then
    echo "[image] $tag present"
    exit 0
fi

echo "[image] building $tag - once per machine, a few minutes"
docker build -t "$tag" "$DIR"
