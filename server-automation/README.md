# Server Automation — Wake & Shutdown

Centralized scripts for remotely waking and shutting down office servers across
multiple subnets from any laptop IP. Built for DevOps use.

---

## Folder Structure

```
server-automation/
├── config/
│   └── servers.yaml          ← single source of truth: IPs, MACs, groups
├── scripts/
│   ├── utils.sh              ← shared helpers (sourced, not run directly)
│   ├── wake_servers.sh       ← WOL bash script
│   └── shutdown_servers.sh   ← SSH shutdown bash script
├── python/
│   ├── wake_servers.py       ← WOL Python alternative
│   ├── shutdown_servers.py   ← SSH shutdown Python alternative
│   └── requirements.txt
├── keys/
│   └── setup_ssh_key.sh      ← one-time SSH key setup
└── logs/                     ← auto-created, one log file per run
```

---

## One-Time Setup

### 1. Install dependencies

**Bash scripts**
```bash
# Debian/Ubuntu
sudo apt install wakeonlan python3 python3-yaml

# macOS
brew install wakeonlan
pip3 install pyyaml
```

**Python scripts (optional alternative)**
```bash
pip3 install -r python/requirements.txt
```

### 2. Edit `config/servers.yaml`

Fill in the real MAC addresses and IPs of your servers.

To find a server's MAC address from your network:
```bash
arp -n 192.168.1.120          # if server is currently online
# OR check your router/switch ARP table
# OR: ip neigh show (on Linux, run from the server itself)
```

### 3. Enable Wake-on-LAN on each target server (one-time)

SSH in and run:
```bash
# Check current WOL state
sudo ethtool eth0 | grep Wake-on

# Enable WOL temporarily (test)
sudo ethtool -s eth0 wol g

# Make it permanent (systemd service)
sudo tee /etc/systemd/system/wol.service <<EOF
[Unit]
Description=Enable Wake-on-LAN
After=network.target

[Service]
Type=oneshot
ExecStart=/sbin/ethtool -s eth0 wol g

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now wol.service
```

Replace `eth0` with the actual interface name (`ip link` to list them).

### 4. Set up SSH keys (passwordless authentication)

```bash
chmod +x keys/setup_ssh_key.sh
./keys/setup_ssh_key.sh
```

This script:
- Generates `~/.ssh/server_automation_key` (ED25519)
- Copies the public key to every server in `servers.yaml`
- Prints the sudoers rule needed for passwordless shutdown

### 5. Make scripts executable

```bash
chmod +x scripts/wake_servers.sh scripts/shutdown_servers.sh keys/setup_ssh_key.sh
```

---

## Usage

### Wake servers

```bash
# Wake all servers
./scripts/wake_servers.sh

# Wake a specific group
./scripts/wake_servers.sh --group production

# Wake one server and wait until SSH is up
./scripts/wake_servers.sh --name server-web-01 --wait

# Python version
python3 python/wake_servers.py --group web --wait
```

### Shut down servers

```bash
# Shutdown all (prompts for confirmation)
./scripts/shutdown_servers.sh

# Shutdown a group
./scripts/shutdown_servers.sh --group web

# Preview without acting
./scripts/shutdown_servers.sh --dry-run

# Python version
python3 python/shutdown_servers.py --group production
```

### Adding a new server

Edit `config/servers.yaml`, add an entry, then run:
```bash
./keys/setup_ssh_key.sh     # push the key to the new server
```
No other changes needed.

---

## Network Requirements for Wake-on-LAN Across Subnets

WOL magic packets are UDP broadcasts. Routers normally drop broadcast packets
between subnets. You need one of the following:

### Option A — Directed broadcast (recommended)

1. **Router**: Enable `ip directed-broadcast` on each target VLAN interface.

   *Cisco IOS example:*
   ```
   interface Vlan10
    ip directed-broadcast
   ```

   *pfSense/OPNsense*: Rules → LAN → allow UDP dst 192.168.1.255 port 9.

2. **Firewall**: Allow incoming UDP port 9 (or 7) to the subnet broadcast address.

   The scripts send to `subnet_broadcast` (e.g. `192.168.1.255`), not to
   the individual server IP, so the router delivers the packet to all hosts
   on that VLAN including the sleeping server.

### Option B — WOL relay agent

Deploy a small relay service on a always-on host in each subnet:
```bash
# On a Raspberry Pi / small always-on machine in subnet 192.168.1.x:
sudo apt install wakeonlan
# Listen for forwarded packets and re-broadcast locally
```

Then target the relay's IP instead of the broadcast address.

### Option C — Switch-level WOL forwarding

Some managed switches (e.g. Cisco SG series) support WOL packet forwarding
between VLANs natively — check your switch's admin guide.

---

## Security Best Practices

| Topic | What this toolkit does |
|---|---|
| SSH authentication | ED25519 keys only — no passwords |
| Key scope | Dedicated `server_automation_key`, not your personal key |
| `authorized_keys` | Per-user, stored on target servers |
| sudo | NOPASSWD only for `/sbin/shutdown`, nothing else |
| Office-network check | Scripts verify your IP is in an office CIDR before running |
| Logs | Every run timestamped in `logs/` |
| Confirmation | Shutdown requires typing `yes` interactively |

### Additional hardening recommendations

```bash
# On each server — restrict the automation key to only allow shutdown:
# In ~/.ssh/authorized_keys, prefix the key line with:
command="sudo shutdown -h now",no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAA...
```

This means even if the key is stolen, it can only trigger shutdown — nothing else.

---

## Logs

Each run writes a timestamped log to `logs/`:
```
logs/wake_20240520_143012.log
logs/shutdown_20240520_183045.log
```

Rotate old logs:
```bash
find logs/ -name "*.log" -mtime +30 -delete
```
