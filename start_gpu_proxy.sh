#!/bin/bash
# Start GPU reverse proxy: tan:8000 → titan:8001
# Tailscale funnel (https://tan.tail2e1adb.ts.net) → this proxy → titan GPU service

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/proxy_venv"

if [ ! -d "$VENV" ]; then
    echo "Creating venv..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install httpx uvicorn
fi

echo "Starting GPU proxy on :8000 → 192.168.0.105:8001"
exec "$VENV/bin/uvicorn" gpu_proxy:app --host 0.0.0.0 --port 8000 --app-dir "$SCRIPT_DIR"
