#!/usr/bin/env python3
"""
Test script for Sony IMX219 (8MP, 160 FOV) on NVIDIA Jetson Orin Nano.
ECE 3332 Wildlife Deterrent System
"""

import os
import sys
import time
import cv2

sensor_id = int(os.environ.get("CSI_SENSOR_ID", "0"))
flip_method = int(os.environ.get("CSI_FLIP_METHOD", "0"))
output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cam_test.jpg")

def build_nvargus_pipeline(sid, flip):
    return (
        f"nvarguscamerasrc sensor-id={sid} ! "
        f"video/x-raw(memory:NVMM), width=1920, height=1080, framerate=30/1 ! "
        f"nvvidconv flip-method={flip} ! "
        f"video/x-raw, width=1280, height=720, format=BGRx ! "
        f"videoconvert ! "
        f"video/x-raw, format=BGR ! appsink drop=1"
    )

def build_v4l2_bayer_pipeline(dev="/dev/video0"):
    # Fallback Bayer pipeline for raw V4L2 capture
    return (
        f"v4l2src device={dev} ! "
        f"video/x-bayer, width=1920, height=1080, format=rggb ! "
        f"bayer2rgb ! "
        f"videoconvert ! "
        f"video/x-raw, format=BGR ! appsink drop=1"
    )

print("=" * 60)
print(f" Testing IMX219 Camera on Jetson (sensor-id={sensor_id})")
print("=" * 60)

cap = None

# Step 1: Hardware-accelerated ISP (nvarguscamerasrc)
print(f"[1/2] Attempting Hardware ISP capture via nvarguscamerasrc (sensor-id={sensor_id})...")
cap = cv2.VideoCapture(build_nvargus_pipeline(sensor_id, flip_method), cv2.CAP_GSTREAMER)

# Step 2: V4L2 Bayer GStreamer fallback
if not cap.isOpened():
    print("[2/2] nvargus not ready. Attempting direct V4L2 Bayer GStreamer on /dev/video0...")
    cap = cv2.VideoCapture(build_v4l2_bayer_pipeline("/dev/video0"), cv2.CAP_GSTREAMER)

if not cap.isOpened():
    print("\n[ERROR] Unable to open camera stream.")
    print("If you just ran enable_imx219_overlay.sh, remember to run: sudo reboot")
    sys.exit(1)

print(f"\n[OK] Camera stream opened! Capturing test frame...")
# Warmup a few frames
for _ in range(5):
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.05)

ret, frame = cap.read()
cap.release()

if ret and frame is not None:
    cv2.imwrite(output_file, frame)
    h, w, c = frame.shape
    print(f"[SUCCESS] Captured frame ({w}x{h}, {c} channels)")
    print(f"[SAVED] Test snapshot saved to: {output_file}")
else:
    print("[ERROR] Camera opened but no frames received.")
    sys.exit(1)
