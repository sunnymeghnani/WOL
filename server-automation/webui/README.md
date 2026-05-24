# Web UI

Browser-based dashboard for the server-automation toolkit. Reuses the same
`config/servers.yaml` and the SSH/WOL logic from the `python/` scripts —
so anything you change in the YAML file shows up here automatically.

## Features

- **Live server list** with up/down status (pings every 30s)
- **Group filter** (production / web / database / app …)
- **Multi-select** rows for bulk wake or shutdown
- **Per-row Wake / Shutdown buttons**
- **Confirmation modal** before any shutdown
- **Activity log pane** updated every 3s
- **Office-network guard** — actions blocked when off-network
- **Toasts** for success/failure feedback

## Run

```bash
cd webui/
pip install -r requirements.txt
python3 app.py
```

Then open <http://localhost:5000> — or share `http://YOUR-LAPTOP-IP:5000`
with teammates on the office LAN (the server binds to `0.0.0.0`).

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask backend — REST endpoints for wake/shutdown/status |
| `templates/index.html` | Single-page UI |
| `static/style.css` | Styling (dark theme) |
| `static/app.js` | Frontend logic + polling |
| `requirements.txt` | Python dependencies |

## Production deployment

For real production use, put it behind nginx + gunicorn and add basic auth:

```bash
pip install gunicorn
gunicorn -w 2 -b 127.0.0.1:5000 app:app
```

Then nginx with `auth_basic` in front, TLS via Let's Encrypt, and firewall the
port so it's reachable only from the office VLAN.
