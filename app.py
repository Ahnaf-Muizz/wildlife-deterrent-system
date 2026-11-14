import os

# Enforce 100% offline Ultralytics execution BEFORE importing ultralytics
os.environ["YOLO_OFFLINE"] = "true"
os.environ["ULTRALYTICS_OFFLINE"] = "1"

import glob
import uuid
import time
import sqlite3
import cv2
import numpy as np
import random
import json
import urllib.request
import urllib.parse
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event as sa_event, Index
from ultralytics import YOLO
import torch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIST = os.path.join(BASE_DIR, "frontend", "dist")

app = Flask(__name__, static_folder=FRONTEND_DIST, static_url_path="")
DB_V4_PATH = os.path.join(BASE_DIR, "sentinel_logs_v4.db")
DB_V3_PATH = os.path.join(BASE_DIR, "sentinel_logs_v3.db")

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_V4_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # Support up to 512MB video uploads
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "uploads")
app.config["RESULTS_FOLDER"] = os.path.join(BASE_DIR, "results_db")
app.config["THUMBNAILS_FOLDER"] = os.path.join(BASE_DIR, "thumbnails_db")

db = SQLAlchemy(app)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["RESULTS_FOLDER"], exist_ok=True)
os.makedirs(app.config["THUMBNAILS_FOLDER"], exist_ok=True)

# Enable SQLite Write-Ahead Logging (WAL) for high-capacity concurrent performance
with app.app_context():
    @sa_event.listens_for(db.engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.close()


class DeterrentEvent(db.Model):
    __tablename__ = "deterrent_event"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    thumbnail_filename = db.Column(db.String(200), nullable=True)
    media_type = db.Column(db.String(30), nullable=False, default="image", index=True)  # image | video | live_snapshot
    timestamp = db.Column(db.DateTime, default=datetime.now, index=True)
    primary_target = db.Column(db.String(50), nullable=False, index=True)  # LARGE MAMMAL | SMALL MAMMAL | BIRD | SAFE | None
    action_taken = db.Column(db.String(200), nullable=False)
    actuators_json = db.Column(db.Text, nullable=True, default="[]")
    sound_duration_ms = db.Column(db.Integer, nullable=True, default=0)
    confidence = db.Column(db.Float, nullable=True, default=0.0)
    resolution = db.Column(db.String(64), nullable=True, default="Unknown")
    file_size_kb = db.Column(db.Float, nullable=True, default=0.0)
    video_duration_sec = db.Column(db.Float, nullable=True, default=0.0)
    detections_json = db.Column(db.Text, nullable=True, default="[]")
    timeline_json = db.Column(db.Text, nullable=True, default="[]")

    def to_dict(self):
        try:
            actuators = json.loads(self.actuators_json) if self.actuators_json else []
        except Exception:
            actuators = []
        try:
            detections = json.loads(self.detections_json) if self.detections_json else []
        except Exception:
            detections = []
        try:
            timeline = json.loads(self.timeline_json) if self.timeline_json else []
        except Exception:
            timeline = []

        return {
            "id": self.id,
            "filename": self.filename,
            "result_url": f"/results/{self.filename}",
            "thumbnail_url": f"/thumbnails/{self.thumbnail_filename}" if self.thumbnail_filename else f"/results/{self.filename}",
            "media_type": self.media_type or "image",
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "",
            "iso_timestamp": self.timestamp.isoformat() if self.timestamp else "",
            "primary_target": self.primary_target,
            "action_taken": self.action_taken,
            "actuators": actuators,
            "sound_duration_ms": self.sound_duration_ms or 0,
            "confidence": round(float(self.confidence or 0.0), 4),
            "resolution": self.resolution or "Unknown",
            "file_size_kb": round(float(self.file_size_kb or 0.0), 1),
            "video_duration_sec": round(float(self.video_duration_sec or 0.0), 2),
            "detections": detections,
            "timeline": timeline,
        }


def migrate_v3_database_if_needed():
    """Preserves all existing scan logs from sentinel_logs_v3.db on first launch."""
    if not os.path.exists(DB_V3_PATH):
        return
    if DeterrentEvent.query.count() > 0:
        return
    try:
        conn = sqlite3.connect(DB_V3_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT filename, timestamp, primary_target, action_taken, confidence, resolution, file_size_kb FROM deterrent_event"
        )
        rows = cur.fetchall()
        conn.close()
        for r in rows:
            fname, ts_str, target, action, conf, res, fsize = r
            parsed_ts = datetime.now()
            if ts_str:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        parsed_ts = datetime.strptime(str(ts_str), fmt)
                        break
                    except Exception:
                        pass
            actuators = []
            if target == "LARGE MAMMAL":
                actuators = ["SOUND", "LIGHT", "WATER"]
            elif target == "SMALL MAMMAL":
                actuators = ["WATER", "SOUND"]
            elif target == "BIRD":
                actuators = ["SOUND", "LIGHT"]

            ev = DeterrentEvent(
                filename=fname,
                thumbnail_filename=None,
                media_type="image",
                timestamp=parsed_ts,
                primary_target=target,
                action_taken=action,
                actuators_json=json.dumps(actuators),
                sound_duration_ms=5000 if actuators else 0,
                confidence=float(conf or 0.0),
                resolution=res or "Unknown",
                file_size_kb=float(fsize or 0.0),
                detections_json="[]",
                timeline_json="[]",
            )
            db.session.add(ev)
        db.session.commit()
        print(f"[DB] Migrated {len(rows)} historical events from sentinel_logs_v3.db -> sentinel_logs_v4.db")
    except Exception as e:
        print(f"[DB] Note during v3 migration check: {e}")


with app.app_context():
    db.create_all()
    migrate_v3_database_if_needed()
    # Ensure any logged event containing a Human (class_id == 3) overrides to SAFE
    for ev in DeterrentEvent.query.all():
        try:
            dets = json.loads(ev.detections_json) if ev.detections_json else []
            safe_dets = [d for d in dets if d.get("class_id") == 3]
            if safe_dets and ev.primary_target != "SAFE":
                ev.primary_target = "SAFE"
                ev.action_taken = "SAFE Alert — Human Verified (0 Deterrents)"
                ev.actuators_json = "[]"
                ev.sound_duration_ms = 0
                ev.confidence = max((float(d.get("confidence", 0.0)) for d in safe_dets), default=ev.confidence)
                db.session.commit()
        except Exception:
            pass

# ==============================================================================
# HARDWARE ACCELERATION & 100% OFFLINE DUAL-MODEL YOLO CASCADE
# ==============================================================================
device = 0 if torch.cuda.is_available() else "cpu"
_inference_lock = threading.Lock()

best_weights = None
if os.environ.get("MODEL_PATH") and os.path.exists(os.environ.get("MODEL_PATH")):
    best_weights = os.environ.get("MODEL_PATH")

if not best_weights:
    candidates = [
        os.path.join(BASE_DIR, "best.engine"),
        r"C:\wildlife_yolo\runs\y11m_4class_orin\weights\best.pt",
        os.path.join(BASE_DIR, "best.pt"),
        os.path.join(BASE_DIR, "deploy_package", "best.pt"),
        os.path.join(BASE_DIR, "weights", "best.pt"),
    ]
    for c in candidates:
        if os.path.exists(c):
            best_weights = c
            break

if not best_weights:
    print("ERROR: No local custom model weights (best.pt / best.engine) found!")
    exit(1)

print(f"[AI] Loading Primary Custom 4-Class Model (OFFLINE): {best_weights} (Device: {device})")
primary_model = YOLO(best_weights)

# Load Local Prebuilt COCO Model (yolo11n.pt) strictly from local disk (Zero Internet Required)
coco_verifier = None
coco_candidates = [
    os.path.join(BASE_DIR, "yolo11n.engine"),
    os.path.join(BASE_DIR, "yolo11n.pt"),
    os.path.join(BASE_DIR, "deploy_package", "yolo11n.pt"),
]
for cc in coco_candidates:
    if os.path.exists(cc):
        try:
            coco_verifier = YOLO(cc)
            print(f"[AI] Loaded Secondary COCO Verification Model (OFFLINE): {cc}")
            break
        except Exception as e:
            print(f"[AI] Warning loading {cc}: {e}")

# COCO Class ID mappings for Hybrid Dual-Model Cascade:
# 0: person -> Class 3 (SAFE - Strictly Human Only!)
# 14: bird -> Class 0 (BIRD)
# 15: cat, 16: dog -> Class 1 (SMALL MAMMAL - Pets moved out of safe into small_mammal!)
# 17: horse, 18: sheep, 19: cow, 20: elephant, 21: bear, 22: zebra, 23: giraffe -> Class 2 (LARGE MAMMAL)
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


def verify_crop_with_coco(img_bgr, xyxy, conf_thresh=0.50):
    """
    Secondary crop-level check when full-frame COCO didn't match a 'safe' candidate box.
    Returns (is_human, detected_sentinel_cls, sub_label).
    If neither a human nor an animal is confirmed by COCO in the crop, returns
    (False, None, "background_rejected") so background clutter is never turned into SMALL MAMMAL.
    """
    h_img, w_img = img_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    pad_x = int((x2 - x1) * 0.08)
    pad_y = int((y2 - y1) * 0.08)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w_img, x2 + pad_x)
    y2 = min(h_img, y2 + pad_y)
    w_box = x2 - x1
    h_box = y2 - y1
    if w_box <= 8 or h_box <= 8:
        return False, None, "background_rejected"

    if coco_verifier is not None:
        crop = img_bgr[y1:y2, x1:x2]
        if crop.size > 0:
            try:
                res = coco_verifier.predict(
                    source=crop,
                    classes=COCO_RELEVANT_CLASSES,
                    conf=max(0.40, conf_thresh * 0.85),
                    device=device,
                    verbose=False,
                )
                c_boxes = res[0].boxes
                if len(c_boxes) > 0:
                    # Check if any person (0) is detected first (Human safety priority)
                    for cb in c_boxes:
                        if int(cb.cls[0].item()) == 0:
                            return True, 3, "human"
                    best_c_cls = int(c_boxes.cls[0].item())
                    best_c_conf = float(c_boxes.conf[0].item())
                    if best_c_cls in COCO_TO_SENTINEL and best_c_conf >= conf_thresh:
                        mapped_cls, _, sub = COCO_TO_SENTINEL[best_c_cls]
                        return False, mapped_cls, sub
                # Neither person nor animal found in crop -> reject false-positive background box
                return False, None, "background_rejected"
            except Exception:
                pass

    return False, None, "background_rejected"


