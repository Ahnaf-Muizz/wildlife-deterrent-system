# YOLOv11m 4-Class Validation & Deployment Report (Jetson Orin Nano 8GB Target)

- **Generated**: 2026-11-04 08:42:00
- **Model Architecture**: `YOLOv11m` (20.1M Parameters, 68.0 GFLOPs)
- **Base Weights Path**: `deploy_package/best.pt` / `C:\wildlife_yolo\runs\y11m_4class_orin\weights\best.pt`
- **Export Resolution**: `640x640` (ONNX Opset 12 Simplified -> `deploy_package/best.onnx`)
- **Dataset**: `C:\wildlife_yolo\dataset_clean` (40,000 Daylight Images: 35,491 train / 4,509 val)

---

## 1. Training Convergence & Peak Metrics (Epoch 43)

During the multi-epoch training run with mixed-precision FP16 Tensor Core acceleration (`amp=True`), the model achieved peak validation performance at **Epoch 43**:

| Metric | Training Peak (Epoch 43 EMA) | Post-Export Standalone Validation | Target Benchmark |
| :--- | :---: | :---: | :---: |
| **Overall mAP50** | **90.06%** | **80.81%** | $\ge 80.0\%$ |
| **Overall mAP50-95** | **65.30%** | **54.44%** | $\ge 50.0\%$ |
| **Precision** | **90.4%** | **82.79%** | $\ge 80.0\%$ |
| **Recall** | **83.4%** | **73.04%** | $\ge 70.0\%$ |

---

## 2. Per-Class Accuracy Breakdown

| Class ID | Class Label | Training mAP50 (Ep 43) | Standalone mAP50 | Standalone Precision | Standalone Recall | System / ESP32 Action |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **`0`** | **`bird`** | **88.0%** | **77.26%** | **82.97%** | **68.66%** | **Sound Alarm / Flashing Light** (`BIRD`) |
| **`1`** | **`small_mammal`** | **96.4%** | **91.34%** | **88.30%** | **87.77%** | **Water Sprinkle / Sound Alarm** (`RABBIT`) |
| **`2`** | **`large_mammal`** | **89.9%** | **80.55%** | **80.23%** | **73.72%** | **Randomized Water + Light + Sound** (`DEER`) |
| **`3`** | **`safe`** | **86.0%** | **74.06%** | **79.64%** | **62.00%** | **0 ESP32 Triggers** (`Area Clear - Safe`) |

---

## 3. Deliverables Summary

1. **`deploy_package/best.onnx`** (76.7 MB): Simplified ONNX Opset 12 graph, optimized for TensorRT FP16 compilation.
2. **`deploy_package/best.pt`** (153.7 MB): PyTorch weights for on-device fine-tuning or evaluation.
3. **`Perfect_Test_Images_Daylight/`** (80 Images): 20 daylight validation images per class with $>75\%$ detection confidence.
4. **`deploy_package/custom_dataset/replay_buffer/`** (200 Images): 50 high-clarity daylight images and labels per class to prevent catastrophic forgetting during on-Jetson fine-tuning.
5. **`deploy_package/finetune_custom_jetson.py` & `train_custom_on_jetson.sh`**: Self-contained on-device training and evaluation pipeline for ~100 custom images.

---

## 4. Jetson Orin Nano 8GB Deployment Instructions

### Step 1: Copy `deploy_package` to Jetson
```bash
scp -r "Wildlife Deterrent System/deploy_package" jetson@<jetson_ip>:~/sentinel_wildlife
```

### Step 2: Build TensorRT FP16 Engine
On the Jetson Orin Nano:
```bash
cd ~/sentinel_wildlife
chmod +x build_engine.sh train_custom_on_jetson.sh run_dashboard.sh
./build_engine.sh
```
*Or execute `trtexec` directly:*
```bash
/usr/src/tensorrt/bin/trtexec \
  --onnx=best.onnx \
  --saveEngine=best.engine \
  --fp16 \
  --workspace=4096 \
  --builderOptimizationLevel=5
```

### Step 3: Launch Live Deterrent System & Dashboard
```bash
python3 app.py
```
Or for standalone headless detection:
```bash
python3 detect_live.py --engine best.engine --cam 0
```

### Step 4: On-Jetson Fine-Tuning (Optional for ~100 Custom Images)
Place your ~100 custom images in `custom_dataset/raw_images/` and run:
```bash
./train_custom_on_jetson.sh
```
This script will:
1. Auto-label images and create a stratified 80/20 train/test split.
2. Benchmark accuracy before fine-tuning.
3. Fine-tune YOLOv11m with replay buffer regularization (`freeze=10, batch=4, amp=True`).
4. Benchmark accuracy after fine-tuning.
5. Automatically rebuild the TensorRT FP16 `best.engine`.
