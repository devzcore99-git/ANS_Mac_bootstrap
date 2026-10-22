# The image every project's devcontainer is built from: the base image plus
# everything the template installs that does not depend on a feature, a mount
# or the project.
#
# WHY THIS EXISTS
#
# These steps used to run in onCreateCommand and postCreateCommand, so every
# create paid for them again - about 20 seconds of apt and downloads per
# container, on every Agent Swarm run, which creates a fresh workspace each
# time. Here they are image layers. The Dockerfile and the files it copies are
# identical in every project, so the build cache is shared across all of them:
# the first project to build pays, everyone after gets a cache hit.
#
# WHAT MAY GO IN, AND WHAT MAY NOT
#
#  * Only template boilerplate. Never COPY packages.txt, setup.sh or
#    firewall-allow.txt (the files in .project-owned): they differ per project,
#    so one of them here gives every project its own image and the shared cache
#    is gone. They keep running at create time. check.sh asserts this.
#  * Nothing that needs a feature. Features (node, python, gh, claude-code) are
#    installed ON TOP of this image, after it is built - so npm and the python
#    feature's pipx do not exist yet. opencode stays in postCreateCommand for
#    exactly that reason, and packages.base.txt is apt-only.
#  * Nothing that writes to $HOME. The build runs as root with no mounts;
#    ~/.claude, ~/.config/sops and the rest only exist in the container. The
#    herdr integrations and the sops key report stay at create time.
#
# FAILURE
#
# The base package list is fail-closed, as it always was: a failure fails the
# build. The three tools are not - each RUN ends in `|| echo`, so a GitHub or
# PyPI outage costs the image that tool, and the same script run bare from
# postCreateCommand installs it at create instead. Know that a failed tool step
# is CACHED like a good one: the image keeps lacking it (and every create keeps
# making up for it) until the layer is rebuilt, e.g. `--no-cache` or a bump.
#
# NETWORK AND SECRETS
#
# A build has no firewall and no mounts, so nothing here needs an allow-list
# entry, and no credential is ever present while vendor code is downloaded -
# stricter than the create path these steps came from, where the Claude Code
# credentials and the gh token were already mounted.
#
# The base image is the same moving :ubuntu tag as before, the owner's decision
# (see CLAUDE.md, Dependencies). Docker keeps the copy it already pulled until a
# build is run with --pull.

FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Build-time only (ARG, not ENV): keeps apt from prompting without leaving the
# variable set in every shell of the finished container.
ARG DEBIAN_FRONTEND=noninteractive

# One COPY per script, each just before the RUN that uses it, so a bump to one
# tool invalidates that layer and the ones after it rather than the whole image.
# Least likely to change first.
COPY packages.base.txt install-packages.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-packages.sh base

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
# pinned. The feature's own `installTools` is switched off in devcontainer.json:
# it re-installed these unpinned on every create, which DevPod cannot cache.
COPY install-python-tools.sh /opt/devcontainer/
RUN bash /opt/devcontainer/install-python-tools.sh --image \
    || echo "[image] WARNING: some python tools not baked in; see the lines above"