def run_dual_model_cascade(img_bgr, conf_thresh=0.50):
    """
    Runs the 100% Offline Hybrid Dual-Model Cascade:
      1. Primary 4-class YOLOv11m (best.pt / best.engine)
      2. Secondary Prebuilt COCO YOLOv11n (yolo11n.pt)
    Guarantees:
      - Enforces a minimum 50% confidence floor by default to prevent low-confidence false positives.
      - Class 3 ('SAFE') is strictly Human Only.
      - Unconfirmed background boxes are rejected rather than misclassified as SMALL MAMMAL.
      - Domestic pets (cats, dogs) and foxes are classified as 'SMALL MAMMAL' (Class 1).
    """
    if img_bgr is None or img_bgr.size == 0:
        return []

    conf_thresh = max(0.50, float(conf_thresh))
    h_img, w_img = img_bgr.shape[:2]

    with _inference_lock:
        primary_res = primary_model.predict(
            source=img_bgr,
            save=False,
            device=device,
            conf=conf_thresh,
            verbose=False,
        )[0]

        coco_detections = []
        if coco_verifier is not None:
            try:
                coco_res = coco_verifier.predict(
                    source=img_bgr,
                    classes=COCO_RELEVANT_CLASSES,
                    conf=max(0.45, conf_thresh * 0.9),
                    device=device,
                    verbose=False,
                )[0]
                for cbox in coco_res.boxes:
                    c_cls = int(cbox.cls[0].item())
                    c_conf = float(cbox.conf[0].item())
                    c_xyxy = [float(v) for v in cbox.xyxy[0].tolist()]
                    if c_cls in COCO_TO_SENTINEL:
                        s_cls, s_name, s_sub = COCO_TO_SENTINEL[c_cls]
                        coco_detections.append({
                            "coco_cls": c_cls,
                            "sentinel_cls": s_cls,
                            "class_name": s_name,
                            "subtype": s_sub,
                            "conf": c_conf,
                            "xyxy": c_xyxy,
                            "matched": False,
                        })
            except Exception as e:
                print(f"[AI] Secondary verifier error: {e}")

        final_detections = []
        for pbox in primary_res.boxes:
            p_cls = int(pbox.cls[0].item())
            p_conf = float(pbox.conf[0].item())
            p_xyxy = [float(v) for v in pbox.xyxy[0].tolist()]

            # Find highest-IoU COCO box
            best_iou = 0.0
            best_coco = None
            for cd in coco_detections:
                iou = compute_iou(p_xyxy, cd["xyxy"])
                if iou > best_iou:
                    best_iou = iou
                    best_coco = cd

            resolved_cls = p_cls
            resolved_conf = p_conf
            subtype = SENTINEL_CLASS_NAMES.get(p_cls, "UNKNOWN").lower()

            if best_coco is not None and best_iou >= 0.30:
                best_coco["matched"] = True
                c_s_cls = best_coco["sentinel_cls"]
                c_sub = best_coco["subtype"]
                c_conf = best_coco["conf"]

                if p_cls == 3:
                    # 'safe' box from primary model: ONLY keep as SAFE if COCO confirms human (person)!
                    if c_s_cls == 3:
                        resolved_cls = 3
                        resolved_conf = max(p_conf, c_conf)
                        subtype = "human"
                    else:
                        # COCO explicitly says it's a cat, dog, bird, or mammal -> Override to threat class!
                        resolved_cls = c_s_cls if c_s_cls in (0, 1, 2) else 1
                        resolved_conf = max(p_conf, c_conf)
                        subtype = f"{c_sub}"
                else:
                    # Primary predicted a wildlife class (0, 1, or 2)
                    if c_s_cls == 3 and c_conf >= 0.40:
                        # COCO confirmed a Human (person) -> Override box to SAFE!
                        resolved_cls = 3
                        resolved_conf = max(p_conf, c_conf)
                        subtype = "human"
                    elif c_sub in ("cat", "dog"):
                        # Pets are strictly SMALL MAMMAL (Class 1)
                        resolved_cls = 1
                        resolved_conf = max(p_conf, c_conf)
                        subtype = c_sub
                    elif c_s_cls == p_cls:
                        resolved_conf = max(p_conf, c_conf)
                        subtype = c_sub
            else:
                # No full-frame COCO match
                if p_cls == 3:
                    # Verify crop directly; if neither human nor animal is in crop, discard background false positive
                    is_human, override_cls, sub = verify_crop_with_coco(img_bgr, p_xyxy, conf_thresh=conf_thresh)
                    if is_human:
                        resolved_cls = 3
                        subtype = "human"
                    elif override_cls is not None:
                        resolved_cls = override_cls
                        subtype = sub
                    else:
                        continue
                elif p_cls == 1:
                    # Reject tall vertical wall/partition false positives when unconfirmed by COCO
                    box_w = max(1.0, p_xyxy[2] - p_xyxy[0])
                    box_h = max(1.0, p_xyxy[3] - p_xyxy[1])
                    if (box_h / float(h_img)) > 0.80 and (box_h / box_w) > 1.65:
                        continue

            if resolved_conf < conf_thresh:
                continue

            class_name = SENTINEL_CLASS_NAMES.get(resolved_cls, "SMALL MAMMAL")
            display_label = f"{class_name} {int(round(resolved_conf * 100))}%"

            final_detections.append({
                "class_id": resolved_cls,
                "class_name": class_name,
                "subtype": subtype,
                "display_label": display_label,
                "confidence": round(resolved_conf, 4),
                "bbox": [round(v, 1) for v in p_xyxy],
                "bbox_norm": [
                    round(p_xyxy[0] / w_img, 4),
                    round(p_xyxy[1] / h_img, 4),
                    round(p_xyxy[2] / w_img, 4),
                    round(p_xyxy[3] / h_img, 4),
                ],
            })

        # Add any high-confidence unmatched COCO detections (e.g., domestic cat/dog or person)
        for cd in coco_detections:
            if not cd["matched"] and cd["conf"] >= conf_thresh:
                # Ensure it doesn't heavily overlap an already added box
                if any(compute_iou(cd["xyxy"], fd["bbox"]) >= 0.35 for fd in final_detections):
                    continue
                s_cls = cd["sentinel_cls"]
                c_name = SENTINEL_CLASS_NAMES.get(s_cls, "SMALL MAMMAL")
                sub = cd["subtype"]
                conf = cd["conf"]
                xyxy = cd["xyxy"]
                disp = f"{c_name} {int(round(conf * 100))}%"

                final_detections.append({
                    "class_id": s_cls,
                    "class_name": c_name,
                    "subtype": sub,
                    "display_label": disp,
                    "confidence": round(conf, 4),
                    "bbox": [round(v, 1) for v in xyxy],
                    "bbox_norm": [
                        round(xyxy[0] / w_img, 4),
                        round(xyxy[1] / h_img, 4),
                        round(xyxy[2] / w_img, 4),
                        round(xyxy[3] / h_img, 4),
                    ],
                })

        # High-resolution multi-crop fallback for uploaded 12MP photos when full-frame 640 misses distant targets
        if not final_detections and max(h_img, w_img) >= 1200:
            crop_windows = [
                (0.20, 0.20, 0.80, 0.80),
                (0.30, 0.25, 0.75, 0.70),
                (0.125, 0.125, 0.375, 0.375),
                (0.45, 0.20, 0.80, 0.55),
                (0.70, 0.15, 0.98, 0.45),
                (0.15, 0.35, 0.65, 0.80),
            ]
            for rx1, ry1, rx2, ry2 in crop_windows:
                cx1, cy1 = int(rx1 * w_img), int(ry1 * h_img)
                cx2, cy2 = int(rx2 * w_img), int(ry2 * h_img)
                crop_bgr = img_bgr[cy1:cy2, cx1:cx2]
                if crop_bgr.size == 0:
                    continue
                c_res = primary_model.predict(
                    source=crop_bgr,
                    save=False,
                    device=device,
                    conf=max(0.30, conf_thresh * 0.68),
                    verbose=False,
                )[0]
                for cb in c_res.boxes:
                    c_cls = int(cb.cls[0].item())
                    c_conf = float(cb.conf[0].item())
                    bx1, by1, bx2, by2 = [float(v) for v in cb.xyxy[0].tolist()]
                    full_xyxy = [cx1 + bx1, cy1 + by1, cx1 + bx2, cy1 + by2]
                    c_name = SENTINEL_CLASS_NAMES.get(c_cls, "SMALL MAMMAL")
                    disp = f"{c_name} {int(round(c_conf * 100))}%"
                    final_detections.append({
                        "class_id": c_cls,
                        "class_name": c_name,
                        "subtype": c_name.lower(),
                        "display_label": disp,
                        "confidence": round(c_conf, 4),
                        "bbox": [round(v, 1) for v in full_xyxy],
                        "bbox_norm": [
                            round(full_xyxy[0] / w_img, 4),
                            round(full_xyxy[1] / h_img, 4),
                            round(full_xyxy[2] / w_img, 4),
                            round(full_xyxy[3] / h_img, 4),
                        ],
                    })
                if final_detections:
                    break

    return final_detections


