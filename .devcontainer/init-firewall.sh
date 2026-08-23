#!/bin/bash
#
# Default-DROP egress firewall for the dev container.
#
# Builds an ipset allow-list from GitHub's published IP ranges plus two text
# files beside this script, sets the default OUTPUT policy to DROP, then
# verifies that a disallowed host is blocked and an allowed one is reachable.
#
# This script carries NO host names. They live in:
#
#   firewall-allow.base.txt   the template's own set (npm, PyPI, the Anthropic
#                             API, the Ubuntu archives, VS Code, the LAN the
#                             local LLM is on). Boilerplate. Fail-closed.
#   firewall-allow.txt        this project's additions. The only file here a
#                             project edits. Best-effort: a bad entry warns
#                             rather than blocking the boot.
#
# So a project that needs another host adds a line to a text file, and this
# script stays byte-identical everywhere and can be refreshed without a merge.
#
# The allow-list is IPv4-only, so IPv6 is denied outright rather than left at
# its default ACCEPT — see the ip6tables block below.
#
# DNS is allowed only to the container's own resolver, the private LAN, and
# 1.1.1.1/8.8.8.8 — not to any destination — so port 53 is not left open as an
# egress channel.
#
# Toggle lives in devcontainer.json (`INIT_FIREWALL`, default "true"); the
# postStartCommand only invokes this script when the firewall is enabled.
# Running this script directly ALWAYS applies the firewall, regardless of that
# variable — that is the intended way to (re)apply it by hand.
#
# Requires: root (via sudo), NET_ADMIN + NET_RAW capabilities (runArgs), and
# iptables/ipset/dnsutils/aggregate/jq/iproute2 (installed by onCreateCommand).
#
# Strict by design: any failure aborts with a non-zero exit so the container is
# never left with a half-applied policy. If a transient failure (DNS, GitHub
# rate-limit) bricks startup, set INIT_FIREWALL=false in devcontainer.json to
# boot without it.

set -euo pipefail  # Exit on error, undefined vars, and pipeline failures
IFS=$'\n\t'        # Stricter word splitting

# 1. Extract Docker DNS info BEFORE any flushing
DOCKER_DNS_RULES=$(iptables-save -t nat | grep "127\.0\.0\.11" || true)

# Flush existing rules and delete existing ipsets
iptables -F
iptables -X
iptables -t nat -F
iptables -t nat -X
iptables -t mangle -F
iptables -t mangle -X

# Reset the chain policies too. `-F` deletes rules; the policy of a built-in
# chain is a separate attribute that only `-P` changes, so without these three
# lines the flush above is only half a reset.
#
# On a first boot that is invisible — the chains are in a fresh network
# namespace at the kernel default of ACCEPT. On a re-run inside a container that
# already has this firewall, `-P OUTPUT DROP` from line ~245 of the previous run
# survives the flush that just deleted every ACCEPT rule, and the container has
# a default-deny policy with no exceptions from here on. The GitHub fetch below
# then hangs on a black-holed SYN (the fast-fail REJECT was flushed too) and the
# script exits, leaving no egress at all.
#
# That is not a hypothetical path: it is the documented one. The header above
# calls a direct run "the intended way to (re)apply it by hand", and README's
# firewall section names it as the fix for a stale allow-list. It also fires
# whenever postStartCommand runs against a container that is already up, e.g.
# reopening the folder without stopping it. (A full stop/start gets a new
# network namespace and so starts clean.)
#
# Resetting to ACCEPT restores exactly the state a first boot finds, which makes
# the run idempotent. It does leave egress unrestricted between here and the
# `-P ... DROP` below — the same window that already exists between container
# start and postStartCommand. Closing that too means building the ruleset in a
# temp file and applying it with a single atomic `iptables-restore`.
#
# The ip6tables block further down does not need this: it re-asserts its
# policies unconditionally after flushing, so it already converges on a re-run.
iptables -P INPUT ACCEPT
iptables -P FORWARD ACCEPT
iptables -P OUTPUT ACCEPT

