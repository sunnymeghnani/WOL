#!/usr/bin/env bash
# shutdown_servers.sh — safely shut down one or more remote Linux servers via SSH.
#
# Shutdowns run in parallel (one background job per server) and results are
# aggregated at the end.
#
# Usage:
#   ./shutdown_servers.sh                   # shutdown ALL servers
#   ./shutdown_servers.sh --group web       # shutdown servers in group "web"
#   ./shutdown_servers.sh --name server-web-01
#   ./shutdown_servers.sh --dry-run         # print what would happen, no action

set -euo pipefail
source "$(dirname "$0")/utils.sh"

# ── CLI args ──────────────────────────────────────────────────────────────────
FILTER_GROUP=""; FILTER_NAME=""; DRY_RUN=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --all              Shutdown all servers (default when no filter given)
  --group GROUP      Shutdown only servers in GROUP
  --name  NAME       Shutdown a single server by name
  --dry-run          Print actions without executing them
  -h, --help         Show this help

Examples:
  $(basename "$0") --all
  $(basename "$0") --group production
  $(basename "$0") --name server-db-01 --dry-run
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)           shift ;;
        --group)         FILTER_GROUP="$2"; shift 2 ;;
        --name)          FILTER_NAME="$2";  shift 2 ;;
        --dry-run)       DRY_RUN=true;      shift ;;
        -h|--help)       usage ;;
        *)               die "Unknown option: $1" ;;
    esac
done

# ── pre-flight ────────────────────────────────────────────────────────────────
init_log "shutdown"
require_cmd ssh python3
assert_office_network

SSH_KEY=$(get_setting "ssh_key_path")
SSH_KEY="${SSH_KEY/#\~/$HOME}"
SSH_TIMEOUT=$(get_setting "ssh_connect_timeout")

[[ -f "$SSH_KEY" ]] || die "SSH key not found: $SSH_KEY  (run ./keys/setup_ssh_key.sh)"

# ── build server list ─────────────────────────────────────────────────────────
if   [[ -n "$FILTER_GROUP" ]]; then
    mapfile -t SERVERS < <(filter_servers --group "$FILTER_GROUP")
elif [[ -n "$FILTER_NAME"  ]]; then
    mapfile -t SERVERS < <(filter_servers --name  "$FILTER_NAME")
else
    mapfile -t SERVERS < <(filter_servers --all)
fi

[[ ${#SERVERS[@]} -eq 0 ]] && die "No servers matched the given filter."

# ── confirmation prompt ───────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${RED}=== SHUTDOWN CONFIRMATION ===${RESET}"
echo "The following servers will be shut down:"
for entry in "${SERVERS[@]}"; do
    IFS='|' read -r name ip _mac _bcast _user _port _groups <<< "$entry"
    echo "  • $name  ($ip)"
done
echo ""

if $DRY_RUN; then
    warn "DRY-RUN mode — no shutdown commands will be sent."
    exit 0
fi

read -r -p "Type 'yes' to confirm: " CONFIRM
[[ "$CONFIRM" == "yes" ]] || { warn "Aborted by user."; exit 0; }

# ── parallel shutdown ─────────────────────────────────────────────────────────
echo ""
info "Initiating parallel shutdowns…"

RESULT_DIR=$(mktemp -d)
declare -a PIDS=()

shutdown_one() {
    local name="$1" ip="$2" user="$3" port="$4"
    local result_file="${RESULT_DIR}/${name}"

    # Sync filesystems first, then power off cleanly.
    # 'sudo shutdown -h now' requires NOPASSWD in /etc/sudoers for $user
    # (see keys/setup_ssh_key.sh for sudoers snippet).
    if ssh \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout="$SSH_TIMEOUT" \
        -o BatchMode=yes \
        -i "$SSH_KEY" \
        -p "$port" \
        "${user}@${ip}" \
        "sync && sudo shutdown -h now" 2>&1; then
        echo "SUCCESS" > "$result_file"
    else
        echo "FAILED" > "$result_file"
    fi
}

for entry in "${SERVERS[@]}"; do
    IFS='|' read -r name ip _mac _bcast user port _groups <<< "$entry"
    info "  Shutting down ${BOLD}${name}${RESET} ($ip) in background…"
    shutdown_one "$name" "$ip" "$user" "$port" &
    PIDS+=($!)
done

echo ""
info "Waiting for all shutdown jobs to complete…"

# Wait for all background jobs
for pid in "${PIDS[@]}"; do
    wait "$pid" || true
done

# ── collect results ───────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}=== RESULTS ===${RESET}"
FAILED=0

for entry in "${SERVERS[@]}"; do
    IFS='|' read -r name ip _mac _bcast user port _groups <<< "$entry"
    result_file="${RESULT_DIR}/${name}"
    if [[ -f "$result_file" ]]; then
        result=$(< "$result_file")
    else
        result="FAILED"
    fi

    if [[ "$result" == "SUCCESS" ]]; then
        # SSH exits with non-zero when the connection drops because the server
        # powered off mid-session, which is normal. Treat that as success too.
        success "$name ($ip) — shutdown command delivered"
    else
        error "$name ($ip) — shutdown FAILED (check SSH access)"
        (( FAILED++ )) || true
    fi
done

rm -rf "$RESULT_DIR"

echo ""
if (( FAILED == 0 )); then
    success "All ${#SERVERS[@]} server(s) shut down successfully."
else
    warn "${FAILED} server(s) failed. Review the log: $LOG_FILE"
    exit 1
fi