# Warm up TensorRT / CUDA models at server startup so Live Camera detects immediately
# without waiting for a manual picture upload scan to initialize the GPU context.
try:
    print("[AI] Warming up Dual-Model Cascade on GPU...")
    _warmup_bgr = np.zeros((640, 640, 3), dtype=np.uint8)
    run_dual_model_cascade(_warmup_bgr, conf_thresh=0.5)
    print("[AI] GPU Warmup complete — real-time Live Camera inference ready.")
except Exception as _warmup_err:
    print(f"[AI] Warmup note: {_warmup_err}")


def draw_tactical_boxes(img_bgr, detections):
    """
    Renders clean, high-contrast tactical bounding boxes & telemetry tags onto a BGR frame.
    """
    canvas = img_bgr.copy()
    h_img, w_img = canvas.shape[:2]
    scale = max(0.55, min(1.2, w_img / 960.0))
    thickness = max(2, int(round(2.5 * scale)))

    # Color map in OpenCV BGR
    colors_bgr = {
        2: (60, 68, 248),    # LARGE MAMMAL: Crimson Red (#F8443C)
        1: (24, 165, 245),   # SMALL MAMMAL: Amber Orange (#F5A518)
        0: (255, 182, 56),   # BIRD: Tactical Sky Blue (#38B6FF)
        3: (110, 198, 46),   # SAFE (HUMAN): Emerald Green (#2EC66E)
    }

    for det in detections:
        cls_id = det["class_id"]
        color = colors_bgr.get(cls_id, (255, 182, 56))
        x1, y1, x2, y2 = [int(round(v)) for v in det["bbox"]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w_img - 1, x2), min(h_img - 1, y2)

        # Main bounding box
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)

        # Corner tactical brackets
        corner_len = max(10, min(28, int(min(x2 - x1, y2 - y1) * 0.22)))
        c_thick = thickness + 1
        # Top-left
        cv2.line(canvas, (x1, y1), (x1 + corner_len, y1), color, c_thick)
        cv2.line(canvas, (x1, y1), (x1, y1 + corner_len), color, c_thick)
        # Top-right
        cv2.line(canvas, (x2, y1), (x2 - corner_len, y1), color, c_thick)
        cv2.line(canvas, (x2, y1), (x2, y1 + corner_len), color, c_thick)
        # Bottom-left
        cv2.line(canvas, (x1, y2), (x1 + corner_len, y2), color, c_thick)
        cv2.line(canvas, (x1, y2), (x1, y2 - corner_len), color, c_thick)
        # Bottom-right
        cv2.line(canvas, (x2, y2), (x2 - corner_len, y2), color, c_thick)
        cv2.line(canvas, (x2, y2), (x2, y2 - corner_len), color, c_thick)

        # Label pill
        label = det["display_label"]
        font_scale = 0.56 * scale
        font_thick = max(1, int(round(1.8 * scale)))
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, font_scale, font_thick)
        pad_x, pad_y = 8, 6
        lbl_y1 = max(0, y1 - th - pad_y * 2)
        lbl_y2 = lbl_y1 + th + pad_y * 2
        lbl_x2 = min(w_img - 1, x1 + tw + pad_x * 2)

        cv2.rectangle(canvas, (x1, lbl_y1), (lbl_x2, lbl_y2), color, -1)
        text_color = (10, 14, 20) if cls_id in (0, 1, 3) else (255, 255, 255)
        cv2.putText(
            canvas,
            label,
            (x1 + pad_x, lbl_y2 - pad_y - 1),
            cv2.FONT_HERSHEY_DUPLEX,
            font_scale,
            text_color,
            font_thick,
            cv2.LINE_AA,
        )

    return canvas


