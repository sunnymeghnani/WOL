#!/usr/bin/env python3
"""
wake_servers.py — Wake-on-LAN script (Python version).

Usage:
    python3 wake_servers.py                    # wake all servers
    python3 wake_servers.py --group web
    python3 wake_servers.py --name server-web-01
    python3 wake_servers.py --wait             # wait for SSH
"""

import argparse
import socket
import struct
import sys
import time
from pathlib import Path

import yaml  # pip install pyyaml

try:
    import paramiko  # pip install paramiko  (only needed with --wait)
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

CONFIG = Path(__file__).parent.parent / "config" / "servers.yaml"
LOG_DIR = Path(__file__).parent.parent / "logs"

# ── ANSI colours ──────────────────────────────────────────────────────────────
class C:
    RED    = "\033[0;31m"
    GREEN  = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN   = "\033[0;36m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def info(msg):    print(f"{C.CYAN}[INFO]{C.RESET}  {msg}")
def ok(msg):      print(f"{C.GREEN}[OK]{C.RESET}    {msg}")
def warn(msg):    print(f"{C.YELLOW}[WARN]{C.RESET}  {msg}")
def err(msg):     print(f"{C.RED}[ERROR]{C.RESET} {msg}", file=sys.stderr)
def die(msg):     err(msg); sys.exit(1)


# ── config loading ────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


# ── office network guard ──────────────────────────────────────────────────────
def assert_office_network(office_cidrs: list[str]) -> None:
    import ipaddress, socket
    my_ips = socket.gethostbyname_ex(socket.gethostname())[2]
    # also grab IPs via hostname -I style
    try:
        import subprocess
        out = subprocess.check_output(["hostname", "-I"], text=True)
        my_ips += out.split()
    except Exception:
        pass
    my_ips = list(set(my_ips))

    for ip in my_ips:
        for cidr in office_cidrs:
            try:
                if ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False):
                    ok(f"Office network confirmed: {ip} ∈ {cidr}")
                    return
            except ValueError:
                continue
    die(f"Not on office network. Current IPs: {my_ips}. Aborting.")


# ── WOL magic packet ──────────────────────────────────────────────────────────
def build_magic_packet(mac: str) -> bytes:
    """6 bytes of 0xFF followed by 16 repetitions of the 6-byte MAC."""
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(mac_bytes) != 6:
        raise ValueError(f"Invalid MAC address: {mac}")
    return b"\xff" * 6 + mac_bytes * 16


def send_wol(mac: str, broadcast: str, port: int) -> None:
    packet = build_magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (broadcast, port))


# ── SSH reachability check ────────────────────────────────────────────────────
def wait_for_ssh(ip: str, user: str, port: int, key_path: str,
                 timeout: int = 10, max_wait: int = 300, poll: int = 10) -> bool:
    if not HAS_PARAMIKO:
        warn("paramiko not installed; skipping SSH wait (pip install paramiko)")
        return False
    key = paramiko.RSAKey.from_private_key_file(str(Path(key_path).expanduser()))
    elapsed = 0
    while elapsed < max_wait:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(ip, port=port, username=user, pkey=key,
                           timeout=timeout, banner_timeout=timeout)
            client.close()
            return True
        except Exception:
            warn(f"  {ip} not yet reachable, retrying in {poll}s… ({elapsed}s elapsed)")
            time.sleep(poll)
            elapsed += poll
    return False


# ── server filtering ──────────────────────────────────────────────────────────
def filter_servers(servers: list[dict], group: str | None, name: str | None) -> list[dict]:
    if name:
        return [s for s in servers if s["name"] == name]
    if group:
        return [s for s in servers if group in s.get("groups", [])]
    return servers


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Wake-on-LAN for multiple servers")
    parser.add_argument("--group", help="Wake servers in this group")
    parser.add_argument("--name",  help="Wake a single server by name")
    parser.add_argument("--wait",  action="store_true",
                        help="Wait and verify SSH reachability after sending WOL")
    args = parser.parse_args()

    cfg = load_config()
    settings = cfg["settings"]

    assert_office_network(settings["office_networks"])

    targets = filter_servers(cfg["servers"], args.group, args.name)
    if not targets:
        die("No servers matched the given filter.")

    wol_port = settings["wol_port"]
    info(f"Sending WOL packets to {len(targets)} server(s)…\n")

    for srv in targets:
        name  = srv["name"]
        mac   = srv["mac"]
        bcast = srv["subnet_broadcast"]
        info(f"  → {C.BOLD}{name}{C.RESET}  MAC: {mac}  broadcast: {bcast}:{wol_port}")
        try:
            send_wol(mac, bcast, wol_port)
            ok(f"  Packet sent to {name}")
        except Exception as exc:
            err(f"  Failed to send WOL to {name}: {exc}")
        print()

    if args.wait:
        key_path = settings["ssh_key_path"]
        timeout  = settings["ssh_connect_timeout"]
        info("Waiting for servers to become reachable via SSH…\n")
        for srv in targets:
            name = srv["name"]
            ip   = srv["ip"]
            user = srv["ssh_user"]
            port = srv["ssh_port"]
            if wait_for_ssh(ip, user, port, key_path, timeout=timeout):
                ok(f"{name} ({ip}) is UP")
            else:
                err(f"{name} ({ip}) did not come up within 300s")

    print()
    ok("Wake-on-LAN sequence complete.")


if __name__ == "__main__":
    main()