ipset destroy allowed-domains 2>/dev/null || true

# 2. Selectively restore ONLY internal Docker DNS resolution
if [ -n "$DOCKER_DNS_RULES" ]; then
    echo "Restoring Docker DNS rules..."
    iptables -t nat -N DOCKER_OUTPUT 2>/dev/null || true
    iptables -t nat -N DOCKER_POSTROUTING 2>/dev/null || true
    echo "$DOCKER_DNS_RULES" | xargs -L 1 iptables -t nat
else
    echo "No Docker DNS rules to restore"
fi

# 3. Deny IPv6 outright — this firewall is IPv4-only.
#
# Every other rule here programs iptables, which governs the IPv4 stack alone.
# Left untouched, the IPv6 stack keeps its default ACCEPT policy with no rules
# at all, so a dual-stack destination is simply reached over AAAA and the
# allow-list below is decorative. The container only gets IPv6 when the Docker
# daemon or network is configured for it, but the policy has to say so rather
# than depend on that.
#
# Filtered, not disabled: `sysctl net.ipv6.conf.all.disable_ipv6=1` would also
# strip ::1 from loopback and break tooling that binds it. Loopback stays open
# here, and the OUTPUT chain ends in REJECT rather than relying on the DROP
# policy so a stray IPv6 connect fails immediately and falls back to IPv4
# instead of stalling until timeout.
#
# Applied before the ipset work below so the deny is in force even if a later
# step aborts the script.
if [ ! -d /proc/sys/net/ipv6 ]; then
    echo "IPv6 unavailable in this kernel - nothing to block"
elif ! command -v ip6tables >/dev/null 2>&1 || ! ip6tables -L -n >/dev/null 2>&1; then
    echo "ERROR: IPv6 is enabled in this kernel but ip6tables is unusable;"
    echo "       cannot enforce the IPv4-only policy"
    exit 1
else
    echo "Blocking all IPv6 traffic..."
    ip6tables -F
    ip6tables -X
    ip6tables -t mangle -F 2>/dev/null || true
    ip6tables -t mangle -X 2>/dev/null || true
    ip6tables -P INPUT DROP
    ip6tables -P FORWARD DROP
    ip6tables -P OUTPUT DROP
    ip6tables -A INPUT -i lo -j ACCEPT
    ip6tables -A OUTPUT -o lo -j ACCEPT
    ip6tables -A OUTPUT -j REJECT --reject-with adm-prohibited
fi

# First allow DNS and localhost before any restrictions
#
# DNS is restricted to a fixed set of resolvers rather than allowed to any
# destination: port 53 open to the whole internet is a working egress channel
# through an attacker-controlled nameserver, which undercuts the point of an
# allow-list. The set is the container's own resolver (read from resolv.conf,
# since it is 127.0.0.11 under Docker's default bridge but the host resolver
# under --network=host), the private LAN, and the two public resolvers below.
#
# TCP as well as UDP: resolvers fall back to TCP/53 for truncated answers, and
# large or DNSSEC-signed responses are exactly the case that truncates. The
# script's own dig calls do not hit this — they run before the policy flips to
# DROP — so a UDP-only rule fails at runtime, looking like a flaky network.
DNS_SRV=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf || true)
if [ -z "$DNS_SRV" ]; then
    echo "ERROR: No nameserver in /etc/resolv.conf; cannot scope the DNS rules"
    exit 1
fi
echo "Container resolver detected as: $DNS_SRV"

for dns in \
    "$DNS_SRV" \
    "192.168.0.0/16" \
    "1.1.1.1" \
    "8.8.8.8"; do
    echo "Allowing DNS to $dns"
    # Allow outbound DNS
    iptables -A OUTPUT -p udp -d "$dns" --dport 53 -j ACCEPT
    iptables -A OUTPUT -p tcp -d "$dns" --dport 53 -j ACCEPT
    # Allow inbound DNS responses
    iptables -A INPUT -p udp -s "$dns" --sport 53 -j ACCEPT
    iptables -A INPUT -p tcp -s "$dns" --sport 53 -j ACCEPT