def evaluate_deterrent_plan(detections):
    """
    Deterministic Threat Hierarchy & Tiered Sound Duration Randomization:
      - SAFETY OVERRIDE FIRST: If ANY Human (Class 3: SAFE) is detected -> Override to SAFE (0 Deterrents)
      - Otherwise: LARGE MAMMAL (Class 2) > SMALL MAMMAL (Class 1) > BIRD (Class 0) > None
      - Bird: Sound + Light (3000 - 6000 ms)
      - Small Mammal: Water + Sound (5000 - 9000 ms)
      - Large Mammal: Sound + Light + Water [All 3 always] (8000 - 14000 ms)
      - Human / Class 3: SAFE Alert — 0 Deterrents
    """
    if not detections:
        return {
            "primary_target": "None",
            "action_taken": "Area Clear — No Deterrents",
            "actuators": [],
            "esp32_token": None,
            "sound_duration_ms": 0,
            "max_confidence": 0.0,
        }

    threat_detections = [d for d in detections if d["class_id"] in (0, 1, 2)]
    safe_detections = [d for d in detections if d["class_id"] == 3]

    # HUMAN SAFETY OVERRIDE: If any human (Class 3: SAFE) is in the frame, override to SAFE
    # and do NOT engage any deterrents (even if a pet or animal is also in the frame).
    if safe_detections:
        max_safe_conf = max((d["confidence"] for d in safe_detections), default=0.0)
        return {
            "primary_target": "SAFE",
            "action_taken": "SAFE Alert — Human Verified (0 Deterrents)",
            "actuators": [],
            "esp32_token": None,
            "sound_duration_ms": 0,
            "max_confidence": max_safe_conf,
        }

    if threat_detections:
        highest_cls = max(d["class_id"] for d in threat_detections)
        max_conf = max(d["confidence"] for d in threat_detections if d["class_id"] == highest_cls)

        if highest_cls == 2:
            return {
                "primary_target": "LARGE MAMMAL",
                "action_taken": "Sound Alarm + Flashing Light + Water Sprinkler",
                "actuators": ["SOUND", "LIGHT", "WATER"],
                "esp32_token": "LARGE",
                "sound_duration_ms": random.randint(8000, 14000),
                "max_confidence": max_conf,
            }
        elif highest_cls == 1:
            return {
                "primary_target": "SMALL MAMMAL",
                "action_taken": "Water Sprinkler + Sound Alarm",
                "actuators": ["WATER", "SOUND"],
                "esp32_token": "SMALL",
                "sound_duration_ms": random.randint(5000, 9000),
                "max_confidence": max_conf,
            }
        else:
            return {
                "primary_target": "BIRD",
                "action_taken": "Sound Alarm + Flashing Light",
                "actuators": ["SOUND", "LIGHT"],
                "esp32_token": "BIRD",
                "sound_duration_ms": random.randint(3000, 6000),
                "max_confidence": max_conf,
            }

    return {
        "primary_target": "None",
        "action_taken": "Area Clear — No Deterrents",
        "actuators": [],
        "esp32_token": None,
        "sound_duration_ms": 0,
        "max_confidence": 0.0,
    }


# ==============================================================================
# ESP32 SOFTAP TELEMETRY & ZERO-LATENCY COMMAND DISPATCHER
# ==============================================================================
_deterrent_state = {
    "esp32_online": False,
    "esp32_ip": os.environ.get("ESP32_HOST", "192.168.4.1"),
    "last_target": "NONE",
    "active_actuators": [],
    "trigger_start_epoch": 0.0,
    "duration_ms": 0,
    "last_live_trigger_epoch": 0.0,
}
_state_lock = threading.Lock()


def get_active_deterrent_telemetry():
    with _state_lock:
        now = time.time()
        elapsed_ms = int((now - _deterrent_state["trigger_start_epoch"]) * 1000)
        total_ms = _deterrent_state["duration_ms"]
        if total_ms > 0 and elapsed_ms < total_ms:
            remaining_ms = total_ms - elapsed_ms
            active_actuators = list(_deterrent_state["active_actuators"])
            is_active = True
        else:
            remaining_ms = 0
            total_ms = 0
            active_actuators = []
            is_active = False

        return {
            "esp32_online": _deterrent_state["esp32_online"],
            "esp32_ip": _deterrent_state["esp32_ip"],
            "is_active": is_active,
            "last_target": _deterrent_state["last_target"],
            "active_actuators": active_actuators,
            "duration_ms": total_ms,
            "remaining_ms": remaining_ms,
        }


