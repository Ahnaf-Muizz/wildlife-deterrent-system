# Wildlife Deterrent System v2.0 — Jetson Orin Nano 8GB Deployment Package
**ECE 3332: Microcontroller Project Lab | Group 8**

This self-contained package includes:
- **React + TypeScript Pre-Built Dashboard (`frontend/dist/`)**: Zero Node.js or internet required on the Jetson.
- **100% Offline Hybrid Dual-Model YOLO Cascade (`app.py` & `detect_live.py`)**:
  - Primary 4-Class `YOLOv11m` (`best.engine` / `best.pt`) + Secondary Prebuilt COCO (`yolo11n.pt`).
  - **Human Safety Override**: Any detected human (`Class 3: SAFE`) overrides the frame to `SAFE` with **0 deterrents engaged**.
  - **Domestic Pets & Foxes**: Cats, dogs, and foxes classify strictly as `SMALL MAMMAL` (`Class 1`).
  - **Deterministic Escalation**: `LARGE MAMMAL` (`Sound+Light+Water`, `8-14s`) > `SMALL MAMMAL` (`Water+Sound`, `5-9s`) > `BIRD` (`Sound+Light`, `3-6s`).
- **Zero-Latency ESP32-S3 Firmware (`esp32/`)**: Hardware-randomized sub-pattern and total durations with `< 5ms` SoftAP response.

---

## Step-by-Step Archive & Clean Setup on Jetson Orin Nano

### Step 1: On Your Jetson — Stop & Archive the Old Deployment
SSH into your Jetson (or open a terminal on the Jetson) and run:
```bash
# Stop any running app.py instance
pkill -f "python3 app.py" || true

# Archive the current deploy_package with a timestamp
mv ~/deploy_package ~/deploy_package_v1_archive_$(date +%Y%m%d_%H%M%S)
```

### Step 2: On Your Windows Laptop — Copy the New `deploy_package` to the Jetson
Open PowerShell on your laptop inside the `ECE 3332 - Microcontroller Project Lab` folder and run:
```powershell
scp -r "Wildlife Deterrent System/deploy_package" <JETSON_USER>@<JETSON_IP>:~/deploy_package
```

### Step 3: On Your Jetson — Run the 1-Step Setup & Launch Script
Back on the Jetson terminal:
```bash
cd ~/deploy_package
chmod +x setup_v2.sh run_dashboard.sh build_engine.sh
./setup_v2.sh
./run_dashboard.sh
```
> **Note**: `setup_v2.sh` automatically detects your `~/deploy_package_v1_archive_*` folder and copies over your existing `.venv` and compiled TensorRT `best.engine` so setup completes **100% offline in seconds**!