done

# No blanket port-22 rule here, deliberately.
#
# An unrestricted `-p tcp --dport 22 -j ACCEPT` is a tunnel straight out of a
# default-DROP policy — `ssh -D`, `ssh -W`, `ssh host 'cat > exfil'` — and this
# container mounts live Claude Code OAuth credentials at /home/vscode/.claude
# and the host's GitHub token at /home/vscode/.config/gh.
#
# Nothing is lost by dropping it: SSH is governed by the same ipset as
# everything else, and the ipset match below carries no port constraint, so
# git-over-SSH to GitHub still works via the ranges from api.github.com/meta.
# A non-GitHub SSH host goes in an allow-list file, not back in here.

# Allow localhost
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Create ipset with CIDR support
ipset create allowed-domains hash:net

# Fetch GitHub meta information and aggregate + add their IP ranges
echo "Fetching GitHub IP ranges..."
# `|| true` so the guard below is reachable. Under `set -e` an assignment takes
# the exit status of its command substitution, so a failing curl kills the
# script here and the error message never prints — on a fail-closed boot path
# that is a container refusing to start with no reason given. Same idiom as
# lines 35 and 106, and repeated at the two substitutions further down.
gh_ranges=$(curl -s https://api.github.com/meta || true)
if [ -z "$gh_ranges" ]; then
    echo "ERROR: Failed to fetch GitHub IP ranges"
    exit 1
fi

if ! echo "$gh_ranges" | jq -e '.web and .api and .git' >/dev/null; then
    echo "ERROR: GitHub API response missing required fields"
    exit 1
fi

echo "Processing GitHub IPs..."
while read -r cidr; do
    if [[ ! "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$ ]]; then
        echo "ERROR: Invalid CIDR range from GitHub meta: $cidr"
        exit 1
    fi
    echo "Adding GitHub range $cidr"
    # -exist: re-adding an already-present element is a no-op instead of a
    # non-zero exit (would otherwise kill the script under `set -e`).
    ipset add allowed-domains "$cidr" -exist
done < <(echo "$gh_ranges" | jq -r '(.web + .api + .git)[]' | aggregate -q)

# Resolve and add the allow-list files
#
# Two files, both in this directory, read in this order:
#
#   firewall-allow.base.txt  the template's own set - npm, PyPI, the Anthropic
#                            API, the Ubuntu archives, VS Code, the LAN segment
#                            the local LLM is on. Boilerplate; refreshed from
#                            DEV-TEMPLATE. FAIL-CLOSED: a bad or unresolvable
#                            entry aborts the boot, because a container without
#                            npm or the Anthropic API has not usefully started.
#
#   firewall-allow.txt       what THIS project needs on top. The only file in
#                            .devcontainer/ a project is meant to edit, and the
#                            reason the script itself carries no host names.
#                            BEST-EFFORT: a bad or unresolvable entry warns,
#                            naming file and line, and the boot continues with
#                            that host blocked. Optional - absent is normal.
#
# The split is the whole point. A project extends the firewall by adding a line
# to a text file, never by editing this script, so this script stays identical
# across every project and can be refreshed without a merge.
#
# Format (both files): one entry per line, a domain name, a bare IPv4 address,
# or an IPv4 CIDR; `#` starts a comment to end of line; blank lines ignored.
ALLOW_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE_ALLOW_FILE="$ALLOW_DIR/firewall-allow.base.txt"
PROJECT_ALLOW_FILE="$ALLOW_DIR/firewall-allow.txt"

# Anchored and complete, because these decide what a root script feeds to ipset
# and dig. A label is 1-63 of [A-Za-z0-9-] not starting or ending with a hyphen;
# at least one dot is required, so a bare word cannot be mistaken for a host.
HOSTNAME_RE='^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'
IPV4_RE='^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'
CIDR_RE='^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$'

ALLOW_WARNINGS=0

# Report a bad entry: fatal in a strict (base) file, a warning in a project one.
allow_problem() {
    local strict="$1" label="$2" lineno="$3" message="$4"
    if [ "$strict" = "true" ]; then
        echo "ERROR: $message"
        echo "       $label line $lineno"
        exit 1
    fi
    echo "WARNING: $message"
    echo "         $label line $lineno"
    echo "         continuing; traffic to it will be BLOCKED"
    ALLOW_WARNINGS=$((ALLOW_WARNINGS + 1))
}

# Add one entry to the ipset. A literal address or CIDR goes straight in; a
# domain is resolved first and every A record is added.
allow_entry() {
    local entry="$1" strict="$2" label="$3" lineno="$4"
    local ips ip

    if [[ "$entry" =~ $CIDR_RE ]] || [[ "$entry" =~ $IPV4_RE ]]; then
        echo "Adding $entry"
        # -exist: re-adding an already-present element is a no-op instead of a
        # non-zero exit (would otherwise kill the script under `set -e`).
        ipset add allowed-domains "$entry" -exist
        return 0
    fi

    if [[ ! "$entry" =~ $HOSTNAME_RE ]]; then
        allow_problem "$strict" "$label" "$lineno" \
            "not a domain name, IPv4 address, or IPv4 CIDR: '$entry'"
        return 0
    fi

    echo "Resolving $entry..."
    # `|| true` on the pipeline: dig exits 9 when no server replies, and
    # pipefail would propagate it before the guard runs - losing the one message
    # that says *which* domain stalled. The -z test already covers the result.
    ips=$(dig +noall +answer A "$entry" | awk '$4 == "A" {print $5}' || true)
    if [ -z "$ips" ]; then
        allow_problem "$strict" "$label" "$lineno" "failed to resolve '$entry'"
        return 0
    fi

    while read -r ip; do
        if [[ ! "$ip" =~ $IPV4_RE ]]; then
            allow_problem "$strict" "$label" "$lineno" \
                "invalid IP from DNS for '$entry': $ip"
            continue
        fi
        echo "Adding $ip for $entry"
        # -exist: domains behind a shared CDN (Fastly, Cloudflare) resolve to
        # overlapping IPs; without this, the second add fails and aborts.
        ipset add allowed-domains "$ip" -exist
    done < <(echo "$ips")
}

# Read one allow-list file. `|| [ -n "$line" ]` so a final line with no trailing
# newline is still processed rather than silently dropped - the single likeliest
# way a hand-edited entry goes missing without any error.
read_allow_file() {
    local file="$1" strict="$2"
    local label lineno=0 line entry
    label=$(basename "$file")

    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))
        entry="${line%%#*}"                              # strip comment
        entry="${entry#"${entry%%[![:space:]]*}"}"       # trim leading space
        entry="${entry%"${entry##*[![:space:]]}"}"       # trim trailing space
        [ -z "$entry" ] && continue
        allow_entry "$entry" "$strict" "$label" "$lineno"
    done < "$file"
}

if [ ! -f "$BASE_ALLOW_FILE" ]; then
    echo "ERROR: Missing $BASE_ALLOW_FILE"
    echo "       This file carries the template's own allow-list; without it the"
    echo "       container would start with only GitHub reachable. Restore it from"
    echo "       DEV-TEMPLATE rather than booting with INIT_FIREWALL=false."
    exit 1
fi

echo "Reading template allow-list: $BASE_ALLOW_FILE"
read_allow_file "$BASE_ALLOW_FILE" true

if [ -f "$PROJECT_ALLOW_FILE" ]; then
    echo "Reading project allow-list: $PROJECT_ALLOW_FILE"
    read_allow_file "$PROJECT_ALLOW_FILE" false
else
    echo "No project allow-list at $PROJECT_ALLOW_FILE - template set only"
fi

# Get host IP from default route
# `|| true`: grep exits 1 when there is no default route at all, which pipefail
# turns into a silent abort instead of the message below.
HOST_IP=$(ip route | grep default | cut -d" " -f3 || true)
if [ -z "$HOST_IP" ]; then
    echo "ERROR: Failed to detect host IP"
    exit 1
fi

HOST_NETWORK=$(echo "$HOST_IP" | sed "s/\.[0-9]*$/.0\/24/")
echo "Host network detected as: $HOST_NETWORK"

# Set up remaining iptables rules
iptables -A INPUT -s "$HOST_NETWORK" -j ACCEPT
iptables -A OUTPUT -d "$HOST_NETWORK" -j ACCEPT

# Set default policies to DROP first
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP

# First allow established connections for already approved traffic
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Then allow only specific outbound traffic to allowed domains
iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT

# Explicitly REJECT all other outbound traffic for immediate feedback
iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited

if [ "$ALLOW_WARNINGS" -gt 0 ]; then
    echo "Firewall configuration complete with $ALLOW_WARNINGS allow-list warning(s)"
    echo "  Those entries were SKIPPED and their traffic is blocked. Scroll up for"
    echo "  the file and line of each, fix them, then re-run this script."
else
    echo "Firewall configuration complete"
fi
echo "Verifying firewall rules..."

# Confirm the IPv6 stack really is denied. Captured into a variable rather than
# piped into grep: `grep -q` exits on its first match, and the resulting SIGPIPE
# would fail the pipeline under `set -o pipefail`.
if [ -d /proc/sys/net/ipv6 ] && command -v ip6tables >/dev/null 2>&1; then
    ip6_rules=$(ip6tables -S)
    for chain in INPUT FORWARD OUTPUT; do
        if ! echo "$ip6_rules" | grep -q -- "-P $chain DROP"; then
            echo "ERROR: Firewall verification failed - ip6tables $chain policy is not DROP"
            exit 1
        fi
    done
    echo "Firewall verification passed - all IPv6 chains default to DROP"
fi

# Confirm DNS is scoped: an allowed resolver answers, an unlisted one does not.
# 9.9.9.9 (Quad9) is the probe purely because it is a well-known resolver that
# is deliberately absent from the list above.
if ! dig +time=5 +tries=1 @1.1.1.1 example.com >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - allowed resolver 1.1.1.1 is unreachable"
    exit 1
else
    echo "Firewall verification passed - allowed resolver 1.1.1.1 is reachable"
fi

if dig +time=5 +tries=1 @9.9.9.9 example.com >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - unlisted resolver 9.9.9.9 answered"
    exit 1
else
    echo "Firewall verification passed - unlisted resolver 9.9.9.9 is blocked as expected"
fi

# Confirm SSH is governed by the allow-list rather than open on port 22.
# gitlab.com is the probe because it definitely listens on 22 and is definitely
# not in the ipset, so a success here means the policy is broken — this can only
# fail the boot when the firewall is actually wrong, never when SSH is merely
# unreachable. The positive case (git-over-SSH to GitHub still working) is left
# as a manual check, `ssh -T git@github.com`, so container start does not gain a
# dependency on port 22 being reachable at all.
if timeout 5 bash -c 'exec 3<>/dev/tcp/gitlab.com/22' >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - reached gitlab.com:22, SSH is not allow-listed"
    exit 1
else
    echo "Firewall verification passed - SSH to a non-allow-listed host is blocked"
fi

if curl --connect-timeout 5 https://example.com >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - was able to reach https://example.com"
    exit 1
else
    echo "Firewall verification passed - unable to reach https://example.com as expected"
fi

# Verify GitHub API access
if ! curl --connect-timeout 5 https://api.github.com/zen >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - unable to reach https://api.github.com"
    exit 1
else
    echo "Firewall verification passed - able to reach https://api.github.com as expected"
fi
