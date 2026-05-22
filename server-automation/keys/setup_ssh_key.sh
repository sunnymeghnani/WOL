#!/usr/bin/env bash
# setup_ssh_key.sh — generate the automation SSH key and push it to all servers.
#
# Run this ONCE from the office network with temporary password-based SSH access.
# After this, all automation scripts use the key with no password prompts.

set -euo pipefail
source "$(dirname "$0")/../scripts/utils.sh"

KEY_PATH="$HOME/.ssh/server_automation_key"
KEY_COMMENT="server-automation@$(hostname)"

# ── generate key ──────────────────────────────────────────────────────────────
if [[ -f "$KEY_PATH" ]]; then
    warn "Key already exists at $KEY_PATH — skipping generation."
else
    info "Generating ED25519 key pair…"
    ssh-keygen -t ed25519 -f "$KEY_PATH" -C "$KEY_COMMENT" -N ""
    success "Key generated: $KEY_PATH"
fi

chmod 600 "$KEY_PATH"
chmod 644 "${KEY_PATH}.pub"

PUB_KEY=$(< "${KEY_PATH}.pub")
info "Public key: $PUB_KEY"
echo ""

# ── push to servers ───────────────────────────────────────────────────────────
info "Pushing public key to servers (you will be prompted for each server's password)…"
echo ""

while IFS='|' read -r name ip mac bcast user port groups; do
    info "  → $name ($user@$ip:$port)"
    ssh-copy-id -i "${KEY_PATH}.pub" -p "$port" "${user}@${ip}" \
        || warn "  Failed to copy key to $name — add it manually."
    echo ""
done < <(parse_servers)

success "Key distribution complete."

# ── print sudoers snippet ─────────────────────────────────────────────────────
cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IMPORTANT: Add this sudoers rule on EACH target server
  so the automation user can shutdown without a password.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Run on each server:
    sudo visudo -f /etc/sudoers.d/automation

  Paste this content:
    # Allow automation user to shut down without password
    devops ALL=(ALL) NOPASSWD: /sbin/shutdown

  Replace 'devops' with the ssh_user in servers.yaml if different.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
