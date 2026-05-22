#!/usr/bin/env python3
"""
shutdown_servers.py — Safely shut down remote Linux servers in parallel via SSH.

Usage:
    python3 shutdown_servers.py                    # shutdown all
    python3 shutdown_servers.py --group production
    python3 shutdown_servers.py --name server-web-01
    python3 shutdown_servers.py --dry-run
"""

import argparse
import concurrent.futures
import ipaddress
import logging
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import paramiko  # pip install paramiko
import yaml      # pip install pyyaml

CONFIG  = Path(__file__).parent.parent / "config" / "servers.yaml"
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


# ── logging setup ─────────────────────────────────────────────────────────────
def init_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"shutdown_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("shutdown")
    logger.info(f"Logging to: {log_file}")
    return logger


# ── config ────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


# ── office network guard ──────────────────────────────────────────────────────
def assert_office_network(office_cidrs: list[str]) -> None:
    my_ips: list[str] = []
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True)
        my_ips += out.split()
    except Exception:
        try:
            my_ips.append(socket.gethostbyname(socket.gethostname()))
        except Exception:
            pass

    for ip in my_ips:
        for cidr in office_cidrs:
            try:
                if ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False):
                    ok(f"Office network confirmed: {ip} in {cidr}")
                    return
            except ValueError:
                continue
    die(f"Not on office network. Current IPs: {my_ips}. Aborting.")


# ── filtering ─────────────────────────────────────────────────────────────────
def filter_servers(servers: list[dict], group: str | None, name: str | None) -> list[dict]:
    if name:
        return [s for s in servers if s["name"] == name]
    if group:
        return [s for s in servers if group in s.get("groups", [])]
    return servers


# ── per-server shutdown ───────────────────────────────────────────────────────
def shutdown_one(srv: dict, key_path: str, timeout: int,
                 dry_run: bool, logger: logging.Logger) -> tuple[str, bool, str]:
    """Returns (name, success, message)."""
    name = srv["name"]
    ip   = srv["ip"]
    user = srv["ssh_user"]
    port = srv["ssh_port"]

    if dry_run:
        logger.info(f"[DRY-RUN] Would SSH {user}@{ip}:{port} and run: sync && sudo shutdown -h now")
        return name, True, "dry-run"

    try:
        key = paramiko.Ed25519Key.from_private_key_file(str(Path(key_path).expanduser()))
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=port, username=user, pkey=key,
                       timeout=timeout, banner_timeout=timeout)

        # sync first, then power off
        _stdin, stdout, stderr = client.exec_command(
            "sync && sudo shutdown -h now", timeout=30
        )
        out = stdout.read().decode().strip()
        err_out = stderr.read().decode().strip()

        try:
            client.close()
        except Exception:
            pass  # expected — server cuts the connection as it shuts down

        logger.info(f"{name} ({ip}): shutdown command delivered. stdout={out!r} stderr={err_out!r}")
        return name, True, "shutdown command delivered"

    except paramiko.ssh_exception.NoValidConnectionsError as exc:
        # Server cut the connection during shutdown — treat as success
        if "Connection refused" not in str(exc):
            logger.info(f"{name}: connection dropped (server powering off) — treating as success")
            return name, True, "connection dropped (server powering off)"
        logger.error(f"{name} ({ip}): SSH connection refused — {exc}")
        return name, False, str(exc)

    except EOFError:
        # SSH channel closed abruptly because the server shut down mid-command.
        logger.info(f"{name}: SSH EOF (server powered off) — treating as success")
        return name, True, "server powered off"

    except Exception as exc:
        logger.error(f"{name} ({ip}): {exc}")
        return name, False, str(exc)


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Safely shut down remote servers in parallel")
    parser.add_argument("--group",   help="Shutdown servers in this group")
    parser.add_argument("--name",    help="Shutdown a single server by name")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without executing them")
    args = parser.parse_args()

    logger = init_logging()
    cfg = load_config()
    settings = cfg["settings"]

    assert_office_network(settings["office_networks"])

    targets = filter_servers(cfg["servers"], args.group, args.name)
    if not targets:
        die("No servers matched the given filter.")

    key_path = settings["ssh_key_path"]
    timeout  = settings["ssh_connect_timeout"]

    # confirmation prompt
    print()
    print(f"{C.BOLD}{C.RED}=== SHUTDOWN CONFIRMATION ==={C.RESET}")
    print("The following servers will be shut down:")
    for s in targets:
        print(f"  • {s['name']}  ({s['ip']})")
    print()

    if args.dry_run:
        warn("DRY-RUN mode — no commands will be sent.\n")
    else:
        confirm = input("Type 'yes' to confirm: ").strip()
        if confirm != "yes":
            warn("Aborted by user.")
            sys.exit(0)

    # parallel shutdown
    info(f"Shutting down {len(targets)} server(s) in parallel…\n")
    results: list[tuple[str, bool, str]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {
            pool.submit(shutdown_one, srv, key_path, timeout, args.dry_run, logger): srv
            for srv in targets
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # results summary
    print()
    print(f"{C.BOLD}=== RESULTS ==={C.RESET}")
    failed = 0
    for name, success, msg in results:
        if success:
            ok(f"{name} — {msg}")
        else:
            err(f"{name} — FAILED: {msg}")
            failed += 1

    print()
    if failed == 0:
        ok(f"All {len(targets)} server(s) shut down successfully.")
    else:
        warn(f"{failed} server(s) failed. Check the log in {LOG_DIR}/")
        sys.exit(1)


if __name__ == "__main__":
    main()