def dispatch_esp32_command(animal_token, duration_ms=0, actuators=None):
    """
    Dispatches a low-latency HTTP command to the ESP32 SoftAP (192.168.4.1)
    and updates local real-time actuator telemetry for the dashboard.
    """
    if actuators is None:
        actuators = []

    with _state_lock:
        if animal_token in ("STOP", "OFF"):
            _deterrent_state["active_actuators"] = []
            _deterrent_state["duration_ms"] = 0
            _deterrent_state["trigger_start_epoch"] = 0.0
        else:
            _deterrent_state["last_target"] = animal_token
            _deterrent_state["active_actuators"] = list(actuators)
            _deterrent_state["duration_ms"] = int(duration_ms)
            _deterrent_state["trigger_start_epoch"] = time.time()

    def _worker():
        # Send both query params and stringified JSON duration for 100% compatibility
        payload_dict = {
            "animal": str(animal_token),
            "duration": str(int(duration_ms)) if duration_ms > 0 else "0",
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        hosts = [
            os.environ.get("ESP32_HOST", "192.168.4.1"),
            "esp32.local",
        ]
        for host in hosts:
            if not host:
                continue
            q_animal = urllib.parse.quote(str(animal_token))
            q_dur = int(duration_ms)
            url = f"http://{host}/command?animal={q_animal}&duration={q_dur}" if q_dur > 0 else f"http://{host}/command?animal={q_animal}"
            try:
                req = urllib.request.Request(
                    url,
                    data=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "Connection": "keep-alive",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=1.2) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                    try:
                        resp_json = json.loads(body)
                        esp_dur = int(resp_json.get("duration_ms", duration_ms) or duration_ms)
                    except Exception:
                        esp_dur = duration_ms

                    with _state_lock:
                        _deterrent_state["esp32_online"] = True
                        _deterrent_state["esp32_ip"] = host
                        if animal_token not in ("STOP", "OFF") and esp_dur > 0:
                            _deterrent_state["duration_ms"] = esp_dur
                    print(f"[ESP32 HTTP] >>> Triggered '{animal_token}' ({esp_dur} ms) at {host} (HTTP {resp.status}) <<<")
                    return
            except Exception:
                pass

        with _state_lock:
            _deterrent_state["esp32_online"] = False
        print(f"[ESP32 INFO] Node 192.168.4.1 unreachable (Simulated telemetry active on dashboard).")

    threading.Thread(target=_worker, daemon=True).start()


THREAT_TOKEN_RANK = {"BIRD": 1, "SMALL": 2, "LARGE": 3}

_live_temporal_lock = threading.Lock()
_live_temporal_state = {
    "prev_detections": [],
    "prev_time": 0.0,
}


def sync_deterrents_with_plan(plan):
    """
    Enforces strict real-time hardware deterrent rules for both Live Camera and Video:
      1. If a Human ('SAFE') is on screen -> STOP deterrents immediately.
      2. If NO 'SAFE' is detected on screen and an Animal ('BIRD', 'SMALL MAMMAL', 'LARGE MAMMAL')
         is detected -> TURN ON deterrents immediately (or escalate immediately if a higher
         threat tier appears).
    Returns True if a deterrent trigger command was dispatched, False otherwise.
    """
    now = time.time()
    primary_target = plan.get("primary_target", "None")
    esp32_token = plan.get("esp32_token")

    # 1. HUMAN ON SCREEN -> STOP DETERRENTS IMMEDIATELY
    if primary_target == "SAFE":
        should_stop = False
        with _state_lock:
            active_rem = max(
                0.0,
                (_deterrent_state["duration_ms"] / 1000.0) - (now - _deterrent_state["trigger_start_epoch"]),
            )
            if (
                active_rem > 0.0
                or len(_deterrent_state["active_actuators"]) > 0
                or _deterrent_state.get("last_target") not in ("NONE", "STOP", "OFF")
            ):
                should_stop = True
                _deterrent_state["last_live_trigger_epoch"] = 0.0
                _deterrent_state["last_target"] = "STOP"
        if should_stop:
            dispatch_esp32_command("STOP", duration_ms=0, actuators=[])
        return False

    # 2. NO SAFE ON SCREEN + ANIMAL DETECTED -> TURN ON DETERRENTS IMMEDIATELY
    if esp32_token:
        should_fire = False
        with _state_lock:
            active_rem = max(
                0.0,
                (_deterrent_state["duration_ms"] / 1000.0) - (now - _deterrent_state["trigger_start_epoch"]),
            )
            cur_target = _deterrent_state.get("last_target", "NONE")
            cur_rank = THREAT_TOKEN_RANK.get(cur_target, 0) if active_rem > 0.35 else 0
            new_rank = THREAT_TOKEN_RANK.get(esp32_token, 1)

            if active_rem <= 0.35 or not _deterrent_state["active_actuators"] or new_rank > cur_rank:
                should_fire = True
                _deterrent_state["last_live_trigger_epoch"] = now

        if should_fire:
            dispatch_esp32_command(
                esp32_token,
                duration_ms=plan["sound_duration_ms"],
                actuators=plan["actuators"],
            )
            return True

    return False


# ==============================================================================
# VIDEO ANNOTATION & THREAT TIMELINE PIPELINE
# ==============================================================================
def process_uploaded_video(filepath, unique_stem, conf_thresh=0.50):
    conf_thresh = max(0.50, float(conf_thresh))
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened():
        raise RuntimeError("Could not open uploaded video file.")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1.0 or fps > 120.0:
        fps = 24.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = (total_frames / fps) if total_frames > 0 else 0.0

    # Downscale very high-res video slightly if needed for fast laptop/Jetson rendering
    max_dim = 960
    if max(width, height) > max_dim:
        scale = max_dim / float(max(width, height))
        out_w = int(round(width * scale / 2.0) * 2)
        out_h = int(round(height * scale / 2.0) * 2)
    else:
        out_w = width - (width % 2)
        out_h = height - (height % 2)

    # Try fast browser-native H.264 MP4 ('avc1') first, then VP8 WebM ('vp80'), then mp4v
    out_filename = f"{unique_stem}.mp4"
    out_filepath = os.path.join(app.config["RESULTS_FOLDER"], out_filename)
    writer = None
    for codec, ext in [("avc1", ".mp4"), ("vp80", ".webm"), ("mp4v", ".mp4")]:
        candidate_name = f"{unique_stem}{ext}"
        candidate_path = os.path.join(app.config["RESULTS_FOLDER"], candidate_name)
        fourcc = cv2.VideoWriter_fourcc(*codec)
        w = cv2.VideoWriter(candidate_path, fourcc, fps, (out_w, out_h))
        if w.isOpened():
            writer = w
            out_filename = candidate_name
            out_filepath = candidate_path
            break
        else:
            if os.path.exists(candidate_path):
                try:
                    os.remove(candidate_path)
                except Exception:
                    pass

    if writer is None:
        cap.release()
        raise RuntimeError("Failed to initialize OpenCV VideoWriter.")

    # Sample ~5 times per second for AI inference so video processing finishes rapidly
    sample_stride = max(1, int(round(fps / 5.0)))
    frame_idx = 0
    last_detections = []
    all_detections_summary = []
    unmasked_threat_detections = []
    last_active_plan = None
    timeline_markers = []
    peak_frame_bgr = None
    peak_threat_tuple = (-1, -1.0)  # (priority_rank, confidence)

    priority_rank_map = {3: 0, 0: 1, 1: 2, 2: 3}

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if (out_w, out_h) != (frame.shape[1], frame.shape[0]):
            frame = cv2.resize(frame, (out_w, out_h))

        if frame_idx % sample_stride == 0:
            last_detections = run_dual_model_cascade(frame, conf_thresh=conf_thresh)
            plan = evaluate_deterrent_plan(last_detections)
            # Deterrents are triggered live during video playback via /api/deterrent/video_sync
            # once analysis completes and the video modal opens automatically on screen.

            if last_detections:
                last_active_plan = plan
                t_sec = round(frame_idx / fps, 2)
                timeline_markers.append({
                    "time_sec": t_sec,
                    "frame": frame_idx,
                    "target": plan["primary_target"],
                    "confidence": round(plan["max_confidence"], 4),
                    "actuators": plan["actuators"],
                    "count": len(last_detections),
                })
                all_detections_summary.extend(last_detections)
                if plan["esp32_token"] is not None:
                    unmasked_threat_detections.extend(last_detections)

                # Track best keyframe thumbnail
                top_cls = max(d["class_id"] for d in last_detections)
                top_conf = max(d["confidence"] for d in last_detections if d["class_id"] == top_cls)
                rank_tuple = (priority_rank_map.get(top_cls, 0), top_conf)
                if rank_tuple > peak_threat_tuple:
                    peak_threat_tuple = rank_tuple
                    peak_frame_bgr = draw_tactical_boxes(frame, last_detections)

        annotated_frame = draw_tactical_boxes(frame, last_detections) if last_detections else frame
        if peak_frame_bgr is None and frame_idx == 0:
            peak_frame_bgr = annotated_frame.copy()

        writer.write(annotated_frame)
        frame_idx += 1

    cap.release()
    writer.release()

    if duration_sec <= 0 and frame_idx > 0:
        duration_sec = frame_idx / fps

    thumb_filename = f"thumb_{unique_stem}.jpg"
    thumb_filepath = os.path.join(app.config["THUMBNAILS_FOLDER"], thumb_filename)
    if peak_frame_bgr is not None:
        cv2.imwrite(thumb_filepath, peak_frame_bgr)

    # If the video had frames where an animal was detected without a human present,
    # summarize the event with that threat plan; otherwise evaluate all detections.
    if unmasked_threat_detections:
        overall_plan = evaluate_deterrent_plan(unmasked_threat_detections)
    else:
        overall_plan = evaluate_deterrent_plan(all_detections_summary)

    return {
        "out_filename": out_filename,
        "thumb_filename": thumb_filename,
        "resolution": f"{width} x {height} px",
        "duration_sec": round(duration_sec, 2),
        "plan": overall_plan,
        "last_active_plan": last_active_plan or overall_plan,
        "timeline": timeline_markers[:240],
        "sample_detections": all_detections_summary[:30],
    }


# ==============================================================================
# REST API ENDPOINTS FOR REACT + TYPESCRIPT DASHBOARD
# ==============================================================================

@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    target_filter = request.args.get("target", "ALL").upper()
    media_filter = request.args.get("media_type", "ALL").lower()
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(6, int(request.args.get("per_page", 24))))

    # Global incursion counts across entire persistent database
    total_scans = DeterrentEvent.query.count()
    large_mammals = DeterrentEvent.query.filter_by(primary_target="LARGE MAMMAL").count()
    small_mammals = DeterrentEvent.query.filter_by(primary_target="SMALL MAMMAL").count()
    birds = DeterrentEvent.query.filter_by(primary_target="BIRD").count()
    safe_humans = DeterrentEvent.query.filter_by(primary_target="SAFE").count()
    clear_scans = DeterrentEvent.query.filter_by(primary_target="None").count()

    query = DeterrentEvent.query
    if target_filter and target_filter != "ALL":
        if target_filter == "SAFE":
            query = query.filter(DeterrentEvent.primary_target.in_(["SAFE", "None"]))
        else:
            query = query.filter_by(primary_target=target_filter)

    if media_filter and media_filter != "all":
        query = query.filter_by(media_type=media_filter)

    pagination = query.order_by(DeterrentEvent.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "metrics": {
            "total_scans": total_scans,
            "large_mammals": large_mammals,
            "small_mammals": small_mammals,
            "birds": birds,
            "safe_humans": safe_humans,
            "clear_scans": clear_scans,
            "safe_total": safe_humans + clear_scans,
        },
        "events": [ev.to_dict() for ev in pagination.items],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": pagination.total,
            "total_pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        },
        "telemetry": get_active_deterrent_telemetry(),
        "models": {
            "primary": os.path.basename(best_weights),
            "secondary": "yolo11n.pt (COCO Offline Cascade)" if coco_verifier else "Geometric Fallback",
            "device": f"CUDA GPU ({torch.cuda.get_device_name(0)})" if torch.cuda.is_available() else "CPU",
            "offline_mode": True,
        },
    })


@app.route("/api/events/<int:event_id>", methods=["GET"])
def api_get_event(event_id):
    ev = DeterrentEvent.query.get_or_404(event_id)
    return jsonify(ev.to_dict())


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def api_delete_event(event_id):
    ev = DeterrentEvent.query.get(event_id)
    if not ev:
        return jsonify({"status": "not_found"}), 404

    for folder, fname in [
        (app.config["RESULTS_FOLDER"], ev.filename),
        (app.config["UPLOAD_FOLDER"], ev.filename),
        (app.config["THUMBNAILS_FOLDER"], ev.thumbnail_filename),
    ]:
        if fname:
            try:
                p = os.path.join(folder, fname)
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    db.session.delete(ev)
    db.session.commit()
    return jsonify({"status": "deleted", "id": event_id})


