#!/bin/bash
#
# Install the packages named in the two package files beside this script.
#
# This script carries NO package names. They live in:
#
#   packages.base.txt   the template's own set - the firewall's tooling.
#                       Boilerplate, refreshed from DEV-TEMPLATE. FAIL-CLOSED:
#                       a failure here aborts the create, because a container
#                       that cannot raise its firewall is not usefully built.
#   packages.txt        this project's additions. The only package file a
#                       project edits. BEST-EFFORT: a failure prints a warning
#                       naming the file and line and the create continues, so a
#                       typo costs a package rather than a container.
#
# Same split, same reasoning, and the same file format as firewall-allow.txt
# next to it. A project that needs another package adds a line to a text file,
# never an edit to devcontainer.json or to this script - both are boilerplate
# that /project-bootstrap --update-devcontainer overwrites.
#
# Line format: `installer:package`, one per line, `#` to end of line for
# comments, blank lines ignored. Three installers:
#
#   apt:ripgrep              a system package (apt-get install)
#   npm:typescript@5.4.5     a global npm package (npm install -g)
#   pip:ruff==0.6.9          a Python package (python3 -m pip install)
#
# The prefix is required. It is what lets one line say everything - which is
# also why a diff or an error message about a single line is self-explanatory.
#
# Runs from onCreateCommand, which is AFTER devcontainer features are installed
# (so node and python exist) and BEFORE postStartCommand raises the firewall
# (so nothing here needs an allow-list entry). Once the firewall is up, apt and
# the registries still work - archive.ubuntu.com, registry.npmjs.org and
# pypi.org are in firewall-allow.base.txt - but a package from anywhere else
# needs a matching line in firewall-allow.txt, or it hangs on connect.
#
# Not everything belongs here. Anything with real logic - creating a venv,
# fixing permissions on a mounted directory, an installer that verifies a
# digest - goes in setup.sh, which runs from postCreateCommand.

set -uo pipefail   # NOT -e: this script decides per line what is fatal.
IFS=$'\n\t'

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE_FILE="$SCRIPT_DIR/packages.base.txt"
PROJECT_FILE="$SCRIPT_DIR/packages.txt"

APT=()
NPM=()
PIP=()
WARNINGS=0

# npm arrives via the node devcontainer feature, which puts it under NVM rather
# than on the default PATH. Same two lines postCreateCommand uses.
export NVM_DIR="${NVM_DIR:-/usr/local/share/nvm}"
export PATH="$NVM_DIR/current/bin:$PATH"

problem() {
    local strict="$1" label="$2" lineno="$3" message="$4"
    if [ "$strict" = "true" ]; then
        echo "ERROR: $message"
        echo "       $label line $lineno"
        exit 1
    fi
    echo "WARNING: $message"
    echo "         $label line $lineno"
    echo "         continuing; that package will NOT be installed"
    WARNINGS=$((WARNINGS + 1))
}

# Collect rather than install line by line: apt in particular must go in one
# transaction, both because it is far faster and because installing packages
# one at a time can fail on interdependencies that resolve fine together.
read_package_file() {
    local file="$1" strict="$2"
    local label lineno=0 line entry installer package
    label=$(basename "$file")

    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))
        entry="${line%%#*}"
        entry="${entry#"${entry%%[![:space:]]*}"}"
        entry="${entry%"${entry##*[![:space:]]}"}"
        [ -z "$entry" ] && continue

        installer="${entry%%:*}"
        package="${entry#*:}"
        if [ "$installer" = "$entry" ] || [ -z "$package" ]; then
            problem "$strict" "$label" "$lineno" \
                "missing installer prefix: '$entry' (expected apt:, npm: or pip:)"
            continue
        fi
        # Anchored allow-list of characters. These strings reach a
        # root-privileged create step, so a name is accepted only if it looks
        # like a package name and nothing else. No spaces, quotes, backticks,
        # $, ;, & or | can appear, which is what keeps the expansions below
        # from being anything other than package names.
        #
        # The punctuation that IS allowed is all version-specifier syntax the
        # three installers really use: `npm:typescript@5.4.5`,
        # `pip:ruff==0.6.9`, `pip:django>=4,<5`, `pip:package[extra]`,
        # `pip:foo~=1.2`, `apt:libfoo-dev`. An earlier form of this pattern
        # omitted `=` and rejected every pinned pip entry, including the
        # examples shipped in packages.txt.
        #
        # `][` leads the second bracket expression on purpose: a `]` is literal
        # only in first position, and `-` is literal only in last.
        if [[ ! "$package" =~ ^[A-Za-z0-9][][A-Za-z0-9._@/+~!\<\>=,-]*$ ]]; then
            problem "$strict" "$label" "$lineno" \
                "not a valid package name: '$package'"
            continue
        fi
        case "$installer" in
            apt) APT+=("$package") ;;
            npm) NPM+=("$package") ;;
            pip) PIP+=("$package") ;;
            *)   problem "$strict" "$label" "$lineno" \
                     "unknown installer '$installer:' (expected apt:, npm: or pip:)" ;;
        esac
    done < "$file"
}

# Runs one installer and applies this file's strictness rule to the result.
# The command is passed as separate arguments and invoked as `"$@"`, never
# assembled into a string for a shell, so a package name is only ever one
# argument however it is punctuated.
run_installer() {
    local what="$1" strict="$2"
    shift 2
    echo "[packages] $what: $*"
    if "$@"; then
        return 0
    fi
    if [ "$strict" = "true" ]; then
        echo "ERROR: $what failed, and it is in packages.base.txt - aborting."
        exit 1
    fi
    echo "WARNING: $what failed. The container is otherwise ready; install by"
    echo "         hand, or fix the entry in packages.txt and rebuild."
    WARNINGS=$((WARNINGS + 1))
}

install_collected() {
    local strict="$1"
    if [ ${#APT[@]} -gt 0 ]; then
        run_installer "apt-get update" "$strict" sudo apt-get update
        run_installer "apt-get install" "$strict" \
            sudo apt-get install -y --no-install-recommends "${APT[@]}"
    fi
    if [ ${#NPM[@]} -gt 0 ]; then
        run_installer "npm install -g" "$strict" npm install -g "${NPM[@]}"
    fi
    if [ ${#PIP[@]} -gt 0 ]; then
        run_installer "pip install" "$strict" python3 -m pip install "${PIP[@]}"
    fi
    APT=(); NPM=(); PIP=()
}

if [ ! -f "$BASE_FILE" ]; then
    echo "ERROR: Missing $BASE_FILE"
    echo "       It carries the firewall's own tooling; without it the container"
    echo "       cannot raise its egress policy. Restore it from DEV-TEMPLATE."
    exit 1
fi

# Two passes rather than one combined transaction, so the base set keeps its
# fail-closed behaviour even when a project entry is broken. A single apt call
# holding both would fail as a unit and take the base packages down with it.
echo "[packages] reading $BASE_FILE"
read_package_file "$BASE_FILE" true
install_collected true

if [ -f "$PROJECT_FILE" ]; then
    echo "[packages] reading $PROJECT_FILE"
    read_package_file "$PROJECT_FILE" false
    install_collected false
else
    echo "[packages] no $PROJECT_FILE - template set only"
fi

if [ "$WARNINGS" -gt 0 ]; then
    echo "[packages] done with $WARNINGS warning(s) - see above; those packages"
    echo "[packages] are NOT installed"
else
    echo "[packages] done"
fi
