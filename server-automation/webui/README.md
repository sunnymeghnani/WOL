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

### Docker (recommended)

From the `server-automation/` root (one level up from this README):

```bash
docker compose up -d        # build + start in background
docker compose logs -f      # tail logs
docker compose down         # stop & remove
```

Open <http://localhost:5000>.

**Adding/changing servers without restarting**: edit `config/servers.yaml`
on your host machine and the UI picks it up on the next page refresh — no
`docker compose down/up` needed. The config is bind-mounted into the container
and the app re-reads it on every request.

Only rebuild the image (`docker compose up -d --build`) when you change
Python code or `requirements.txt`.

### Linux / macOS

```bash
cd webui/

# One-time setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Every time you want to run it
source venv/bin/activate
python3 app.py
```

If `python3 -m venv` fails on Ubuntu, install: `sudo apt install python3-venv python3-full`.

### Windows (PowerShell)

```powershell
cd webui

# One-time setup
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Every time you want to run it
.\venv\Scripts\Activate.ps1
python app.py
```

If PowerShell blocks the activation script, run once as Administrator:
`Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

For Windows CMD instead of PowerShell, use `venv\Scripts\activate.bat`.

### Access the dashboard

Open <http://localhost:5000> — or share `http://YOUR-LAPTOP-IP:5000`
with teammates on the office LAN (the server binds to `0.0.0.0`).

To stop: `Ctrl+C` in the terminal. To leave the venv: `deactivate`.

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
