#!/usr/bin/env python3
"""
Flask web UI for the server-automation toolkit.

Run:
    pip install -r requirements.txt
    python3 app.py
    # open http://localhost:5000
"""

import ipaddress
import logging
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import paramiko
import yaml
from flask import Flask, jsonify, render_template, request

# ── make the sibling python/ folder importable so we reuse existing logic ────
SCRIPT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPT_ROOT / "python"))
from wake_servers import send_wol  # noqa: E402

CONFIG  = SCRIPT_ROOT / "config" / "servers.yaml"
LOG_DIR = SCRIPT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── logging ──────────────────────────────────────────────────────────────────
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = LOG_DIR / f"webui_{ts}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("webui")

# Ring buffer of recent activity (shown in the UI's live log pane)
ACTIVITY: deque = deque(maxlen=200)

def activity(level: str, msg: str) -> None:
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "msg": msg,
    }
    ACTIVITY.appendleft(entry)
    getattr(log, level if level != "ok" else "info")(msg)


# ── config loading (re-read on every request so YAML edits show up live) ────
def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


# ── office network guard ─────────────────────────────────────────────────────
def get_local_ips() -> list[str]:
    ips: list[str] = []
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True)
        ips += out.split()
    except Exception:
        try:
            ips.append(socket.gethostbyname(socket.gethostname()))
        except Exception:
            pass
    return list(set(ips))


def in_office_network(cidrs: list[str]) -> tuple[bool, str]:
    for ip in get_local_ips():
        for cidr in cidrs:
            try:
                if ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False):
                    return True, f"{ip} in {cidr}"
            except ValueError:
                continue
    return False, f"none of {get_local_ips()} match {cidrs}"


# ── server status via ping ───────────────────────────────────────────────────
_IS_WINDOWS = sys.platform.startswith("win")

def ping(ip: str, timeout: int = 1) -> bool:
    if _IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout), ip]
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
        return r.returncode == 0
    except Exception:
        return False


# ── server selection helpers ─────────────────────────────────────────────────
def select_servers(payload: dict) -> list[dict]:
    cfg = load_config()
    servers = cfg["servers"]
    if payload.get("all"):
        return servers
    if payload.get("group"):
        return [s for s in servers if payload["group"] in s.get("groups", [])]
    if payload.get("names"):
        names = set(payload["names"])
        return [s for s in servers if s["name"] in names]
    return []


# ── shutdown worker ──────────────────────────────────────────────────────────
def shutdown_one(srv: dict, key_path: str, timeout: int) -> tuple[bool, str]:
    name, ip = srv["name"], srv["ip"]
    user, port = srv["ssh_user"], srv["ssh_port"]
    try:
        key = paramiko.Ed25519Key.from_private_key_file(str(Path(key_path).expanduser()))
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, port=port, username=user, pkey=key,
                  timeout=timeout, banner_timeout=timeout)
        c.exec_command("sync && sudo shutdown -h now", timeout=30)
        try:
            c.close()
        except Exception:
            pass
        return True, "shutdown command delivered"
    except (paramiko.ssh_exception.NoValidConnectionsError, EOFError):
        return True, "server powered off"
    except Exception as exc:
        return False, str(exc)


# ── Flask app ────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/network")
def api_network():
    cfg = load_config()
    ok, why = in_office_network(cfg["settings"]["office_networks"])
    return jsonify(in_office=ok, detail=why, local_ips=get_local_ips())


@app.route("/api/servers")
def api_servers():
    cfg = load_config()
    out = []
    for s in cfg["servers"]:
        out.append({
            "name": s["name"],
            "ip": s["ip"],
            "mac": s["mac"],
            "groups": s.get("groups", []),
            "subnet_broadcast": s["subnet_broadcast"],
            "status": "up" if ping(s["ip"]) else "down",
        })
    groups = sorted({g for s in cfg["servers"] for g in s.get("groups", [])})
    return jsonify(servers=out, groups=groups)


@app.route("/api/wake", methods=["POST"])
def api_wake():
    cfg = load_config()
    ok, why = in_office_network(cfg["settings"]["office_networks"])
    if not ok:
        return jsonify(error=f"Not on office network ({why})"), 403

    payload = request.get_json(silent=True) or {}
    targets = select_servers(payload)
    if not targets:
        return jsonify(error="No servers matched the selection"), 400

    wol_port = cfg["settings"]["wol_port"]
    results = []
    for s in targets:
        try:
            send_wol(s["mac"], s["subnet_broadcast"], wol_port)
            activity("ok", f"WOL packet sent to {s['name']} ({s['mac']})")
            results.append({"name": s["name"], "ok": True, "msg": "WOL sent"})
        except Exception as exc:
            activity("error", f"WOL failed for {s['name']}: {exc}")
            results.append({"name": s["name"], "ok": False, "msg": str(exc)})
    return jsonify(results=results)


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    cfg = load_config()
    ok, why = in_office_network(cfg["settings"]["office_networks"])
    if not ok:
        return jsonify(error=f"Not on office network ({why})"), 403

    payload = request.get_json(silent=True) or {}
    if payload.get("confirm") != "yes":
        return jsonify(error="Missing confirmation token"), 400

    targets = select_servers(payload)
    if not targets:
        return jsonify(error="No servers matched the selection"), 400

    key_path = cfg["settings"]["ssh_key_path"]
    timeout = cfg["settings"]["ssh_connect_timeout"]

    # Run shutdowns in parallel threads so the UI doesn't block on slow hosts.
    results: list[dict] = []
    threads: list[threading.Thread] = []
    lock = threading.Lock()

    def worker(srv):
        ok_, msg = shutdown_one(srv, key_path, timeout)
        with lock:
            results.append({"name": srv["name"], "ok": ok_, "msg": msg})
        activity("ok" if ok_ else "error",
                 f"Shutdown {srv['name']}: {msg}")

    for s in targets:
        t = threading.Thread(target=worker, args=(s,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=60)

    return jsonify(results=results)


@app.route("/api/activity")
def api_activity():
    return jsonify(entries=list(ACTIVITY))


if __name__ == "__main__":
    activity("info", f"WebUI starting — logs: {log_file.name}")
    # Bind to 0.0.0.0 so teammates on the office LAN can reach it.
    # Set debug=False in production.
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