@app.route("/api/events/clear", methods=["POST"])
def api_clear_events():
    DeterrentEvent.query.delete()
    db.session.commit()
    for folder in [
        app.config["RESULTS_FOLDER"],
        app.config["UPLOAD_FOLDER"],
        app.config["THUMBNAILS_FOLDER"],
    ]:
        for f in glob.glob(os.path.join(folder, "*")):
            try:
                os.remove(f)
            except Exception:
                pass
    return jsonify({"status": "cleared"})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    source_mode = request.form.get("source_mode", "upload")  # upload | live_snapshot
    conf_thresh = max(0.50, float(request.form.get("conf", 0.50)))

    ext = os.path.splitext(file.filename)[1].lower()
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    video_exts = {".mp4", ".mov", ".avi", ".webm", ".mkv"}

    if ext not in image_exts and ext not in video_exts:
        return jsonify({"error": f"Unsupported file format '{ext}'. Upload an image or video."}), 400

    unique_stem = f"scan_{uuid.uuid4().hex[:8]}"
    raw_filename = f"{unique_stem}{ext}"
    upload_path = os.path.join(app.config["UPLOAD_FOLDER"], raw_filename)
    file.save(upload_path)
    file_size_kb = os.path.getsize(upload_path) / 1024.0

    if ext in image_exts:
        img_bgr = cv2.imread(upload_path)
        if img_bgr is None:
            return jsonify({"error": "Failed to decode uploaded image."}), 400

        h_img, w_img = img_bgr.shape[:2]
        resolution = f"{w_img} x {h_img} px"

        detections = run_dual_model_cascade(img_bgr, conf_thresh=conf_thresh)
        annotated_bgr = draw_tactical_boxes(img_bgr, detections)
        plan = evaluate_deterrent_plan(detections)

        result_filename = f"{unique_stem}.jpg"
        result_path = os.path.join(app.config["RESULTS_FOLDER"], result_filename)
        cv2.imwrite(result_path, annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 93])

        sync_deterrents_with_plan(plan)

        ev = DeterrentEvent(
            filename=result_filename,
            thumbnail_filename=None,
            media_type="live_snapshot" if source_mode == "live_snapshot" else "image",
            primary_target=plan["primary_target"],
            action_taken=plan["action_taken"],
            actuators_json=json.dumps(plan["actuators"]),
            sound_duration_ms=plan["sound_duration_ms"],
            confidence=plan["max_confidence"],
            resolution=resolution,
            file_size_kb=file_size_kb,
            video_duration_sec=0.0,
            detections_json=json.dumps(detections),
            timeline_json="[]",
        )
        db.session.add(ev)
        db.session.commit()

        return jsonify({
            "status": "success",
            "event": ev.to_dict(),
            "telemetry": get_active_deterrent_telemetry(),
        })

    else:
        # Video upload pipeline
        try:
            vid_info = process_uploaded_video(upload_path, unique_stem, conf_thresh=conf_thresh)
        except Exception as e:
            return jsonify({"error": f"Video processing error: {e}"}), 500

        plan = vid_info["plan"]
        # Deterrents are triggered live as the video plays inside the auto-opened modal via /api/deterrent/video_sync

        ev = DeterrentEvent(
            filename=vid_info["out_filename"],
            thumbnail_filename=vid_info["thumb_filename"],
            media_type="video",
            primary_target=plan["primary_target"],
            action_taken=plan["action_taken"],
            actuators_json=json.dumps(plan["actuators"]),
            sound_duration_ms=plan["sound_duration_ms"],
            confidence=plan["max_confidence"],
            resolution=vid_info["resolution"],
            file_size_kb=file_size_kb,
            video_duration_sec=vid_info["duration_sec"],
            detections_json=json.dumps(vid_info["sample_detections"]),
            timeline_json=json.dumps(vid_info["timeline"]),
        )
        db.session.add(ev)
        db.session.commit()

        return jsonify({
            "status": "success",
            "event": ev.to_dict(),
            "telemetry": get_active_deterrent_telemetry(),
        })


@app.route("/api/deterrent/video_sync", methods=["POST"])
def api_deterrent_video_sync():
    """
    Synchronizes ESP32 hardware deterrents in real time with video playback:
      - If target == 'SAFE': immediately stops all deterrents.
      - If target in ('LARGE MAMMAL', 'SMALL MAMMAL', 'BIRD'): immediately turns on
        the corresponding tier's deterrents if no SAFE is on screen.
    """
    data = request.get_json(silent=True) or {}
    target = str(data.get("target", "None")).upper()

    if target == "SAFE":
        plan = {
            "primary_target": "SAFE",
            "action_taken": "SAFE Alert — Human Verified (0 Deterrents)",
            "actuators": [],
            "esp32_token": None,
            "sound_duration_ms": 0,
            "max_confidence": 1.0,
        }
        sync_deterrents_with_plan(plan)
        return jsonify({"status": "stopped", "telemetry": get_active_deterrent_telemetry()})

    if target == "LARGE MAMMAL":
        plan = {
            "primary_target": "LARGE MAMMAL",
            "action_taken": "Sound Alarm + Flashing Light + Water Sprinkler",
            "actuators": ["SOUND", "LIGHT", "WATER"],
            "esp32_token": "LARGE",
            "sound_duration_ms": random.randint(8000, 14000),
            "max_confidence": 1.0,
        }
        triggered = sync_deterrents_with_plan(plan)
        return jsonify({"status": "triggered" if triggered else "active", "telemetry": get_active_deterrent_telemetry()})

    if target == "SMALL MAMMAL":
        plan = {
            "primary_target": "SMALL MAMMAL",
            "action_taken": "Water Sprinkler + Sound Alarm",
            "actuators": ["WATER", "SOUND"],
            "esp32_token": "SMALL",
            "sound_duration_ms": random.randint(5000, 9000),
            "max_confidence": 1.0,
        }
        triggered = sync_deterrents_with_plan(plan)
        return jsonify({"status": "triggered" if triggered else "active", "telemetry": get_active_deterrent_telemetry()})

    if target == "BIRD":
        plan = {
            "primary_target": "BIRD",
            "action_taken": "Sound Alarm + Flashing Light",
            "actuators": ["SOUND", "LIGHT"],
            "esp32_token": "BIRD",
            "sound_duration_ms": random.randint(3000, 6000),
            "max_confidence": 1.0,
        }
        triggered = sync_deterrents_with_plan(plan)
        return jsonify({"status": "triggered" if triggered else "active", "telemetry": get_active_deterrent_telemetry()})

    return jsonify({"status": "clear", "telemetry": get_active_deterrent_telemetry()})


