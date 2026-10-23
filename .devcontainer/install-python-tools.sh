#!/usr/bin/env bash
#
# Install the Python developer tools - linters, formatters, test runner and
# environment managers - each in its own pipx venv, pinned.
#
# Run at image build (Dockerfile, as root, with --image) and again from
# postCreateCommand (as `vscode`) - see "Two callers" below.
#
# WHY THIS IS NOT THE PYTHON FEATURE'S JOB ANY MORE
#
# The python feature installs this same set when its `installTools` option is
# on, which is its default. It did so at create time, on every create: DevPod
# cannot cache feature layers across workspaces (each workspace copies in its
# own generated feature folder, which busts every step after it), so these
# twelve tools cost about 40 seconds of every new container - on every Agent
# Swarm run. They also floated: the feature installs whatever PyPI has that
# day, so two containers built on different days had different linters, against
# this template's "pinned, never floating" rule. The template has since dropped
# the python feature altogether (see the Dockerfile), and this script installs
# the same twelve here, pinned, into the shared image.
#
# These are machine-level CLIs, the same tools the feature put on PATH. A
# project that needs a specific version of one as a LIBRARY - a pytest plugin,
# a mypy pinned to its own codebase - still puts it in its own .venv, per the
# workspace rules; that venv's copy wins whenever the venv is active.
#
# Bumping one is a deliberate edit to TOOLS below, from https://pypi.org/.
#
# NETWORK: the downloads run at image build, which has no firewall. A hand
# re-run inside a container also works with the firewall up - pypi.org and
# files.pythonhosted.org are in firewall-allow.base.txt.
#
# Exits non-zero when anything is missing or off-pin. Both callers deliberately
# do NOT treat that as fatal - a PyPI outage should cost the image its linters,
# not the build.

set -euo pipefail

# Pinned. The set is the python feature's own `toolsToInstall` default, so
# dropping the feature removed nothing anyone had.
TOOLS=(
    "flake8==7.4.1"
    "autopep8==2.3.2"
    "black==26.10.1"
    "yapf==0.43.0"
    "mypy==2.4.0"
    "pydocstyle==6.3.0"
    "pycodestyle==2.15.0"
    "bandit==1.9.4"
    "pipenv==2026.10.2"
    "virtualenv==21.14.12"
    "pytest==9.1.1"
    "pylint==4.1.3"
)

# The image's pipx tree, shared with install-graphify.sh. Fixed paths rather
# than PIPX_HOME from the environment, which a project may set for its own use.
export PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin

# Two callers, one script. The Dockerfile runs it with --image, as root, before
# any feature exists - so pipx comes from the Ubuntu archive, as it does for
# graphify. postCreateCommand runs it bare, which only checks: every tool
# present at its pin, or a WARNING naming the ones that are not. It does not
# install at create: the pipx tree is root's, and twelve tools at create is the
# 40 seconds this exists to remove; a failed image step is fixed by rebuilding
# the image.
if [ "${1:-}" = "--image" ]; then
    if ! command -v pipx >/dev/null 2>&1; then
        echo "[python-tools] installing pipx from the Ubuntu archive"
        apt-get install -y --no-install-recommends pipx
    fi
    failed=""
    for spec in "${TOOLS[@]}"; do
        echo "[python-tools] installing ${spec}"
        # --force so a re-run puts the pin back over whatever is there. Each
        # tool may fail on its own: one bad release should not cost the other
        # eleven.
        pipx install --force "$spec" >/dev/null || failed="$failed ${spec%%==*}"
    done
    if [ -n "$failed" ]; then
        echo "[python-tools] WARNING: not installed:${failed}"
        exit 1
    fi
fi

# Verify against pipx's own record, not `<tool> --version`: the twelve print
# their versions in twelve formats, and pipx list --json is one.
installed="$(pipx list --json 2>/dev/null || echo '{}')"
off_pin=""
for spec in "${TOOLS[@]}"; do
    name="${spec%%==*}" want="${spec#*==}"
    have="$(printf '%s' "$installed" |
        jq -r --arg n "$name" '.venvs[$n].metadata.main_package.package_version // empty')"
    [ "$have" = "$want" ] || off_pin="$off_pin $name(${have:-missing})"
done
if [ -n "$off_pin" ]; then
    echo "[python-tools] WARNING: not at their pins:${off_pin}"
    echo "[python-tools]          on the HOST: .devcontainer/build-image.sh --rebuild,"
    echo "[python-tools]          then Rebuild Container"
    exit 1
fi
echo "[python-tools] all ${#TOOLS[@]} tools present at their pins"
