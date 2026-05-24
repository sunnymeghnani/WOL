# Multi-stage build keeps the final image small.
# We need `ping` for server status checks, so we install iputils-ping.
FROM python:3.12-slim

# System dependencies:
#   iputils-ping  → app.py uses `ping` to determine UP/DOWN status
#   tini          → proper signal handling (Ctrl+C, docker stop)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        iputils-ping \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer — only rebuilds when
# requirements.txt changes, not every time we edit source code)
COPY webui/requirements.txt /app/webui/requirements.txt
RUN pip install --no-cache-dir -r /app/webui/requirements.txt

# Copy source code. config/ and logs/ are NOT copied — they come in as
# bind-mounts at runtime so host edits reflect immediately.
COPY webui/ /app/webui/
COPY python/ /app/python/

EXPOSE 5000

WORKDIR /app/webui

# tini reaps zombies and forwards signals correctly so `docker stop` works.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-u", "app.py"]
