#!/bin/bash
#
# Project setup hook. Runs at the end of postCreateCommand, once, after the
# standard installs (packages, opencode, herdr) and before the firewall comes
# up at postStartCommand.
#
# This file is YOURS. It ships as a no-op and the template never overwrites it,
# so anything this project needs at create time goes here rather than into
# devcontainer.json — which is boilerplate that
# `/project-bootstrap --update-devcontainer` replaces wholesale.
#
# Use packages.txt for anything that is just "install this package". Use this
# file for the things a list cannot express:
#
#   - creating the project's own virtualenv and installing its manifest
#   - fixing ownership or permissions on a mounted directory
#   - generating a config file, seeding a database, building a native module
#   - an installer that has to verify a digest or pick an asset per architecture
#
# BEST-EFFORT by design: postCreateCommand invokes this with `|| echo`, so a
# failure here costs the container its setup and says so in the create log,
# rather than costing you the container. Exit non-zero to signal failure — it
# is reported, not swallowed silently.
#
# Notes that will save you an hour:
#
#   - The firewall is NOT up yet, so network access here is unrestricted. Once
#     it is up, anything this script reached may be blocked; if you need it
#     again later, add the host to firewall-allow.txt.
#   - npm needs the two NVM lines below to be on PATH. They are already
#     exported by postCreateCommand, and repeated here so the script also works
#     when you run it by hand.
#   - `${containerWorkspaceFolder}` is not set here. Use "$WORKSPACE" below.
#
# Run it by hand any time:
#
#     bash .devcontainer/setup.sh

set -euo pipefail

WORKSPACE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export NVM_DIR="${NVM_DIR:-/usr/local/share/nvm}"
export PATH="$NVM_DIR/current/bin:$PATH"

echo "[setup] project setup hook for $(basename "$WORKSPACE")"

# ---------------------------------------------------------------------------
# Add this project's setup below. Everything here is commented out on purpose:
# the template ships this file doing nothing at all.
# ---------------------------------------------------------------------------

# A Python project: its own venv, its own manifest. Per the workspace rule,
# dependencies go into the project's environment, never the machine's.
#
#   python3 -m venv "$WORKSPACE/.venv"
#   "$WORKSPACE/.venv/bin/pip" install -q -e "$WORKSPACE[dev]"

# A Node project:
#
#   (cd "$WORKSPACE" && npm ci)

# A mounted directory holding credentials, which docker creates root-owned:
#
#   sudo chown -R vscode:vscode /home/vscode/.config/my-service
#   chmod 700 /home/vscode/.config/my-service

echo "[setup] nothing to do (edit .devcontainer/setup.sh to add project setup)"
