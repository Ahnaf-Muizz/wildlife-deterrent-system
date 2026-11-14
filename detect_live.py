#!/usr/bin/env python3
"""
Sentinel Wildlife Deterrent System v2.0 - Live Camera Detection on Jetson Orin Nano 8GB
100% Offline Hybrid Dual-Model Cascade (best.engine/best.pt + yolo11n.pt):
  - Strictly Human-Only SAFE with Top-Priority Safety Override (0 deterrents if human present)
  - Domestic pets (cats, dogs) and quadrupeds (foxes) routed to SMALL MAMMAL
  - Deterministic Threat Hierarchy: LARGE MAMMAL > SMALL MAMMAL > BIRD
  - Tiered Randomized Sound Durations: Bird (3-6s), Small Mammal (5-9s), Large Mammal (8-14s)
  - Clean '<CLASS NAME> <CONFIDENCE>%' bounding box labels
"""

import os

os.environ["YOLO_OFFLINE"] = "true"
os.environ["ULTRALYTICS_OFFLINE"] = "1"

import cv2
import time
import json
import random
import urllib.request
import urllib.parse
import threading
import numpy as np
import torch
from ultralytics import YOLO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
device = 0 if torch.cuda.is_available() else "cpu"

# 1. Load Primary Custom 4-Class Model (Prefers TensorRT best.engine, falls back to best.pt)
model_path = os.path.join(BASE_DIR, "best.engine")
if not os.path.exists(model_path):
    model_path = os.path.join(BASE_DIR, "best.pt")

print(f"[AI] Loading Primary 4-Class Model (OFFLINE): {model_path} on device: {device}...")
primary_model = YOLO(model_path)

# 2. Load Secondary Prebuilt COCO Model (yolo11n.pt) strictly from local disk
coco_verifier = None
for cc in [os.path.join(BASE_DIR, "yolo11n.engine"), os.path.join(BASE_DIR, "yolo11n.pt")]:
    if os.path.exists(cc):
        try:
            coco_verifier = YOLO(cc)
            print(f"[AI] Loaded Secondary COCO Verifier (OFFLINE): {cc}")
            break
        except Exception as e:
            print(f"[AI] Warning loading {cc}: {e}")

# Startup 3-Frame GPU / TensorRT Warmup at 640x640
if device != "cpu":
    print("[AI] Running 3-frame GPU/TensorRT warmup at 640x640...")
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    for _ in range(3):
        primary_model.predict(source=dummy, imgsz=640, device=device, verbose=False)
        if coco_verifier is not None:
            coco_verifier.predict(source=dummy, imgsz=640, device=device, verbose=False)

