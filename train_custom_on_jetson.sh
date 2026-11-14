#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export YOLO_OFFLINE="true"
export ULTRALYTICS_OFFLINE="1"

echo "=================================================================="
echo " Sentinel v2.0 - Jetson Orin Nano Offline Custom Fine-Tuning"
echo "=================================================================="

# Activate Python virtual environment if present
if [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate"
elif [ -f "$HOME/.venv/bin/activate" ]; then
    source "$HOME/.venv/bin/activate"
fi

# Ensure dashboard/python server is completely stopped so all GPU/RAM is free for training
pkill -f "python3 app.py" 2>/dev/null || true

restore_normal_power() {
    echo ""
    echo "[POWER] Restoring Jetson power mode to normal (25W) and disabling jetson_clocks..."
    python3 -c "
import time
try:
    from jtop import jtop
    with jtop() as jetson:
        if jetson.ok():
            jetson.jetson_clocks.set_enable(False)
            time.sleep(2.5)
            print(f'[POWER] Restored -> nvpmodel={jetson.nvpmodel}, jetson_clocks={jetson.jetson_clocks.status}', flush=True)
except Exception as e:
    print(f'[POWER] jtop restore note: {e}', flush=True)
" 2>/dev/null || true
}
trap restore_normal_power EXIT

echo "[POWER] Enabling maximum power envelope and activating jetson_clocks for training..."
python3 -c "
import time
try:
    from jtop import jtop
    with jtop() as jetson:
        if jetson.ok():
            jetson.jetson_clocks = True
            time.sleep(2.5)
            print(f'[POWER] Active -> nvpmodel={jetson.nvpmodel}, jetson_clocks={jetson.jetson_clocks.status}', flush=True)
except Exception as e:
    print(f'[POWER] jtop enable note: {e}', flush=True)
" || true

# 1. Run fine-tuning (113 campus photos + 10 video frames + 200 replay buffer images)
python3 finetune_custom_jetson.py "$@"

# 2. Rebuild TensorRT FP16 engine from the newly exported best.onnx
echo ""
echo "Rebuilding TensorRT FP16 engine (best.engine) from updated best.onnx..."
chmod +x ./build_engine.sh
./build_engine.sh

echo "=================================================================="
echo " [COMPLETE] Custom fine-tuning & TensorRT engine rebuild finished!"
echo " Start the dashboard with: ./run_dashboard.sh"
echo "=================================================================="
