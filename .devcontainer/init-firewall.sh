#!/bin/bash
#
# Default-DROP egress firewall for the dev container.
#
# Builds an ipset allow-list from GitHub's published IP ranges, a fixed set of
# domains the toolchain needs (npm, PyPI, the Anthropic API, VS Code, and
# telemetry), and a static list of LAN CIDRs (the local LLM), sets the default
# OUTPUT policy to DROP, then verifies that a disallowed host is blocked and an
# allowed one is reachable.
#
# The allow-list is IPv4-only, so IPv6 is denied outright rather than left at
# its default ACCEPT — see the ip6tables block below.
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
# Allow outbound DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
# Allow inbound DNS responses
iptables -A INPUT -p udp --sport 53 -j ACCEPT
# Allow outbound SSH
iptables -A OUTPUT -p tcp --dport 22 -j ACCEPT
# Allow inbound SSH responses
iptables -A INPUT -p tcp --sport 22 -m state --state ESTABLISHED -j ACCEPT
# Allow localhost
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Create ipset with CIDR support
ipset create allowed-domains hash:net

# Fetch GitHub meta information and aggregate + add their IP ranges
echo "Fetching GitHub IP ranges..."
gh_ranges=$(curl -s https://api.github.com/meta)
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

# Resolve and add other allowed domains
#
# npm + PyPI cover the Node and Python features this template ships on by
# default; api.anthropic.com is Claude Code; the rest are VS Code Server and
# telemetry. Add a line here for any host a project legitimately needs.
for domain in \
    "registry.npmjs.org" \
    "pypi.org" \
    "files.pythonhosted.org" \
    "api.anthropic.com" \
    "sentry.io" \
    "statsig.com" \
    "marketplace.visualstudio.com" \
    "vscode.blob.core.windows.net" \
    "update.code.visualstudio.com"; do
    echo "Resolving $domain..."
    ips=$(dig +noall +answer A "$domain" | awk '$4 == "A" {print $5}')
    if [ -z "$ips" ]; then
        echo "ERROR: Failed to resolve $domain"
        exit 1
    fi

    while read -r ip; do
        if [[ ! "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
            echo "ERROR: Invalid IP from DNS for $domain: $ip"
            exit 1
        fi
        echo "Adding $ip for $domain"
        # -exist: domains behind a shared CDN (Fastly, Cloudflare) resolve to
        # overlapping IPs; without this, the second add fails and aborts.
        ipset add allowed-domains "$ip" -exist
    done < <(echo "$ips")
done

# Static networks to allow, in addition to the resolved domains above.
#
# 192.168.12.0/24 is the LAN segment the local LLM lives on — the endpoint
# opencode is pointed at via OPENAI_BASE_URL in devcontainer.json. It is not
# reachable through HOST_NETWORK below: that is derived from the default route,
# which inside the container is the Docker bridge gateway (172.x), not the LAN.
#
# These are literal CIDRs rather than names, so unlike the domain loop they
# involve no DNS and cannot fail a container boot.
for cidr in \
    "192.168.12.0/24"; do
    if [[ ! "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$ ]]; then
        echo "ERROR: Invalid static CIDR: $cidr"
        exit 1
    fi
    echo "Adding static network $cidr"
    ipset add allowed-domains "$cidr" -exist
done

# Get host IP from default route
HOST_IP=$(ip route | grep default | cut -d" " -f3)
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

echo "Firewall configuration complete"
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