COCO_RELEVANT_CLASSES = [0, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
COCO_TO_SENTINEL = {
    0: (3, "SAFE", "human"),
    14: (0, "BIRD", "bird"),
    15: (1, "SMALL MAMMAL", "cat"),
    16: (1, "SMALL MAMMAL", "dog"),
    17: (2, "LARGE MAMMAL", "horse"),
    18: (2, "LARGE MAMMAL", "sheep"),
    19: (2, "LARGE MAMMAL", "cow"),
    20: (2, "LARGE MAMMAL", "elephant"),
    21: (2, "LARGE MAMMAL", "bear"),
    22: (2, "LARGE MAMMAL", "zebra"),
    23: (2, "LARGE MAMMAL", "giraffe"),
}
SENTINEL_CLASS_NAMES = {
    0: "BIRD",
    1: "SMALL MAMMAL",
    2: "LARGE MAMMAL",
    3: "SAFE",
}


def compute_iou(box_a, box_b):
    x_a = max(box_a[0], box_b[0])
    y_a = max(box_a[1], box_b[1])
    x_b = min(box_a[2], box_b[2])
    y_b = min(box_a[3], box_b[3])
    inter_w = max(0.0, x_b - x_a)
    inter_h = max(0.0, y_b - y_a)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0
    area_a = max(1.0, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
    area_b = max(1.0, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))
    return inter_area / float(area_a + area_b - inter_area)


def verify_crop_with_coco(img_bgr, xyxy):
    h_img, w_img = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    pad_x = int((x2 - x1) * 0.08)
    pad_y = int((y2 - y1) * 0.08)
    x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
    x2, y2 = min(w_img, x2 + pad_x), min(h_img, y2 + pad_y)
    if (x2 - x1) <= 4 or (y2 - y1) <= 4:
        return False, 1
    if coco_verifier is not None:
        crop = img_bgr[y1:y2, x1:x2]
        if crop.size > 0:
            try:
                res = coco_verifier.predict(
                    source=crop, classes=COCO_RELEVANT_CLASSES, conf=0.25, device=device, verbose=False
                )
                c_boxes = res[0].boxes
                if len(c_boxes) > 0:
                    best_c_cls = int(c_boxes.cls[0].item())
                    if best_c_cls == 0:
                        return True, 3
                    elif best_c_cls in COCO_TO_SENTINEL:
                        return False, COCO_TO_SENTINEL[best_c_cls][0]
                return False, 1
            except Exception:
                pass
    aspect = (y2 - y1) / float(x2 - x1)
    return (True, 3) if aspect >= 1.25 else (False, 1)


def run_dual_model_cascade(img_bgr, conf_thresh=0.28):
    primary_res = primary_model.predict(source=img_bgr, imgsz=640, conf=conf_thresh, device=device, verbose=False)[0]
    coco_detections = []
    if coco_verifier is not None:
        try:
            coco_res = coco_verifier.predict(
                source=img_bgr, classes=COCO_RELEVANT_CLASSES, conf=conf_thresh, device=device, verbose=False
            )[0]
            for cbox in coco_res.boxes:
                c_cls = int(cbox.cls[0].item())
                c_conf = float(cbox.conf[0].item())
                c_xyxy = [float(v) for v in cbox.xyxy[0].tolist()]
                if c_cls in COCO_TO_SENTINEL:
                    s_cls, s_name, s_sub = COCO_TO_SENTINEL[c_cls]
                    coco_detections.append({
                        "sentinel_cls": s_cls,
                        "subtype": s_sub,
                        "conf": c_conf,
                        "xyxy": c_xyxy,
                        "matched": False,
                    })
        except Exception:
            pass

    final_detections = []
    for pbox in primary_res.boxes:
        p_cls = int(pbox.cls[0].item())
        p_conf = float(pbox.conf[0].item())
        p_xyxy = [float(v) for v in pbox.xyxy[0].tolist()]

        best_iou = 0.0
        best_coco = None
        for cd in coco_detections:
            iou = compute_iou(p_xyxy, cd["xyxy"])
            if iou > best_iou:
                best_iou = iou
                best_coco = cd

        resolved_cls = p_cls
        resolved_conf = p_conf

        if best_coco is not None and best_iou >= 0.30:
            best_coco["matched"] = True
            c_s_cls = best_coco["sentinel_cls"]
            c_sub = best_coco["subtype"]
            c_conf = best_coco["conf"]

            if p_cls == 3:
                if c_s_cls == 3:
                    resolved_cls = 3
                    resolved_conf = max(p_conf, c_conf)
                else:
                    resolved_cls = c_s_cls if c_s_cls in (0, 1, 2) else 1
                    resolved_conf = max(p_conf, c_conf)
            else:
                if c_s_cls == 3 and c_conf >= 0.35:
                    resolved_cls = 3
                    resolved_conf = max(p_conf, c_conf)
                elif c_sub in ("cat", "dog"):
                    resolved_cls = 1
                    resolved_conf = max(p_conf, c_conf)
                elif c_s_cls == p_cls:
                    resolved_conf = max(p_conf, c_conf)
        else:
            if p_cls == 3:
                is_human, override_cls = verify_crop_with_coco(img_bgr, p_xyxy)
                resolved_cls = 3 if is_human else override_cls

        class_name = SENTINEL_CLASS_NAMES.get(resolved_cls, "SMALL MAMMAL")
        final_detections.append({
            "class_id": resolved_cls,
            "class_name": class_name,
            "display_label": f"{class_name} {int(round(resolved_conf * 100))}%",
            "confidence": resolved_conf,
            "bbox": p_xyxy,
        })

    for cd in coco_detections:
        if not cd["matched"] and cd["conf"] >= 0.45:
            if any(compute_iou(cd["xyxy"], fd["bbox"]) >= 0.35 for fd in final_detections):
                continue
            s_cls = cd["sentinel_cls"]
            c_name = SENTINEL_CLASS_NAMES.get(s_cls, "SMALL MAMMAL")
            final_detections.append({
                "class_id": s_cls,
                "class_name": c_name,
                "display_label": f"{c_name} {int(round(cd['conf'] * 100))}%",
                "confidence": cd["conf"],
                "bbox": cd["xyxy"],
            })

    return final_detections


def trigger_esp32_alarm(animal_token, duration_ms):
    def _worker():
        host = os.environ.get("ESP32_HOST", "192.168.4.1")
        q_animal = urllib.parse.quote(str(animal_token))
        url = f"http://{host}/command?animal={q_animal}&duration={int(duration_ms)}"
        payload = json.dumps({"animal": str(animal_token), "duration": str(int(duration_ms))}).encode("utf-8")
        try:
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                print(f"[ESP32 HTTP] Triggered '{animal_token}' ({duration_ms}ms) -> HTTP {resp.status}")
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def gstreamer_pipeline(
    sensor_id=0,
    capture_width=1920,
    capture_height=1080,
    display_width=1280,
    display_height=720,
    framerate=30,
    flip_method=2,
    wbmode=1,
):
    """
    Construct GStreamer pipeline for Jetson Orin Nano hardware ISP capture via nvarguscamerasrc.
    Default sensor_id=0 targets CAM0 (CSI-A port / J1 connector).
    flip_method=2 applies 180-deg rotation on the hardware VIC engine.
    wbmode=1 enables continuous hardware Auto White Balance.
    """
    wb_param = f"wbmode={wbmode} " if wbmode is not None else ""
    return (
        f"nvarguscamerasrc sensor-id={sensor_id} {wb_param}! "
        f"video/x-raw(memory:NVMM), width=(int){capture_width}, height=(int){capture_height}, framerate=(fraction){framerate}/1 ! "
        f"nvvidconv flip-method={flip_method} ! "
        f"video/x-raw, width=(int){display_width}, height=(int){display_height}, format=(string)BGRx ! "
        f"videoconvert ! "
        f"video/x-raw, format=(string)BGR ! appsink drop=1"
    )


class GrayWorldAWB:
    """Software Auto White Balance for neutralizing any residual camera tint."""
    def __init__(self, smoothing: float = 0.85):
        self.smoothing = smoothing
        self.running_gain = None

    def balance(self, bgr_frame: np.ndarray) -> np.ndarray:
        small = cv2.resize(bgr_frame, (160, 90), interpolation=cv2.INTER_NEAREST)
        mb = float(np.mean(small[:, :, 0]))
        mg = float(np.mean(small[:, :, 1]))
        mr = float(np.mean(small[:, :, 2]))
        if mb < 1e-3 or mg < 1e-3 or mr < 1e-3:
            return bgr_frame
        target = (mb + mg + mr) / 3.0
        gain = np.array([target / mb, target / mg, target / mr], dtype=np.float32)
        if self.running_gain is None:
            self.running_gain = gain
        else:
            self.running_gain = (self.smoothing * self.running_gain) + ((1.0 - self.smoothing) * gain)
        lut_b = np.clip(np.arange(256) * self.running_gain[0], 0, 255).astype(np.uint8)
        lut_g = np.clip(np.arange(256) * self.running_gain[1], 0, 255).astype(np.uint8)
        lut_r = np.clip(np.arange(256) * self.running_gain[2], 0, 255).astype(np.uint8)
        b, g, r = cv2.split(bgr_frame)
        return cv2.merge([cv2.LUT(b, lut_b), cv2.LUT(g, lut_g), cv2.LUT(r, lut_r)])


class ThreadedCamera:
    def __init__(self, cap):
        self.cap = cap
        self.ret, self.frame = self.cap.read()
        self.lock = threading.Lock()
        self.stopped = False
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while not self.stopped:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                self.frame = frame
            if not ret:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            return self.ret, (self.frame.copy() if self.frame is not None else None)

    def release(self):
        self.stopped = True
        self.cap.release()


def open_camera():
    """
    Robust camera detector:
    1. Try Hardware ISP capture via nvarguscamerasrc (sensor-id=0)
    2. Try alternate sensor-id=1
    3. Try direct V4L2 Bayer GStreamer on /dev/video0
    4. Try standard V4L2 webcams (/dev/video0, /dev/video1)
    """
    pref_sensor = int(os.environ.get("CSI_SENSOR_ID", "0"))
    flip_m = int(os.environ.get("CSI_FLIP_METHOD", "0"))
    
    print(f"[CAM] Attempting Hardware ISP capture via nvarguscamerasrc (sensor-id={pref_sensor}, flip={flip_m})...")
    cap = cv2.VideoCapture(gstreamer_pipeline(sensor_id=pref_sensor, flip_method=flip_m), cv2.CAP_GSTREAMER)
    if cap.isOpened():
        print(f"[CAM] Successfully initialized CSI Camera (sensor-id={pref_sensor})!")
        return cap
    
    alt_sensor = 1 if pref_sensor == 0 else 0
    print(f"[CAM] sensor-id={pref_sensor} not opened. Trying alternate sensor-id={alt_sensor}...")
    cap = cv2.VideoCapture(gstreamer_pipeline(sensor_id=alt_sensor, flip_method=flip_m), cv2.CAP_GSTREAMER)
    if cap.isOpened():
        print(f"[CAM] Successfully initialized CSI Camera (sensor-id={alt_sensor})!")
        return cap

    print("[CAM] Attempting direct V4L2 Bayer capture pipeline on /dev/video0...")
    bayer_pipe = (
        "v4l2src device=/dev/video0 ! "
        "video/x-bayer, width=1920, height=1080, format=rggb ! "
        "bayer2rgb ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! appsink drop=1"
    )
    cap = cv2.VideoCapture(bayer_pipe, cv2.CAP_GSTREAMER)
    if cap.isOpened():
        print("[CAM] Opened camera via V4L2 Bayer pipeline on /dev/video0")
        return cap

    print("[CAM] Checking standard V4L2 devices...")
    for dev_idx in [0, 1]:
        cap = cv2.VideoCapture(dev_idx)
        if cap.isOpened():
            print(f"[CAM] Opened fallback V4L2 camera on /dev/video{dev_idx}")
            return cap
            
    return None


if __name__ == "__main__":
    raw_cap = open_camera()
    if raw_cap is None:
        print("ERROR: No camera detected. Ensure IMX219 overlay is applied and camera ribbon cable is firmly seated.")
        exit(1)

    cam = ThreadedCamera(raw_cap)
    last_deterrent_time = 0.0
    cooldown = 5.0

    colors_bgr = {
        2: (60, 68, 248),
        1: (24, 165, 245),
        0: (255, 182, 56),
        3: (110, 198, 46),
    }

    awb_processor = GrayWorldAWB()
    use_awb = True
    mirror_h = True
    mirror_v = False
    rot_angle = 0
    show_hud = True

    print("\n" + "=" * 65)
    print(" SENTINEL LIVE CAMERA AI DETECTION ACTIVE")
    print("=" * 65)
    print(" Live Keyboard Controls (focus on the preview window):")
    print("   [m] - Toggle Horizontal Mirror (Left <-> Right)")
    print("   [v] - Toggle Vertical Mirror (Up <-> Down)")
    print("   [r] - Rotate 90 degrees clockwise")
    print("   [f] - Flip 180 degrees")
    print("   [w] - Toggle Software Auto White Balance")
    print("   [h] - Toggle Detection HUD on/off")
    print("   [s] - Save snapshot")
    print("   [q] - Quit live detection\n")

    while True:
        ret, frame = cam.read()
        if not ret or frame is None:
            break

        # 1. Orientation & Mirror
        if rot_angle == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rot_angle == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rot_angle == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if mirror_h:
            frame = cv2.flip(frame, 1)
        if mirror_v:
            frame = cv2.flip(frame, 0)

        # 2. White Balance
        if use_awb:
            frame = awb_processor.balance(frame)

        t0 = time.perf_counter()
        detections = run_dual_model_cascade(frame, conf_thresh=0.28)
        infer_ms = (time.perf_counter() - t0) * 1000.0

        annotated = frame.copy()
        if show_hud:
            for d in detections:
                x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
                col = colors_bgr.get(d["class_id"], (255, 182, 56))
                cv2.rectangle(annotated, (x1, y1), (x2, y2), col, 2)
                cv2.putText(annotated, d["display_label"], (x1, max(y1 - 8, 20)), cv2.FONT_HERSHEY_DUPLEX, 0.6, col, 2)

            mirror_label = []
            if mirror_h:
                mirror_label.append("H-Mirror")
            if mirror_v:
                mirror_label.append("V-Mirror")
            m_text = ", ".join(mirror_label) if mirror_label else "Unmirrored"
            cv2.putText(
                annotated,
                f"Rot={rot_angle} deg | {m_text} | AWB={'ON' if use_awb else 'OFF'}",
                (20, annotated.shape[0] - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )

        safe_dets = [d for d in detections if d["class_id"] == 3]
        threat_dets = [d for d in detections if d["class_id"] in (0, 1, 2)]

        # Human Safety Override First
        if safe_dets:
            pass  # 0 deterrents engaged when human is present
        elif threat_dets:
            top_cls = max(d["class_id"] for d in threat_dets)
            top_conf = max(d["confidence"] for d in threat_dets if d["class_id"] == top_cls)
            now = time.time()
            if now - last_deterrent_time >= cooldown:
                if top_cls == 2:
                    token, dur, act = "LARGE", random.randint(8000, 14000), "SOUND + LIGHT + WATER"
                elif top_cls == 1:
                    token, dur, act = "SMALL", random.randint(5000, 9000), "WATER + SOUND"
                else:
                    token, dur, act = "BIRD", random.randint(3000, 6000), "SOUND + LIGHT"

                print(f"[{time.strftime('%H:%M:%S')}] {SENTINEL_CLASS_NAMES[top_cls]} ({top_conf:.2f} | {infer_ms:.1f}ms) -> {act} ({dur}ms)")
                trigger_esp32_alarm(token, dur)
                last_deterrent_time = now

        if os.environ.get("DISPLAY"):
            cv2.imshow("Sentinel Wildlife Deterrent System v2.0", annotated)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            elif k == ord("m"):
                mirror_h = not mirror_h
                print(f"[CAM] Horizontal mirror: {'ON' if mirror_h else 'OFF'}")
            elif k == ord("v"):
                mirror_v = not mirror_v
                print(f"[CAM] Vertical mirror: {'ON' if mirror_v else 'OFF'}")
            elif k == ord("r"):
                rot_angle = (rot_angle + 90) % 360
                print(f"[CAM] Rotation: {rot_angle} deg")
            elif k == ord("f"):
                rot_angle = (rot_angle + 180) % 360
                print(f"[CAM] Rotation: {rot_angle} deg")
            elif k == ord("w"):
                use_awb = not use_awb
                print(f"[CAM] Software AWB: {'ON' if use_awb else 'OFF'}")
            elif k == ord("h"):
                show_hud = not show_hud
                print(f"[CAM] HUD Overlays: {'ON' if show_hud else 'OFF'}")
            elif k == ord("s"):
                fname = f"sentinel_snap_{int(time.time())}.jpg"
                cv2.imwrite(fname, annotated)
                print(f"[CAM] Snapshot saved to {fname}")

    cam.release()
    cv2.destroyAllWindows()
