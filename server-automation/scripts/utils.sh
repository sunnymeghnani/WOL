#!/usr/bin/env bash
# Shared helpers sourced by wake_servers.sh and shutdown_servers.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="${PROJECT_DIR}/config/servers.yaml"
LOG_DIR="${PROJECT_DIR}/logs"

# ── colour codes ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── logging ───────────────────────────────────────────────────────────────────
init_log() {
    local script_name="$1"
    mkdir -p "$LOG_DIR"
    LOG_FILE="${LOG_DIR}/${script_name}_$(date +%Y%m%d_%H%M%S).log"
    exec > >(tee -a "$LOG_FILE") 2>&1
    info "Logging to: $LOG_FILE"
}

# ── dependency checks ─────────────────────────────────────────────────────────
require_cmd() {
    for cmd in "$@"; do
        command -v "$cmd" &>/dev/null || die "Required command not found: $cmd  (install it and retry)"
    done
}

# ── YAML parsing (pure bash, no yq required) ──────────────────────────────────
# Returns newline-separated "field=value" pairs for all servers.
# Usage: parse_servers | while IFS= read -r line; do ...
parse_servers() {
    python3 - "$CONFIG_FILE" <<'PYEOF' | tr -d '\r'
import sys, yaml, json
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
for s in data.get("servers", []):
    groups = ",".join(s.get("groups", []))
    print(f"{s['name']}|{s['ip']}|{s['mac']}|{s['subnet_broadcast']}|{s['ssh_user']}|{s['ssh_port']}|{groups}")
PYEOF
}

get_setting() {
    local key="$1"
    python3 - "$CONFIG_FILE" "$key" <<'PYEOF' | tr -d '\r'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
keys = sys.argv[2].split(".")
v = data.get("settings", {})
for k in keys:
    v = v[k]
print(v)
PYEOF
}

# ── network / office-network guard ───────────────────────────────────────────
get_local_ips() {
    # Try hostname -I (Linux), then `ip addr` (Linux), then Python (cross-platform fallback).
    if hostname -I 2>/dev/null | grep -q .; then
        hostname -I 2>/dev/null
    elif command -v ip &>/dev/null; then
        ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}'
    else
        python3 -c "import socket; print(socket.gethostbyname(socket.gethostname()))"
    fi
}

ip_in_cidr() {
    # returns 0 (true) if $1 is contained in CIDR $2
    python3 -c "
import sys
from ipaddress import ip_address, ip_network
try:
    sys.exit(0 if ip_address(sys.argv[1]) in ip_network(sys.argv[2], strict=False) else 1)
except Exception:
    sys.exit(1)
" "$1" "$2"
}

assert_office_network() {
    info "Verifying office network connectivity…"
    local office_nets
    office_nets=$(python3 - "$CONFIG_FILE" <<'PYEOF' | tr -d '\r'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
for n in data["settings"]["office_networks"]:
    print(n)
PYEOF
)

    local my_ips
    read -ra my_ips <<< "$(get_local_ips)"

    for my_ip in "${my_ips[@]}"; do
        while IFS= read -r cidr; do
            if ip_in_cidr "$my_ip" "$cidr"; then
                success "Office network confirmed: $my_ip is inside $cidr"
                return 0
            fi
        done <<< "$office_nets"
    done

    die "Not on office network. Current IPs: ${my_ips[*]}. Scripts must run from office network only."
}

# ── filter helpers ────────────────────────────────────────────────────────────
# Usage: filter_servers [--group GROUP] [--name NAME] [--all]
# Prints matching server lines (pipe-separated).
filter_servers() {
    local filter_group="" filter_name="" show_all=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --group) filter_group="$2"; shift 2 ;;
            --name)  filter_name="$2";  shift 2 ;;
            --all)   show_all=true;     shift   ;;
            *)       die "Unknown filter option: $1" ;;
        esac
    done

    while IFS='|' read -r name ip mac bcast user port groups; do
        if $show_all; then
            echo "${name}|${ip}|${mac}|${bcast}|${user}|${port}|${groups}"
        elif [[ -n "$filter_name" && "$name" == "$filter_name" ]]; then
            echo "${name}|${ip}|${mac}|${bcast}|${user}|${port}|${groups}"
        elif [[ -n "$filter_group" ]]; then
            IFS=',' read -ra grp_arr <<< "$groups"
            for g in "${grp_arr[@]}"; do
                if [[ "$g" == "$filter_group" ]]; then
                    echo "${name}|${ip}|${mac}|${bcast}|${user}|${port}|${groups}"
                    break
                fi
            done
        fi
    done < <(parse_servers)
}
