#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo " Building TensorRT FP16 Engine for Jetson Orin Nano 8GB"
echo " (Optimized for Ampere GPU: 1024 CUDA Cores + 32 Tensor Cores)"
echo "=========================================================="

# Keep Jetson Orin Nano within normal power envelope (avoid MAXN over-current warnings)
TRTEXEC_BIN="/usr/src/tensorrt/bin/trtexec"
if [ ! -f "$TRTEXEC_BIN" ]; then
    TRTEXEC_BIN=$(which trtexec || true)
fi

if [ -n "$TRTEXEC_BIN" ] && [ -x "$TRTEXEC_BIN" ]; then
    echo "Using TensorRT trtexec at: $TRTEXEC_BIN"
    WORKSPACE_FLAG="--workspace=2048"
    if "$TRTEXEC_BIN" --help 2>&1 | grep -q -- "--memPoolSize"; then
        WORKSPACE_FLAG="--memPoolSize=workspace:2048M"
    fi
    "$TRTEXEC_BIN" \
        --onnx=best.onnx \
        --saveEngine=best.engine.raw \
        --fp16 \
        $WORKSPACE_FLAG \
        --warmUp=200 \
        --iterations=20
    python3 -c '
import json
meta = json.dumps({
    "description": "Ultralytics YOLO11m custom 4-class wildlife model",
    "author": "Ultralytics",
    "task": "detect",
    "stride": 32,
    "batch": 1,
    "imgsz": [640, 640],
    "names": {0: "bird", 1: "small_mammal", 2: "large_mammal", 3: "safe"},
    "channels": 3,
    "end2end": False,
    "args": {"batch": 1, "half": True, "dynamic": False, "nms": False},
}).encode("utf-8")
with open("best.engine.raw", "rb") as f_in:
    raw_bytes = f_in.read()
with open("best.engine", "wb") as f_out:
    f_out.write(len(meta).to_bytes(4, byteorder="little", signed=True))
    f_out.write(meta)
    f_out.write(raw_bytes)
'
    rm -f best.engine.raw
else
    echo "trtexec not found, exporting via Ultralytics TensorRT API (640x640 FP16)..."
    python3 -c "from ultralytics import YOLO; model = YOLO('best.pt'); model.export(format='engine', imgsz=640, half=True, device=0)"
fi

echo "=========================================================="
echo " Done! Engine successfully built as: best.engine"
echo "=========================================================="