@app.route("/api/live/detect", methods=["POST"])
def api_live_detect():
    """
    Real-time frame inference endpoint for Full-Screen Live Camera Mode.
    Accepts a frame blob ('frame') OR 'use_csi=true' to grab the latest frame
    from JetsonCameraHub, runs the offline Dual-Model Cascade with a 50% confidence floor
    and 2-frame temporal verification window ("scan a smidge longer before drawing boxes"),
    stops deterrents immediately when a human ('SAFE') is on screen, and turns on deterrents
    immediately when no 'SAFE' is detected and an animal is detected.
    """
    save_snapshot = request.form.get("save_snapshot", "false").lower() == "true"
    auto_trigger = request.form.get("auto_trigger", "true").lower() == "true"
    conf_thresh = max(0.50, float(request.form.get("conf", 0.50)))
    use_csi = request.form.get("use_csi", "false").lower() == "true"

    if "frame" in request.files:
        file = request.files["frame"]
        file_bytes = np.frombuffer(file.read(), np.uint8)
        img_bgr = cv2.imdecode(file_bytes, np.uint8 if False else cv2.IMREAD_COLOR)
        if img_bgr is None:
            return jsonify({"error": "Invalid frame data"}), 400
        # Apply Auto White Balance to eliminate IMX219 purple/pink tint
        img_bgr = _global_awb.balance(img_bgr)
    elif use_csi:
        img_bgr = JetsonCameraHub.get_instance().get_frame()
        if img_bgr is None:
            return jsonify({"error": "CSI camera frame not ready yet"}), 503
    else:
        return jsonify({"error": "Missing frame blob"}), 400

    t0 = time.perf_counter()
    h_img, w_img = img_bgr.shape[:2]
    raw_detections = run_dual_model_cascade(img_bgr, conf_thresh=conf_thresh)

    # Multi-frame temporal verification: scan a smidge longer before drawing bounding boxes
    # for newly appearing targets so 1-frame transient false positives are filtered out.
    now_ts = time.time()
    with _live_temporal_lock:
        prev_dets = list(_live_temporal_state["prev_detections"])
        prev_time = float(_live_temporal_state["prev_time"])

    if not raw_detections:
        with _live_temporal_lock:
            _live_temporal_state["prev_detections"] = []
            _live_temporal_state["prev_time"] = now_ts
        detections = []
    else:
        has_recent_history = (now_ts - prev_time) <= 1.8 and len(prev_dets) > 0
        all_matched_prev = False
        if has_recent_history:
            all_matched_prev = all(
                any(
                    d["class_id"] == pd["class_id"] and compute_iou(d["bbox"], pd["bbox"]) >= 0.20
                    for pd in prev_dets
                )
                for d in raw_detections
            )

        if all_matched_prev:
            detections = raw_detections
            with _live_temporal_lock:
                _live_temporal_state["prev_detections"] = raw_detections
                _live_temporal_state["prev_time"] = now_ts
        elif use_csi:
            # Scan a smidge longer (~140 ms) on a fresh camera frame to confirm persistence
            time.sleep(0.14)
            frame2 = JetsonCameraHub.get_instance().get_frame()
            if frame2 is not None:
                dets2 = run_dual_model_cascade(frame2, conf_thresh=conf_thresh)
                confirmed = []
                for d2 in dets2:
                    if any(
                        d2["class_id"] == d1["class_id"] and compute_iou(d2["bbox"], d1["bbox"]) >= 0.20
                        for d1 in raw_detections
                    ) or (
                        d2["class_id"] == 3 and any(d1["class_id"] == 3 for d1 in raw_detections)
                    ):
                        confirmed.append(d2)
                detections = confirmed
                img_bgr = frame2
                h_img, w_img = img_bgr.shape[:2]
                with _live_temporal_lock:
                    _live_temporal_state["prev_detections"] = dets2
                    _live_temporal_state["prev_time"] = time.time()
            else:
                detections = raw_detections
        else:
            detections = raw_detections

    plan = evaluate_deterrent_plan(detections)
    infer_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    triggered_now = False
    if plan["primary_target"] == "SAFE":
        # Always stop deterrents immediately when a human is on screen
        sync_deterrents_with_plan(plan)
    elif auto_trigger and plan["esp32_token"]:
        # Turn on deterrents immediately when no SAFE is detected and an animal is detected
        triggered_now = sync_deterrents_with_plan(plan)

    saved_event_dict = None
    if save_snapshot:
        unique_stem = f"live_{uuid.uuid4().hex[:8]}"
        result_filename = f"{unique_stem}.jpg"
        result_path = os.path.join(app.config["RESULTS_FOLDER"], result_filename)
        annotated_bgr = draw_tactical_boxes(img_bgr, detections)
        cv2.imwrite(result_path, annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        file_size_kb = os.path.getsize(result_path) / 1024.0

        # Also trigger deterrent immediately on manual snapshot if threat present and no SAFE
        if plan["esp32_token"] and not triggered_now:
            triggered_now = sync_deterrents_with_plan(plan)

        ev = DeterrentEvent(
            filename=result_filename,
            thumbnail_filename=None,
            media_type="live_snapshot",
            primary_target=plan["primary_target"],
            action_taken=plan["action_taken"],
            actuators_json=json.dumps(plan["actuators"]),
            sound_duration_ms=plan["sound_duration_ms"],
            confidence=plan["max_confidence"],
            resolution=f"{w_img} x {h_img} px",
            file_size_kb=file_size_kb,
            video_duration_sec=0.0,
            detections_json=json.dumps(detections),
            timeline_json="[]",
        )
        db.session.add(ev)
        db.session.commit()
        saved_event_dict = ev.to_dict()

    return jsonify({
        "detections": detections,
        "primary_target": plan["primary_target"],
        "action_taken": plan["action_taken"],
        "actuators": plan["actuators"],
        "sound_duration_ms": plan["sound_duration_ms"],
        "max_confidence": round(plan["max_confidence"], 4),
        "inference_ms": infer_ms,
        "triggered_now": triggered_now,
        "saved_event": saved_event_dict,
        "telemetry": get_active_deterrent_telemetry(),
    })


@app.route("/api/deterrent/test", methods=["POST"])
def api_deterrent_test():
    """
    Tests each of the 3 deterrents individually:
      - actuator = 'SOUND' (with pattern = 'BIRD' | 'SMALL' | 'LARGE' and randomized duration)
      - actuator = 'WATER' (sends 'WATER_TEST' to ESP32 + activates dashboard telemetry)
      - actuator = 'LIGHT' (sends 'LIGHT_TEST' to ESP32 + activates dashboard telemetry)
    """
    data = request.get_json(silent=True) or {}
    actuator = str(data.get("actuator", "SOUND")).upper()
    pattern = str(data.get("pattern", "LARGE")).upper()

    if actuator == "SOUND":
        if "BIRD" in pattern:
            dur_ms = random.randint(3000, 6000)
            token = "BIRD"
        elif "SMALL" in pattern:
            dur_ms = random.randint(5000, 9000)
            token = "SMALL"
        else:
            dur_ms = random.randint(8000, 14000)
            token = "LARGE"
        dispatch_esp32_command(f"SOUND_TEST_{token}", duration_ms=dur_ms, actuators=["SOUND"])
        return jsonify({
            "status": "triggered",
            "actuator": "SOUND",
            "pattern": token,
            "duration_ms": dur_ms,
            "telemetry": get_active_deterrent_telemetry(),
        })

    elif actuator == "WATER":
        if "LARGE" in pattern:
            dur_ms = random.randint(5000, 9000)
        else:
            dur_ms = random.randint(2500, 5000)
        dispatch_esp32_command("WATER_TEST", duration_ms=dur_ms, actuators=["WATER"])
        return jsonify({
            "status": "triggered",
            "actuator": "WATER",
            "pattern": "WATER_TEST",
            "duration_ms": dur_ms,
            "telemetry": get_active_deterrent_telemetry(),
        })

    elif actuator == "LIGHT":
        dur_ms = int(data.get("duration_ms", 5000))
        dispatch_esp32_command("LIGHT_TEST", duration_ms=dur_ms, actuators=["LIGHT"])
        return jsonify({
            "status": "triggered",
            "actuator": "LIGHT",
            "pattern": "LIGHT_TEST",
            "duration_ms": dur_ms,
            "telemetry": get_active_deterrent_telemetry(),
        })

    return jsonify({"error": f"Unknown actuator '{actuator}'"}), 400


@app.route("/api/deterrent/stop", methods=["POST"])
def api_deterrent_stop():
    dispatch_esp32_command("STOP", duration_ms=0, actuators=[])
    return jsonify({
        "status": "stopped",
        "telemetry": get_active_deterrent_telemetry(),
    })


@app.route("/api/esp32/status", methods=["GET"])
def api_esp32_status():
    probe = request.args.get("probe", "false").lower() == "true"
    if probe:
        host = os.environ.get("ESP32_HOST", "192.168.4.1")
        try:
            req = urllib.request.Request(f"http://{host}/status", method="GET")
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                with _state_lock:
                    _deterrent_state["esp32_online"] = True
                    _deterrent_state["esp32_ip"] = data.get("ip", host)
        except Exception:
            with _state_lock:
                _deterrent_state["esp32_online"] = False

    return jsonify(get_active_deterrent_telemetry())


# ==============================================================================
# CAMERA HARDWARE & STREAMING ENGINE (SINGLE-THREADED HUB + IMX219 CSI + AWB)
# ==============================================================================

class DashboardGrayWorldAWB:
    """Software Auto White Balance for neutralizing IMX219 color cast."""
    def __init__(self, smoothing: float = 0.85):
        self.smoothing = smoothing
        self.running_gain = None

    def balance(self, bgr_frame: np.ndarray) -> np.ndarray:
        if bgr_frame is None or bgr_frame.size == 0:
            return bgr_frame
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

_global_awb = DashboardGrayWorldAWB()

_camera_state = {
    "mirror_h": True,
    "mirror_v": False,
    "rotation": 0,
    "awb": True,
    "sensor_id": int(os.environ.get("CSI_SENSOR_ID", "0")),
    "flip_method": int(os.environ.get("CSI_FLIP_METHOD", "0")),
}


class JetsonCameraHub:
    """
    Thread-safe Singleton Camera Hub for Jetson IMX219.
    A single background thread exclusively owns cv2.VideoCapture to eliminate
    EGLStream race conditions and GStreamer concurrency crashes.
    """
    _instance = None
    _hub_lock = threading.Lock()

    def __init__(self):
        self.cap = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_jpeg = None
        self.last_client_time = 0.0

    @classmethod
    def get_instance(cls):
        with cls._hub_lock:
            if cls._instance is None:
                cls._instance = JetsonCameraHub()
            return cls._instance

    def _open_camera(self):
        sid = _camera_state.get("sensor_id", 0)
        flip = _camera_state.get("flip_method", 0)
        # Bare hardware GStreamer pipeline (camera_overrides.isp + software AWB handle white balance;
        # never fall back to cv2.VideoCapture(0) V4L2 which corrupts IMX219 Argus subdev state).
        pipe = (
            f"nvarguscamerasrc sensor-id={sid} ! "
            f"video/x-raw(memory:NVMM), width=1920, height=1080, framerate=30/1 ! "
            f"nvvidconv flip-method={flip} ! "
            f"video/x-raw, width=1280, height=720, format=BGRx ! "
            f"videoconvert ! "
            f"video/x-raw, format=BGR ! appsink drop=1"
        )
        cap = cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            time.sleep(1.5)
            cap = cv2.VideoCapture(pipe, cv2.CAP_GSTREAMER)
        return cap

    def start_if_needed(self):
        with self.lock:
            self.last_client_time = time.time()
            if self.running and self.thread and self.thread.is_alive():
                return
            self.running = True
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()

    def _worker(self):
        print("[CAM-HUB] Starting dedicated single-owner capture thread...")
        try:
            self.cap = self._open_camera()
            if not self.cap or not self.cap.isOpened():
                print("[CAM-HUB] Warning: Unable to open camera pipeline.")
                self.running = False
                return

            print("[CAM-HUB] Camera stream active and locked to hub thread.")
            while self.running:
                # Idle auto-release if no clients have requested frames for 120s
                if time.time() - self.last_client_time > 120.0:
                    print("[CAM-HUB] No active streaming clients for 120s. Sleeping camera.")
                    break

                ret, frame = self.cap.read()
                if not ret or frame is None:
                    # Do NOT call self.cap.read() again on a halted GStreamer capture,
                    # because OpenCV's grabFrame() attempts an in-place startPipeline()
                    # on the same nvarguscamerasrc element, triggering INVALID_SETTINGS.
                    print("[CAM-HUB] Stream read interrupted; recreating clean GStreamer pipeline...")
                    try:
                        if self.cap:
                            self.cap.release()
                    except Exception:
                        pass
                    self.cap = None
                    time.sleep(1.0)
                    if not self.running:
                        break
                    self.cap = self._open_camera()
                    if not self.cap or not self.cap.isOpened():
                        print("[CAM-HUB] Camera re-initialization failed; exiting worker for clean retry.")
                        break
                    continue

                # Process rotation, mirror, AWB
                rot = _camera_state.get("rotation", 0)
                mh = _camera_state.get("mirror_h", False)
                mv = _camera_state.get("mirror_v", False)
                do_awb = _camera_state.get("awb", True)

                if rot == 90:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif rot == 180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif rot == 270:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

                if mh:
                    frame = cv2.flip(frame, 1)
                if mv:
                    frame = cv2.flip(frame, 0)

                if do_awb:
                    frame = _global_awb.balance(frame)

                ret_enc, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ret_enc:
                    with self.lock:
                        self.latest_frame = frame
                        self.latest_jpeg = jpeg.tobytes()
        except Exception as e:
            print(f"[CAM-HUB] Worker error: {e}")
        finally:
            with self.lock:
                self.running = False
                if self.cap:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None
            print("[CAM-HUB] Camera worker stopped cleanly.")

    def get_jpeg(self):
        self.start_if_needed()
        with self.lock:
            self.last_client_time = time.time()
            return self.latest_jpeg

    def get_frame(self):
        self.start_if_needed()
        deadline = time.time() + 4.5
        while time.time() < deadline:
            with self.lock:
                self.last_client_time = time.time()
                if self.latest_frame is not None:
                    return self.latest_frame.copy()
                if not self.running:
                    break
            time.sleep(0.05)
        with self.lock:
            self.last_client_time = time.time()
            return self.latest_frame.copy() if self.latest_frame is not None else None


@app.route("/api/camera/control", methods=["GET", "POST"])
def api_camera_control():
    """Get or update live camera settings (mirror, rotation, AWB)."""
    global _camera_state
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form.to_dict()
        if "mirror_h" in data:
            _camera_state["mirror_h"] = str(data["mirror_h"]).lower() in ("true", "1")
        if "mirror_v" in data:
            _camera_state["mirror_v"] = str(data["mirror_v"]).lower() in ("true", "1")
        if "toggle_mirror" in data:
            _camera_state["mirror_h"] = not _camera_state["mirror_h"]
        if "rotation" in data:
            _camera_state["rotation"] = int(data["rotation"]) % 360
        if "rotate" in data:
            _camera_state["rotation"] = (_camera_state["rotation"] + 90) % 360
        if "flip" in data:
            _camera_state["rotation"] = (_camera_state["rotation"] + 180) % 360
        if "awb" in data:
            _camera_state["awb"] = str(data["awb"]).lower() in ("true", "1")
        if "toggle_awb" in data:
            _camera_state["awb"] = not _camera_state["awb"]

    return jsonify({"status": "ok", "settings": _camera_state})


@app.route("/api/camera/stream")
def api_camera_stream():
    """MJPEG live camera stream from Jetson IMX219 with AWB, orientation, and mirror."""
    hub = JetsonCameraHub.get_instance()
    hub.start_if_needed()

    def _stream_gen():
        last_frame_bytes = None
        while True:
            jpeg_bytes = hub.get_jpeg()
            if jpeg_bytes is not None and jpeg_bytes != last_frame_bytes:
                last_frame_bytes = jpeg_bytes
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
                    + jpeg_bytes + b"\r\n"
                )
            time.sleep(0.03)

    resp = Response(_stream_gen(), mimetype="multipart/x-mixed-replace; boundary=frame")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ==============================================================================
