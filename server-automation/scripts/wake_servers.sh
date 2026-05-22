#!/usr/bin/env bash
# wake_servers.sh — send Wake-on-LAN magic packets to one or more servers.
#
# Usage:
#   ./wake_servers.sh                    # wake ALL servers
#   ./wake_servers.sh --group web        # wake servers in group "web"
#   ./wake_servers.sh --name server-web-01
#   ./wake_servers.sh --wait             # also wait and verify SSH reachability

set -euo pipefail
source "$(dirname "$0")/utils.sh"

# ── CLI args ──────────────────────────────────────────────────────────────────
FILTER_GROUP=""; FILTER_NAME=""; WAIT_FOR_SSH=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --all              Wake all servers (default when no filter given)
  --group GROUP      Wake only servers belonging to GROUP
  --name  NAME       Wake a single server by name
  --wait             After sending packets, poll SSH until servers respond
  -h, --help         Show this help

Examples:
  $(basename "$0") --all
  $(basename "$0") --group production
  $(basename "$0") --name server-web-01 --wait
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)           shift ;;
        --group)         FILTER_GROUP="$2"; shift 2 ;;
        --name)          FILTER_NAME="$2";  shift 2 ;;
        --wait)          WAIT_FOR_SSH=true; shift ;;
        -h|--help)       usage ;;
        *)               die "Unknown option: $1" ;;
    esac
done

# ── pre-flight ────────────────────────────────────────────────────────────────
init_log "wake"
require_cmd python3 wakeonlan
assert_office_network

# ── build server list ─────────────────────────────────────────────────────────
if   [[ -n "$FILTER_GROUP" ]]; then
    mapfile -t SERVERS < <(filter_servers --group "$FILTER_GROUP")
elif [[ -n "$FILTER_NAME"  ]]; then
    mapfile -t SERVERS < <(filter_servers --name  "$FILTER_NAME")
else
    mapfile -t SERVERS < <(filter_servers --all)
fi

[[ ${#SERVERS[@]} -eq 0 ]] && die "No servers matched the given filter."

WOL_PORT=$(get_setting "wol_port")

# ── send WOL packets ──────────────────────────────────────────────────────────
info "Sending Wake-on-LAN magic packets…"
echo ""

declare -a WAKE_TARGETS=()

for entry in "${SERVERS[@]}"; do
    IFS='|' read -r name ip mac bcast user port groups <<< "$entry"
    info "  → ${BOLD}${name}${RESET}  MAC: ${mac}  broadcast: ${bcast}:${WOL_PORT}"

    # Send to the subnet's directed-broadcast address so the packet reaches
    # the server even though we are on a different subnet.
    # Requires the router to have "ip directed-broadcast" enabled on the
    # target VLAN interface (see README for details).
    if wakeonlan -i "$bcast" -p "$WOL_PORT" "$mac"; then
        success "  Packet sent to $name"
    else
        warn "  wakeonlan reported an error for $name"
    fi
    WAKE_TARGETS+=("${name}|${ip}|${user}|${port}")
    echo ""
done

# ── optional: wait for SSH to come up ────────────────────────────────────────
if $WAIT_FOR_SSH; then
    SSH_KEY=$(get_setting "ssh_key_path")
    SSH_KEY="${SSH_KEY/#\~/$HOME}"
    TIMEOUT=$(get_setting "ssh_connect_timeout")
    MAX_WAIT=300   # seconds to keep trying before giving up
    POLL=10

    info "Waiting for servers to become reachable via SSH (max ${MAX_WAIT}s)…"
    echo ""

    for target in "${WAKE_TARGETS[@]}"; do
        IFS='|' read -r name ip user port <<< "$target"
        elapsed=0
        while (( elapsed < MAX_WAIT )); do
            if ssh -o StrictHostKeyChecking=no \
                   -o ConnectTimeout="$TIMEOUT" \
                   -o BatchMode=yes \
                   -i "$SSH_KEY" \
                   -p "$port" \
                   "${user}@${ip}" "true" 2>/dev/null; then
                success "$name ($ip) is UP and accepting SSH"
                break
            fi
            warn "  $name not yet reachable, retrying in ${POLL}s… (${elapsed}s elapsed)"
            sleep "$POLL"
            (( elapsed += POLL ))
        done
        (( elapsed >= MAX_WAIT )) && error "$name did not come up within ${MAX_WAIT}s"
    done
fi

echo ""
success "Wake-on-LAN sequence complete."
