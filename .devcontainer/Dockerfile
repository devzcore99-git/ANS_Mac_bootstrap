# The image every project's devcontainer runs: the base image plus everything
# the template installs that does not depend on a mount or on the project.
#
# WHY THIS EXISTS
#
# It is built ONCE PER MACHINE by build-image.sh (run from initializeCommand)
# and tagged dev-template:<hash of these files>; devcontainer.json names that
# tag in "image". So DevPod builds nothing: every container starts from the one
# local image, which Docker stores once however many projects use it.
#
# It used to be a base image plus four devcontainer features, re-installed on
# every create. DevPod cannot cache feature layers across workspaces - each
# workspace copies in its own generated feature folder, which busts every step
# after it - so each new workspace paid ~85 s for them, plus ~28 s exporting a
# ~3 GB image of its own, on every Agent Swarm run. The features are now steps
# below (node, gh, claude-code, python), each pinned:
#
#   node         install-node.sh       version + SHA-256 per architecture
#   gh           install-gh.sh         version + SHA-256 per architecture
#   claude-code  npm, below            exact version
#   python       packages.base.txt     Ubuntu archive (python3-pip/-venv/-dev)
#
# WHAT MAY GO IN, AND WHAT MAY NOT
#
#  * Only template boilerplate. Never COPY packages.txt, setup.sh or
#    firewall-allow.txt (the files in .project-owned): they differ per project,
#    and the image is shared. They keep running at create time. check.sh
#    asserts this.
#  * Nothing that writes to $HOME or needs a mount. The build runs with no
#    mounts; ~/.claude, ~/.config/sops and the rest only exist in the
#    container. The herdr integrations and the sops key report stay at create.
#
# FAILURE
#
# What the features did is fail-closed, as the features were: base packages,
# node, gh, claude-code. A failure fails the build. The other tools are not -
# each RUN ends in `|| echo`, so a GitHub, npm or PyPI outage costs the image
# that tool, and the same script run bare from postCreateCommand installs or
# reports it at create. A failed tool step is CACHED like a good one, until the
# layer is rebuilt (`build-image.sh --rebuild`) or a bump changes the tag.
#
# NETWORK AND SECRETS
#
# A build has no firewall and no mounts, so nothing here needs an allow-list
# entry, and no credential is ever present while vendor code is downloaded.
#
# The base image is the same moving :ubuntu tag as before, the owner's decision
# (see CLAUDE.md, Dependencies). Docker keeps the copy it already pulled until a
# build is run with --pull.

FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Build-time only (ARG, not ENV): keeps apt from prompting without leaving the
# variable set in every shell of the finished container.
ARG DEBIAN_FRONTEND=noninteractive

# Where node lives - the node feature's own path, kept so every existing
# `export NVM_DIR=... PATH=$NVM_DIR/current/bin:$PATH` keeps working. See
# install-node.sh.
ENV NVM_DIR=/usr/local/share/nvm
ENV PATH=/usr/local/share/nvm/current/bin:${PATH}

# One COPY per script, each just before the RUN that uses it, so a bump to one
# tool invalidates that layer and the ones after it rather than the whole image.
# Least likely to change first.
COPY packages.base.txt install-packages.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-packages.sh base

COPY install-node.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-node.sh

COPY install-gh.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-gh.sh

# The npm CLIs install AS vscode, into the vscode-owned node prefix - so Claude
# Code's auto-updater, and any `npm install -g` at create, can still write
# there, exactly as under the node feature. A private cache keeps npm's
# download cache out of the layer.
USER vscode
RUN npm install -g --cache /tmp/npm-cache @anthropic-ai/claude-code@2.1.308 \
    && rm -rf /tmp/npm-cache
RUN { npm install -g --cache /tmp/npm-cache opencode-ai@1.18.16 \
      || echo "[image] WARNING: opencode not baked in; postCreateCommand will install it"; } \
    && rm -rf /tmp/npm-cache
USER root

COPY install-sops.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-sops.sh --binary-only \
    || echo "[image] WARNING: sops not baked in; postCreateCommand will install it"

COPY install-herdr.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-herdr.sh --binary-only \
    || echo "[image] WARNING: herdr not baked in; postCreateCommand will install it"

COPY install-graphify.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-graphify.sh --image \
    || echo "[image] WARNING: graphify not baked in; postCreateCommand will install it"

# The python feature's default tool set (flake8, black, mypy, pytest, ...),
# pinned - what the feature's `installTools` used to install, unpinned, on
# every create.
COPY install-python-tools.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-python-tools.sh --image \
    || echo "[image] WARNING: some python tools not baked in; see the lines above"
