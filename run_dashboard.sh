#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

export YOLO_OFFLINE="true"
export ULTRALYTICS_OFFLINE="1"

# Activate virtual environment if present
if [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate"
elif [ -f "$HOME/.venv/bin/activate" ]; then
    source "$HOME/.venv/bin/activate"
fi

# Enable MAXN clocks on Jetson Orin Nano if passwordless sudo is available
if command -v nvpmodel >/dev/null 2>&1; then
    sudo -n nvpmodel -m 0 2>/dev/null || true
fi
if command -v jetson_clocks >/dev/null 2>&1; then
    sudo -n jetson_clocks 2>/dev/null || true
fi

echo "=================================================================="
echo "  Wildlife Deterrent System | ECE 3332 | Group 8 (v2.0)"
echo "=================================================================="

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$IP_ADDR" ]; then
    IP_ADDR="127.0.0.1"
fi

echo ">> Local access on Jetson  : http://127.0.0.1:5002"
echo ">> Remote access on Network: http://$IP_ADDR:5002"
echo ">> Offline Dual-Model AI   : ENABLED (best.engine/best.pt + yolo11n.pt)"
echo "=================================================================="
echo "Press Ctrl+C to stop the dashboard."
echo ""

if [ -n "$DISPLAY" ]; then
    (sleep 2 && (xdg-open http://127.0.0.1:5002 2>/dev/null || chromium-browser http://127.0.0.1:5002 2>/dev/null || google-chrome http://127.0.0.1:5002 2>/dev/null)) &
fi

python3 app.py
