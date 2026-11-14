#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=================================================================="
echo "  Sentinel Wildlife Deterrent System v2.0 — Jetson Setup"
echo "=================================================================="

# 1. Check for an archived v1 folder to reuse .venv and TensorRT best.engine (100% offline fast path)
LATEST_ARCHIVE=$(ls -td ~/deploy_package_v1_archive* ~/deploy_package_backup* ~/deploy_package_old* 2>/dev/null | head -n 1 || true)

if [ -n "$LATEST_ARCHIVE" ] && [ -d "$LATEST_ARCHIVE" ]; then
    echo ">> Found previous deployment archive at: $LATEST_ARCHIVE"

    if [ -d "$LATEST_ARCHIVE/.venv" ] && [ ! -d "$DIR/.venv" ]; then
        echo ">> Copying existing Python virtual environment (.venv) from archive..."
        cp -a "$LATEST_ARCHIVE/.venv" "$DIR/.venv"
    fi

    if [ -f "$LATEST_ARCHIVE/best.engine" ] && [ ! -f "$DIR/best.engine" ]; then
        echo ">> Copying compiled TensorRT engine (best.engine) from archive..."
        cp -a "$LATEST_ARCHIVE/best.engine" "$DIR/best.engine"
    fi
fi

# 2. Activate .venv if present
if [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate"
    echo ">> Activated virtual environment: $DIR/.venv"
elif [ -f "$HOME/.venv/bin/activate" ]; then
    source "$HOME/.venv/bin/activate"
    echo ">> Activated virtual environment: $HOME/.venv"
fi

# 3. Verify or build TensorRT FP16 Engine
if [ -f "$DIR/best.engine" ]; then
    echo ">> TensorRT engine (best.engine) is ready!"
else
    echo ">> Building TensorRT FP16 engine (best.engine) from best.onnx..."
    chmod +x "$DIR/build_engine.sh"
    "$DIR/build_engine.sh"
fi

chmod +x "$DIR/run_dashboard.sh" "$DIR/build_engine.sh" "$DIR/detect_live.py"

echo ""
echo "=================================================================="
echo "  Setup Complete! Launch the v2.0 Dashboard anytime with:"
echo "    ./run_dashboard.sh"
echo "=================================================================="