# MEDIA & STATIC SPA SERVING
# ==============================================================================

@app.route("/results/<path:filename>")
def serve_result(filename):
    response = send_from_directory(app.config["RESULTS_FOLDER"], filename)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/thumbnails/<path:filename>")
def serve_thumbnail(filename):
    response = send_from_directory(app.config["THUMBNAILS_FOLDER"], filename)
    response.headers["Cache-Control"] = "max-age=3600"
    return response


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path):
    if path and os.path.exists(os.path.join(FRONTEND_DIST, path)):
        response = send_from_directory(FRONTEND_DIST, path, conditional=False)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        response = send_from_directory(FRONTEND_DIST, "index.html", conditional=False)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return (
        "<h3>Sentinel Frontend Build Not Found</h3><p>Run <code>npm run build</code> inside <code>Wildlife Deterrent System/frontend</code>.</p>",
        503,
    )


if __name__ == "__main__":
    print("\n" + "=" * 68)
    print("  SENTINEL WILDLIFE DETERRENT SYSTEM — COMMAND DASHBOARD v2.0")
    print("  Local Laptop URL : http://127.0.0.1:5002")
    print("  Offline Mode     : ENABLED (Dual-Model YOLOv11m + COCO Cascade)")
    print("=" * 68 + "\n")
    JetsonCameraHub.get_instance().start_if_needed()
    app.run(host="0.0.0.0", port=5002, debug=False, threaded=True)
