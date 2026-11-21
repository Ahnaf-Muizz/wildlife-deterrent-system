import os

# Enforce 100% offline Ultralytics execution BEFORE importing ultralytics
os.environ["YOLO_OFFLINE"] = "true"
os.environ["ULTRALYTICS_OFFLINE"] = "1"

import gc
import glob
import math
import uuid
import time
import sqlite3
import zipfile
import cv2
import numpy as np
import random
import json
import urllib.request
import urllib.parse
import threading
import queue
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event as sa_event, Index
from ultralytics import YOLO
import torch
try:
    from PIL import Image
except ImportError:
    Image = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIST = os.path.join(BASE_DIR, "frontend", "dist")

app = Flask(__name__, static_folder=FRONTEND_DIST, static_url_path="")
DB_V4_PATH = os.path.join(BASE_DIR, "sentinel_logs_v4.db")
DB_V3_PATH = os.path.join(BASE_DIR, "sentinel_logs_v3.db")

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_V4_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # Support up to 1024MB video/batch uploads
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
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.close()


def _safe_int(value, default: int, min_v=None, max_v=None) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        return default
    if min_v is not None:
        parsed = max(min_v, parsed)
    if max_v is not None:
        parsed = min(max_v, parsed)
    return parsed


def _safe_float(value, default: float, min_v=None, max_v=None) -> float:
    try:
        parsed = float(str(value).strip())
    except Exception:
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    if min_v is not None:
        parsed = max(min_v, parsed)
    if max_v is not None:
        parsed = min(max_v, parsed)
    return parsed


def _safe_remove_file(path: str | None):
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _decode_image_bgr(filepath: str):
    img = cv2.imread(filepath)
    if img is not None:
        return img
    if Image is not None:
        try:
            with Image.open(filepath) as pil_img:
                rgb = pil_img.convert("RGB")
                arr = np.array(rgb)
                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        except Exception:
            pass
    return None


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
    _modified_safe = False
    for ev in DeterrentEvent.query.filter(DeterrentEvent.primary_target != "SAFE").all():
        try:
            dets = json.loads(ev.detections_json) if ev.detections_json else []
            safe_dets = [d for d in dets if d.get("class_id") == 3]
            if safe_dets:
                ev.primary_target = "SAFE"
                ev.action_taken = "SAFE Alert — Human Verified (0 Deterrents)"
                ev.actuators_json = "[]"
                ev.sound_duration_ms = 0
                ev.confidence = max((float(d.get("confidence", 0.0)) for d in safe_dets), default=ev.confidence)
                _modified_safe = True
        except Exception:
            pass
    if _modified_safe:
        db.session.commit()

# ==============================================================================
# HARDWARE ACCELERATION & 100% OFFLINE DUAL-MODEL YOLO CASCADE
# ==============================================================================
import importlib.util

device = 0 if torch.cuda.is_available() else "cpu"
_inference_lock = threading.Lock()
_has_tensorrt = importlib.util.find_spec("tensorrt") is not None

best_weights = None
if os.environ.get("MODEL_PATH") and os.path.exists(os.environ.get("MODEL_PATH")):
    best_weights = os.environ.get("MODEL_PATH")

if not best_weights:
    candidates = [
        r"C:\wildlife_yolo\runs\y11m_4class_orin\weights\best.pt",
        os.path.join(BASE_DIR, "best.pt"),
        os.path.join(BASE_DIR, "deploy_package", "best.pt"),
        os.path.join(BASE_DIR, "weights", "best.pt"),
    ]
    if _has_tensorrt:
        candidates.insert(0, os.path.join(BASE_DIR, "best.engine"))
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
    os.path.join(BASE_DIR, "yolo11n.pt"),
    os.path.join(BASE_DIR, "deploy_package", "yolo11n.pt"),
]
if _has_tensorrt:
    coco_candidates.insert(0, os.path.join(BASE_DIR, "yolo11n.engine"))
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


def compute_iomin(box_a, box_b):
    """Intersection area divided by the smaller box area (catches nested/contained duplicates)."""
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
    return inter_area / float(min(area_a, area_b))


def _box_area(bbox):
    return max(1.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))


def deduplicate_detections(detections, iou_thresh=0.45, iomin_thresh=0.78):
    """
    Cross-class & containment NMS:
      - Prioritizes SAFE (Human, class 3) first, then descending confidence.
      - Suppresses cross-class or same-class duplicate boxes when IoU >= iou_thresh.
      - For animal threat boxes (0, 1, 2) with IoMin >= iomin_thresh, keeps one box per target
        and swaps in a tighter inner box if it covers < 65% of the outer area with similar confidence.
    """
    if len(detections) <= 1:
        return list(detections)

    ordered = sorted(
        detections,
        key=lambda d: (0 if d["class_id"] == 3 else 1, -float(d["confidence"])),
    )
    kept = []
    for det in ordered:
        det_area = _box_area(det["bbox"])
        suppressed = False
        for i, prev in enumerate(kept):
            if compute_iou(det["bbox"], prev["bbox"]) >= iou_thresh:
                suppressed = True
                break
            if compute_iomin(det["bbox"], prev["bbox"]) >= iomin_thresh:
                if prev["class_id"] in (0, 1, 2) and det["class_id"] in (0, 1, 2):
                    prev_area = _box_area(prev["bbox"])
                    if (
                        det_area < 0.65 * prev_area
                        and float(det["confidence"]) >= float(prev["confidence"]) - 0.08
                    ):
                        kept[i] = det
                    suppressed = True
                    break
                if prev["class_id"] == det["class_id"]:
                    suppressed = True
                    break
        if not suppressed:
            kept.append(det)
    return kept


def _build_detection(cls_id, conf, xyxy, w_img, h_img, subtype=None):
    class_name = SENTINEL_CLASS_NAMES.get(cls_id, "SMALL MAMMAL")
    sub = subtype or class_name.lower()
    display_label = f"{class_name} {int(round(conf * 100))}%"
    return {
        "class_id": cls_id,
        "class_name": class_name,
        "subtype": sub,
        "display_label": display_label,
        "confidence": round(conf, 4),
        "bbox": [round(v, 1) for v in xyxy],
        "bbox_norm": [
            round(xyxy[0] / w_img, 4),
            round(xyxy[1] / h_img, 4),
            round(xyxy[2] / w_img, 4),
            round(xyxy[3] / h_img, 4),
        ],
    }


def _finalize_candidate_detection(img_bgr, p_cls, p_conf, p_xyxy, coco_detections, conf_thresh, h_img, w_img):
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
                return None
        elif p_cls == 1:
            # Reject tall vertical wall/partition false positives when unconfirmed by COCO
            box_w = max(1.0, p_xyxy[2] - p_xyxy[0])
            box_h = max(1.0, p_xyxy[3] - p_xyxy[1])
            if (box_h / float(h_img)) > 0.80 and (box_h / box_w) > 1.65:
                return None

    if resolved_conf < conf_thresh:
        return None

    return _build_detection(resolved_cls, resolved_conf, p_xyxy, w_img, h_img, subtype=subtype)


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

    with _inference_lock, torch.inference_mode():
        primary_res = primary_model.predict(
            source=img_bgr,
            save=False,
            device=device,
            conf=min(0.18, conf_thresh),
            verbose=False,
        )[0]

        strong_boxes = []
        weak_proposals = []
        for pbox in primary_res.boxes:
            p_cls = int(pbox.cls[0].item())
            p_conf = float(pbox.conf[0].item())
            p_xyxy = [float(v) for v in pbox.xyxy[0].tolist()]
            if p_conf >= conf_thresh:
                strong_boxes.append((p_cls, p_conf, p_xyxy))
            else:
                weak_proposals.append((p_cls, p_conf, p_xyxy))

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
        for p_cls, p_conf, p_xyxy in strong_boxes:
            det = _finalize_candidate_detection(
                img_bgr, p_cls, p_conf, p_xyxy, coco_detections, conf_thresh, h_img, w_img
            )
            if det is not None:
                final_detections.append(det)

        # Add any high-confidence unmatched COCO detections (e.g., domestic cat/dog or person)
        for cd in coco_detections:
            if not cd["matched"] and cd["conf"] >= conf_thresh:
                if any(compute_iou(cd["xyxy"], fd["bbox"]) >= 0.35 for fd in final_detections):
                    continue
                final_detections.append(
                    _build_detection(
                        cd["sentinel_cls"],
                        cd["conf"],
                        cd["xyxy"],
                        w_img,
                        h_img,
                        subtype=cd["subtype"],
                    )
                )

        # Stage 2A: Proposal-Guided Focal Zoom around sub-threshold full-frame candidates
        if not final_detections and weak_proposals:
            focal_candidates = [
                item for item in sorted(weak_proposals, key=lambda x: _box_area(x[2]))
                if (item[2][2] - item[2][0]) < 0.75 * w_img
                and (item[2][3] - item[2][1]) < 0.75 * h_img
            ][:4]
            for _, _, (bx1, by1, bx2, by2) in focal_candidates:
                bw = bx2 - bx1
                bh = by2 - by1
                cx = (bx1 + bx2) / 2.0
                cy = (by1 + by2) / 2.0
                half = max(160.0, max(bw, bh) * 0.95)
                cx1 = max(0, int(cx - half))
                cy1 = max(0, int(cy - half))
                cx2 = min(w_img, int(cx + half))
                cy2 = min(h_img, int(cy + half))
                if (cx2 - cx1) < 32 or (cy2 - cy1) < 32:
                    continue
                crop_bgr = img_bgr[cy1:cy2, cx1:cx2]
                if crop_bgr.size == 0:
                    continue
                c_res = primary_model.predict(
                    source=crop_bgr,
                    save=False,
                    device=device,
                    conf=conf_thresh,
                    verbose=False,
                )[0]
                for cb in c_res.boxes:
                    c_cls = int(cb.cls[0].item())
                    c_conf = float(cb.conf[0].item())
                    cbx1, cby1, cbx2, cby2 = [float(v) for v in cb.xyxy[0].tolist()]
                    full_xyxy = [cx1 + cbx1, cy1 + cby1, cx1 + cbx2, cy1 + cby2]
                    det = _finalize_candidate_detection(
                        img_bgr, c_cls, c_conf, full_xyxy, coco_detections, conf_thresh, h_img, w_img
                    )
                    if det is not None:
                        final_detections.append(det)
                if any(d["class_id"] == 3 for d in final_detections):
                    break

        # Stage 2B: Distant-target multi-crop fallback for large images when focal zoom finds nothing
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
                    conf=conf_thresh,
                    verbose=False,
                )[0]
                for cb in c_res.boxes:
                    c_cls = int(cb.cls[0].item())
                    c_conf = float(cb.conf[0].item())
                    bx1, by1, bx2, by2 = [float(v) for v in cb.xyxy[0].tolist()]
                    full_xyxy = [cx1 + bx1, cy1 + by1, cx1 + bx2, cy1 + by2]
                    det = _finalize_candidate_detection(
                        img_bgr, c_cls, c_conf, full_xyxy, coco_detections, conf_thresh, h_img, w_img
                    )
                    if det is not None:
                        final_detections.append(det)
                if final_detections:
                    break

    _cleanup_counter = getattr(run_dual_model_cascade, "_calls", 0) + 1
    run_dual_model_cascade._calls = _cleanup_counter
    if _cleanup_counter % 25 == 0:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    return deduplicate_detections(final_detections)


# Warm up TensorRT / CUDA models at server startup so Live Camera detects immediately
# without waiting for a manual picture upload scan to initialize the GPU context.
try:
    print("[AI] Warming up Dual-Model Cascade on GPU...")
    _warmup_bgr = np.zeros((640, 640, 3), dtype=np.uint8)
    run_dual_model_cascade(_warmup_bgr, conf_thresh=0.5)
    print("[AI] GPU Warmup complete — real-time Live Camera inference ready.")
except Exception as _warmup_err:
    print(f"[AI] Warmup note: {_warmup_err}")


def _rects_overlap(rect_a, rect_b):
    return not (
        rect_a[2] <= rect_b[0]
        or rect_b[2] <= rect_a[0]
        or rect_a[3] <= rect_b[1]
        or rect_b[3] <= rect_a[1]
    )


def _clamp_pill(px1, py1, pill_w, pill_h, w_img, h_img):
    lx1 = max(0, min(w_img - 1 - pill_w, int(px1)))
    ly1 = max(0, min(h_img - 1 - pill_h, int(py1)))
    return (lx1, ly1, min(w_img - 1, lx1 + pill_w), min(h_img - 1, ly1 + pill_h))


def _place_label_pill(x1, y1, x2, y2, pill_w, pill_h, w_img, h_img, occupied_pills):
    candidates = [
        _clamp_pill(x1, y1 - pill_h, pill_w, pill_h, w_img, h_img),
        _clamp_pill(x1 + 2, y1 + 2, pill_w, pill_h, w_img, h_img),
        _clamp_pill(x2 - pill_w, y1 - pill_h, pill_w, pill_h, w_img, h_img),
        _clamp_pill(x1, y2 + 2, pill_w, pill_h, w_img, h_img),
        _clamp_pill(x1 + 2, y2 - pill_h - 2, pill_w, pill_h, w_img, h_img),
        _clamp_pill(x1, y1 + pill_h + 6, pill_w, pill_h, w_img, h_img),
    ]
    for cand in candidates:
        if not any(_rects_overlap(cand, prev) for prev in occupied_pills):
            occupied_pills.append(cand)
            return cand
    fallback = candidates[0]
    for _ in range(4):
        colliders = [prev for prev in occupied_pills if _rects_overlap(fallback, prev)]
        if not colliders:
            break
        next_y = max(prev[3] + 2 for prev in colliders)
        fallback = _clamp_pill(fallback[0], next_y, pill_w, pill_h, w_img, h_img)
    occupied_pills.append(fallback)
    return fallback


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

    # Pass 1: draw all bounding boxes and corner brackets first so lines never cut across label pills
    box_draw_info = []
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
        box_draw_info.append((det, cls_id, color, x1, y1, x2, y2))

    # Pass 2: draw all non-overlapping label pills cleanly on top
    occupied_pills = []
    for det, cls_id, color, x1, y1, x2, y2 in box_draw_info:
        label = det["display_label"]
        font_scale = 0.56 * scale
        font_thick = max(1, int(round(1.8 * scale)))
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, font_scale, font_thick)
        pad_x, pad_y = 8, 6
        pill_w = min(max(1, w_img - 1), tw + pad_x * 2)
        pill_h = min(max(1, h_img - 1), th + pad_y * 2)
        lbl_x1, lbl_y1, lbl_x2, lbl_y2 = _place_label_pill(
            x1, y1, x2, y2, pill_w, pill_h, w_img, h_img, occupied_pills
        )

        cv2.rectangle(canvas, (lbl_x1, lbl_y1), (lbl_x2, lbl_y2), color, -1)
        text_color = (10, 14, 20) if cls_id in (0, 1, 3) else (255, 255, 255)
        cv2.putText(
            canvas,
            label,
            (lbl_x1 + pad_x, lbl_y2 - pad_y - 1),
            cv2.FONT_HERSHEY_DUPLEX,
            font_scale,
            text_color,
            font_thick,
            cv2.LINE_AA,
        )

    return canvas


def _save_image_thumbnail(img_bgr, unique_stem: str, max_dim: int = 360):
    """Writes a lightweight ~15 KB JPEG thumbnail so mobile/desktop cards do not re-download full-res results."""
    try:
        h, w = img_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return None
        longest = max(w, h)
        if longest > max_dim:
            scale = max_dim / float(longest)
            thumb_w = max(1, int(round(w * scale)))
            thumb_h = max(1, int(round(h * scale)))
            thumb_bgr = cv2.resize(img_bgr, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        else:
            thumb_bgr = img_bgr
        thumb_filename = f"thumb_{unique_stem}.jpg"
        thumb_path = os.path.join(app.config["THUMBNAILS_FOLDER"], thumb_filename)
        if cv2.imwrite(thumb_path, thumb_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 78]):
            return thumb_filename
    except Exception as exc:
        print(f"[THUMB] Warning generating thumbnail for {unique_stem}: {exc}")
    return None


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
    "esp32_firmware": "unknown",
    "last_target": "NONE",
    "channel_until": {"SOUND": 0.0, "WATER": 0.0, "LIGHT": 0.0},
    "channel_duration_ms": {"SOUND": 0, "WATER": 0, "LIGHT": 0},
    "last_live_trigger_epoch": 0.0,
    "cmd_seq": 0,
}
_state_lock = threading.Lock()
_esp32_cmd_queue: "queue.Queue[tuple[int, str, int, list[str]]]" = queue.Queue()


def _recompute_active_channels_locked(now: float):
    active = []
    channels = {}
    max_rem_ms = 0
    max_dur_ms = 0
    for ch in ("SOUND", "WATER", "LIGHT"):
        rem = max(0, int((_deterrent_state["channel_until"].get(ch, 0.0) - now) * 1000))
        channels[ch] = rem
        if rem > 0:
            active.append(ch)
            if rem > max_rem_ms:
                max_rem_ms = rem
            dur = int(_deterrent_state["channel_duration_ms"].get(ch, 0))
            if dur > max_dur_ms:
                max_dur_ms = dur
        else:
            _deterrent_state["channel_duration_ms"][ch] = 0
    if max_rem_ms > 0 and max_dur_ms < max_rem_ms:
        max_dur_ms = max_rem_ms
    return active, channels, max_rem_ms, max_dur_ms


def get_active_deterrent_telemetry():
    with _state_lock:
        now = time.time()
        active_actuators, channels, remaining_ms, total_ms = _recompute_active_channels_locked(now)
        is_active = len(active_actuators) > 0
        return {
            "esp32_online": _deterrent_state["esp32_online"],
            "esp32_ip": _deterrent_state["esp32_ip"],
            "esp32_firmware": _deterrent_state["esp32_firmware"],
            "is_active": is_active,
            "last_target": _deterrent_state["last_target"],
            "active_actuators": active_actuators,
            "channels": channels,
            "duration_ms": total_ms if is_active else 0,
            "remaining_ms": remaining_ms if is_active else 0,
        }


def _esp32_send_http(seq: int, animal_token: str, duration_ms: int, actuators: list[str]):
    token_upper = str(animal_token).upper().strip()
    is_stop = token_upper in ("STOP", "OFF", "SAFE", "HUMAN")
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
                    "Connection": "close",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                resp_json = {}
                try:
                    resp_json = json.loads(body)
                    esp_dur = int(resp_json.get("duration_ms", duration_ms) or duration_ms)
                except Exception:
                    esp_dur = duration_ms

                pump_dur = int(resp_json.get("pump_duration_ms", 0) or 0)
                led_dur = int(resp_json.get("led_duration_ms", 0) or 0)
                buz_dur = int(resp_json.get("buzzer_duration_ms", esp_dur) or esp_dur)
                fw = str(resp_json.get("firmware") or "pre-v2.3-unsynced")

                now = time.time()
                with _state_lock:
                    _deterrent_state["esp32_online"] = True
                    _deterrent_state["esp32_ip"] = host
                    _deterrent_state["esp32_firmware"] = fw
                    # Only apply optimistic duration correction if no newer command (especially STOP) superseded this seq
                    if not is_stop and _deterrent_state["cmd_seq"] == seq:
                        if token_upper.startswith("WATER") or token_upper.startswith("PUMP"):
                            if pump_dur > 0:
                                _deterrent_state["channel_until"]["WATER"] = now + (pump_dur / 1000.0)
                                _deterrent_state["channel_duration_ms"]["WATER"] = pump_dur
                        elif token_upper.startswith("LIGHT") or token_upper.startswith("LED"):
                            if led_dur > 0:
                                _deterrent_state["channel_until"]["LIGHT"] = now + (led_dur / 1000.0)
                                _deterrent_state["channel_duration_ms"]["LIGHT"] = led_dur
                        elif token_upper.startswith("SOUND") or token_upper.startswith("BUZZER"):
                            if buz_dur > 0:
                                _deterrent_state["channel_until"]["SOUND"] = now + (buz_dur / 1000.0)
                                _deterrent_state["channel_duration_ms"]["SOUND"] = buz_dur
                        else:
                            for ch in actuators:
                                ch_dur = esp_dur
                                if ch == "WATER" and pump_dur > 0:
                                    ch_dur = pump_dur
                                elif ch == "LIGHT" and led_dur > 0:
                                    ch_dur = led_dur
                                if ch_dur > 0:
                                    _deterrent_state["channel_until"][ch] = now + (ch_dur / 1000.0)
                                    _deterrent_state["channel_duration_ms"][ch] = ch_dur
                print(
                    f"[ESP32 HTTP] >>> Triggered '{animal_token}' "
                    f"(total={esp_dur}ms, pump={pump_dur}ms, led={led_dur}ms, fw={fw}) "
                    f"at {host} (HTTP {resp.status}) <<<",
                    flush=True,
                )
                if token_upper.startswith("LARGE") and pump_dur > 0 and pump_dur != esp_dur:
                    print(
                        f"[ESP32 WARN] Pump duration mismatch ({pump_dur}ms != {esp_dur}ms, fw={fw}) "
                        f"— reflash ESP32 with latest v2.4-safe firmware!",
                        flush=True,
                    )
                return
        except Exception:
            pass

    with _state_lock:
        _deterrent_state["esp32_online"] = False
    print(
        f"[ESP32 INFO] Node 192.168.4.1 unreachable (Simulated telemetry active on dashboard).",
        flush=True,
    )


def _esp32_command_worker():
    while True:
        seq, animal_token, duration_ms, actuators = _esp32_cmd_queue.get()
        try:
            with _state_lock:
                latest_seq = _deterrent_state["cmd_seq"]
            token_upper = str(animal_token).upper().strip()
            # If STOP is newer, skip obsolete pre-STOP trigger commands so SAFE always wins
            if seq < latest_seq and token_upper not in ("STOP", "OFF", "SAFE", "HUMAN"):
                continue
            _esp32_send_http(seq, animal_token, duration_ms, actuators)
        except Exception as exc:
            print(f"[ESP32 CMD WORKER] Error: {exc}", flush=True)
        finally:
            _esp32_cmd_queue.task_done()


_esp32_cmd_thread = threading.Thread(target=_esp32_command_worker, daemon=True)
_esp32_cmd_thread.start()


def dispatch_esp32_command(animal_token, duration_ms=0, actuators=None):
    """
    Queues a serialized low-latency HTTP command to the ESP32 SoftAP (192.168.4.1)
    and updates per-channel local real-time actuator telemetry for the dashboard.
    """
    if actuators is None:
        actuators = []

    token_upper = str(animal_token).upper().strip()
    is_stop = token_upper in ("STOP", "OFF", "SAFE", "HUMAN")
    is_single_test = (
        token_upper.startswith("WATER")
        or token_upper.startswith("PUMP")
        or token_upper.startswith("LIGHT")
        or token_upper.startswith("LED")
        or token_upper.startswith("SOUND")
        or token_upper.startswith("BUZZER")
    )

    now = time.time()
    dur_val = max(0, int(duration_ms))

    with _state_lock:
        _deterrent_state["cmd_seq"] += 1
        seq = _deterrent_state["cmd_seq"]
        if is_stop:
            _deterrent_state["last_target"] = "STOP"
            for ch in ("SOUND", "WATER", "LIGHT"):
                _deterrent_state["channel_until"][ch] = 0.0
                _deterrent_state["channel_duration_ms"][ch] = 0
        elif is_single_test:
            _deterrent_state["last_target"] = animal_token
            until = now + (dur_val / 1000.0) if dur_val > 0 else 0.0
            for ch in actuators:
                if ch in _deterrent_state["channel_until"]:
                    _deterrent_state["channel_until"][ch] = until
                    _deterrent_state["channel_duration_ms"][ch] = dur_val
        else:
            _deterrent_state["last_target"] = animal_token
            until = now + (dur_val / 1000.0) if dur_val > 0 else 0.0
            for ch in ("SOUND", "WATER", "LIGHT"):
                if ch in actuators:
                    _deterrent_state["channel_until"][ch] = until
                    _deterrent_state["channel_duration_ms"][ch] = dur_val
                else:
                    _deterrent_state["channel_until"][ch] = 0.0
                    _deterrent_state["channel_duration_ms"][ch] = 0

    if is_stop:
        # Drain pending non-stop triggers in queue so STOP executes immediately
        drained = []
        while True:
            try:
                queued_item = _esp32_cmd_queue.get_nowait()
                _esp32_cmd_queue.task_done()
                if str(queued_item[1]).upper().strip() in ("STOP", "OFF", "SAFE", "HUMAN"):
                    drained.append(queued_item)
            except queue.Empty:
                break
        for d_item in drained:
            _esp32_cmd_queue.put(d_item)

    _esp32_cmd_queue.put((seq, str(animal_token), dur_val, list(actuators)))


THREAT_TOKEN_RANK = {"BIRD": 1, "SMALL": 2, "LARGE": 3}

_live_temporal_lock = threading.Lock()
_live_temporal_state = {
    "prev_detections": [],
    "prev_time": 0.0,
}


def sync_deterrents_with_plan(plan, force_trigger: bool = False):
    """
    Enforces strict real-time hardware deterrent rules for both Live Camera and Video:
      1. If a Human ('SAFE') is on screen -> STOP deterrents immediately.
      2. If NO 'SAFE' is detected on screen and an Animal ('BIRD', 'SMALL MAMMAL', 'LARGE MAMMAL')
         is detected -> TURN ON deterrents immediately (or escalate immediately if a higher
         threat tier appears, or always fire when force_trigger=True on explicit photo uploads).
    Returns True if a deterrent trigger command was dispatched, False otherwise.
    """
    now = time.time()
    primary_target = plan.get("primary_target", "None")
    esp32_token = plan.get("esp32_token")

    # 1. HUMAN ON SCREEN -> STOP DETERRENTS IMMEDIATELY
    if primary_target == "SAFE":
        should_stop = False
        with _state_lock:
            active_channels, _, active_rem_ms, _ = _recompute_active_channels_locked(now)
            if (
                active_rem_ms > 0
                or len(active_channels) > 0
                or _deterrent_state.get("last_target") not in ("NONE", "STOP", "OFF", "SAFE")
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
            active_channels, _, active_rem_ms, _ = _recompute_active_channels_locked(now)
            active_rem = active_rem_ms / 1000.0
            cur_target = _deterrent_state.get("last_target", "NONE")
            cur_rank = THREAT_TOKEN_RANK.get(cur_target, 0) if active_rem > 0.35 else 0
            new_rank = THREAT_TOKEN_RANK.get(esp32_token, 1)

            if force_trigger or active_rem <= 0.35 or not active_channels or new_rank > cur_rank:
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
        out_w = max(2, int(round(width * scale / 2.0) * 2))
        out_h = max(2, int(round(height * scale / 2.0) * 2))
    else:
        out_w = max(2, width - (width % 2))
        out_h = max(2, height - (height % 2))

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

    thumb_filename = _save_image_thumbnail(peak_frame_bgr, unique_stem) if peak_frame_bgr is not None else None

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
        "timeline": timeline_markers[:1800],
        "sample_detections": all_detections_summary[:30],
    }


# ==============================================================================
# REST API ENDPOINTS FOR REACT + TYPESCRIPT DASHBOARD
# ==============================================================================

@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    target_filter = request.args.get("target", "ALL").upper()
    media_filter = request.args.get("media_type", "ALL").lower()
    page = _safe_int(request.args.get("page", 1), 1, min_v=1, max_v=100000)
    per_page = _safe_int(request.args.get("per_page", 24), 24, min_v=6, max_v=100)

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

    pagination = query.order_by(DeterrentEvent.timestamp.desc(), DeterrentEvent.id.desc()).paginate(
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

    protected_uploads: set[str] = set()
    with _qr_jobs_lock:
        active_ids = []
        for jid in _qr_job_order:
            job = _qr_jobs.get(jid)
            if not job:
                continue
            if job.get("status") in ("queued", "processing"):
                active_ids.append(jid)
                p = job.get("saved_upload_path")
                if p:
                    protected_uploads.add(os.path.abspath(p))
            else:
                _qr_jobs.pop(jid, None)
        _qr_job_order[:] = active_ids

    for folder in [
        app.config["RESULTS_FOLDER"],
        app.config["UPLOAD_FOLDER"],
        app.config["THUMBNAILS_FOLDER"],
    ]:
        for f in glob.glob(os.path.join(folder, "*")):
            if os.path.abspath(f) in protected_uploads:
                continue
            _safe_remove_file(f)
    return jsonify({"status": "cleared"})


ALLOWED_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp",
    ".jfif", ".gif", ".tiff", ".tif", ".heic", ".heif",
}
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".3gp"}
MIMETYPE_EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/tiff": ".tiff",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/x-m4v": ".m4v",
    "video/3gpp": ".3gp",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
}

MAX_ZIP_IMAGES = 100
MAX_ZIP_ENTRY_BYTES = 25 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 250 * 1024 * 1024


def _resolve_upload_ext(file_storage, allowed_exts: set[str]) -> str:
    raw_name = (getattr(file_storage, "filename", "") or "").strip()
    ext = os.path.splitext(raw_name)[1].lower()
    if ext in allowed_exts:
        return ext
    mime = (getattr(file_storage, "mimetype", "") or "").split(";")[0].strip().lower()
    mapped_ext = MIMETYPE_EXT_MAP.get(mime, "")
    if mapped_ext in allowed_exts:
        return mapped_ext
    if mime.startswith("image/") and ".jpg" in allowed_exts:
        return ".jpg"
    if mime.startswith("video/") and ".mp4" in allowed_exts:
        return ".mp4"
    return ext


def _iter_safe_zip_image_bytes(zip_path: str):
    total_uncompressed = 0
    processed_count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = sorted(zf.infolist(), key=lambda inf: inf.filename)
        for info in infos:
            name = info.filename
            if info.is_dir() or name.endswith("/"):
                continue
            base = os.path.basename(name)
            norm_parts = name.replace("\\", "/").split("/")
            if "__MACOSX" in norm_parts or base.startswith("._"):
                continue
            ext = os.path.splitext(base)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTS:
                continue
            if info.file_size <= 0 or info.file_size > MAX_ZIP_ENTRY_BYTES:
                continue
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_ZIP_TOTAL_BYTES:
                break
            if processed_count >= MAX_ZIP_IMAGES:
                break
            raw_bytes = zf.read(info)
            if not raw_bytes:
                continue
            arr = np.frombuffer(raw_bytes, np.uint8)
            img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img_bgr is None and Image is not None:
                try:
                    import io
                    with Image.open(io.BytesIO(raw_bytes)) as pil_img:
                        img_bgr = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
                except Exception:
                    img_bgr = None
            if img_bgr is None:
                continue
            processed_count += 1
            yield base, raw_bytes, img_bgr


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file or (not file.filename and not getattr(file, "mimetype", "")):
        return jsonify({"error": "Empty filename"}), 400

    source_mode = request.form.get("source_mode", "upload")  # upload | live_snapshot
    conf_thresh = _safe_float(request.form.get("conf", 0.50), 0.50, min_v=0.50, max_v=0.99)

    image_exts = ALLOWED_IMAGE_EXTS
    video_exts = ALLOWED_VIDEO_EXTS
    allowed_exts = image_exts | video_exts | {".zip"}
    ext = _resolve_upload_ext(file, allowed_exts)

    if ext not in allowed_exts:
        return jsonify({"error": f"Unsupported file format '{ext}'. Upload an image, video, or .zip image archive."}), 400

    if ext == ".zip":
        zip_path = os.path.join(app.config["UPLOAD_FOLDER"], f"batch_{uuid.uuid4().hex[:8]}.zip")
        try:
            file.save(zip_path)
        except Exception as exc:
            _safe_remove_file(zip_path)
            return jsonify({"error": f"Failed to save ZIP archive: {exc}"}), 400
        created_events = []
        try:
            for base_name, raw_bytes, img_bgr in _iter_safe_zip_image_bytes(zip_path):
                item_stem = f"scan_{uuid.uuid4().hex[:8]}"
                h_img, w_img = img_bgr.shape[:2]
                detections = run_dual_model_cascade(img_bgr, conf_thresh=conf_thresh)
                annotated_bgr = draw_tactical_boxes(img_bgr, detections)
                plan = evaluate_deterrent_plan(detections)
                res_fname = f"{item_stem}.jpg"
                cv2.imwrite(
                    os.path.join(app.config["RESULTS_FOLDER"], res_fname),
                    annotated_bgr,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 93],
                )
                thumb_fname = _save_image_thumbnail(annotated_bgr, item_stem)
                ev = DeterrentEvent(
                    filename=res_fname,
                    thumbnail_filename=thumb_fname,
                    media_type="image",
                    primary_target=plan["primary_target"],
                    action_taken=plan["action_taken"],
                    actuators_json=json.dumps(plan["actuators"]),
                    sound_duration_ms=plan["sound_duration_ms"],
                    confidence=plan["max_confidence"],
                    resolution=f"{w_img} x {h_img} px",
                    file_size_kb=len(raw_bytes) / 1024.0,
                    video_duration_sec=0.0,
                    detections_json=json.dumps(detections),
                    timeline_json="[]",
                )
                db.session.add(ev)
                db.session.flush()
                ev_dict = ev.to_dict()
                ev_dict["source_name"] = base_name
                created_events.append(ev_dict)
            if created_events:
                db.session.commit()
        except zipfile.BadZipFile:
            return jsonify({"error": "Corrupt or invalid ZIP archive."}), 400
        finally:
            _safe_remove_file(zip_path)

        if not created_events:
            return jsonify({"error": "No valid images could be decoded from the ZIP archive."}), 400
        return jsonify({
            "status": "success",
            "batch": True,
            "count": len(created_events),
            "events": created_events,
            "event": created_events[-1],
            "telemetry": get_active_deterrent_telemetry(),
        })

    unique_stem = f"scan_{uuid.uuid4().hex[:8]}"
    raw_filename = f"{unique_stem}{ext}"
    upload_path = os.path.join(app.config["UPLOAD_FOLDER"], raw_filename)
    try:
        file.save(upload_path)
        file_size_kb = os.path.getsize(upload_path) / 1024.0
    except Exception as exc:
        _safe_remove_file(upload_path)
        return jsonify({"error": f"Upload save failed: {exc}"}), 400

    try:
        if ext in image_exts:
            img_bgr = _decode_image_bgr(upload_path)
            if img_bgr is None:
                return jsonify({"error": f"Failed to decode uploaded image ({ext}). Please use JPG, PNG, or WEBP."}), 400

            h_img, w_img = img_bgr.shape[:2]
            resolution = f"{w_img} x {h_img} px"

            detections = run_dual_model_cascade(img_bgr, conf_thresh=conf_thresh)
            annotated_bgr = draw_tactical_boxes(img_bgr, detections)
            plan = evaluate_deterrent_plan(detections)

            result_filename = f"{unique_stem}.jpg"
            result_path = os.path.join(app.config["RESULTS_FOLDER"], result_filename)
            cv2.imwrite(result_path, annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
            thumb_filename = _save_image_thumbnail(annotated_bgr, unique_stem)

            sync_deterrents_with_plan(plan, force_trigger=True)

            ev = DeterrentEvent(
                filename=result_filename,
                thumbnail_filename=thumb_filename,
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
    finally:
        _safe_remove_file(upload_path)


# ==============================================================================
# 100% OFFLINE QR CODE GENERATOR & MULTI-UPLOAD FIFO SCAN QUEUE
# ==============================================================================

_QR_EXP = [0] * 512
_QR_LOG = [0] * 256
_qr_x = 1
for _i in range(255):
    _QR_EXP[_i] = _qr_x
    _QR_LOG[_qr_x] = _i
    _qr_x <<= 1
    if _qr_x & 0x100:
        _qr_x ^= 0x11D
for _i in range(255, 512):
    _QR_EXP[_i] = _QR_EXP[_i - 255]

_QR_VER_L = {
    1: (19, 7, 1, []),
    2: (34, 10, 1, [6, 18]),
    3: (55, 15, 1, [6, 22]),
    4: (80, 20, 1, [6, 26]),
    5: (108, 26, 1, [6, 30]),
    6: (136, 18, 2, [6, 34]),
    7: (156, 20, 2, [6, 22, 38]),
    8: (194, 24, 2, [6, 24, 42]),
}
_QR_FORMAT_BITS_L = [0x77C4, 0x72F3, 0x7DAA, 0x789D, 0x662F, 0x6318, 0x6C41, 0x6976]
_QR_VERSION_BITS = {7: 0x07C94, 8: 0x085BC}


def _qr_rs_encode(data, nsym):
    gen = [1]
    for i in range(nsym):
        nxt = [0] * (len(gen) + 1)
        for j, g in enumerate(gen):
            nxt[j] ^= g
            nxt[j + 1] ^= _QR_EXP[_QR_LOG[g] + i] if g else 0
        gen = nxt
    res = list(data) + [0] * nsym
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            lcoef = _QR_LOG[coef]
            for j in range(1, len(gen)):
                if gen[j]:
                    res[i + j] ^= _QR_EXP[lcoef + _QR_LOG[gen[j]]]
    return res[len(data):]


def _make_qr_matrix(text: str):
    raw = text.encode("utf-8")[:190]
    ver = next((v for v, (dc, _, _, _) in _QR_VER_L.items() if len(raw) + 2 <= dc), 8)
    dc, ec_per_blk, nblk, align = _QR_VER_L[ver]
    bits = [0, 1, 0, 0]
    for i in range(7, -1, -1):
        bits.append((len(raw) >> i) & 1)
    for b in raw:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    for _ in range(min(4, dc * 8 - len(bits))):
        bits.append(0)
    while len(bits) % 8 != 0:
        bits.append(0)
    codewords = [sum(bits[i + j] << (7 - j) for j in range(8)) for i in range(0, len(bits), 8)]
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(codewords) < dc:
        codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    blk_size = dc // nblk
    data_blks, ec_blks = [], []
    for b in range(nblk):
        blk = codewords[b * blk_size:(b + 1) * blk_size]
        data_blks.append(blk)
        ec_blks.append(_qr_rs_encode(blk, ec_per_blk))
    final_cw = (
        [data_blks[b][i] for i in range(blk_size) for b in range(nblk)]
        + [ec_blks[b][i] for i in range(ec_per_blk) for b in range(nblk)]
    )
    final_bits = [(cw >> i) & 1 for cw in final_cw for i in range(7, -1, -1)]

    size = 17 + 4 * ver
    mat = [[0] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_func(r, c, val):
        if 0 <= r < size and 0 <= c < size:
            mat[r][c] = 1 if val else 0
            is_func[r][c] = True

    def place_finder(top, left):
        for dr in range(-1, 8):
            for dc_ in range(-1, 8):
                val = (
                    0 <= dr <= 6
                    and 0 <= dc_ <= 6
                    and (dr in (0, 6) or dc_ in (0, 6) or (2 <= dr <= 4 and 2 <= dc_ <= 4))
                )
                set_func(top + dr, left + dc_, val)

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)

    for i in range(8, size - 8):
        set_func(6, i, i % 2 == 0)
        set_func(i, 6, i % 2 == 0)

    for ar in align:
        for ac in align:
            if (ar == 6 and ac == 6) or (ar == 6 and ac == size - 7) or (ar == size - 7 and ac == 6):
                continue
            for dr in range(-2, 3):
                for dc_ in range(-2, 3):
                    set_func(ar + dr, ac + dc_, max(abs(dr), abs(dc_)) != 1)

    for i in range(9):
        if i != 6:
            set_func(8, i, False)
            set_func(i, 8, False)
    for i in range(8):
        set_func(8, size - 1 - i, False)
        set_func(size - 1 - i, 8, False)
    set_func(size - 8, 8, True)

    if ver in _QR_VERSION_BITS:
        vb = _QR_VERSION_BITS[ver]
        for i in range(18):
            bit = ((vb >> i) & 1) == 1
            set_func(size - 11 + (i % 3), i // 3, bit)
            set_func(i // 3, size - 11 + (i % 3), bit)

    bit_idx = 0
    up = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if up else range(size)
        for r in rows:
            for c in (col, col - 1):
                if not is_func[r][c]:
                    if bit_idx < len(final_bits):
                        mat[r][c] = final_bits[bit_idx]
                        bit_idx += 1
        up = not up
        col -= 2

    for r in range(size):
        for c in range(size):
            if not is_func[r][c] and (r + c) % 2 == 0:
                mat[r][c] ^= 1

    fb = _QR_FORMAT_BITS_L[0]
    f_coords1 = [
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
        (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    ]
    for i, (r, c) in enumerate(f_coords1):
        mat[r][c] = (fb >> (14 - i)) & 1
    for i in range(7):
        mat[size - 1 - i][8] = (fb >> (14 - i)) & 1
    for i in range(8):
        mat[8][size - 8 + i] = (fb >> (7 - i)) & 1

    return mat


def generate_qr_svg(text: str, quiet: int = 4) -> str:
    mat = _make_qr_matrix(text)
    n = len(mat)
    total = n + quiet * 2
    rects = []
    for r in range(n):
        for c in range(n):
            if mat[r][c]:
                rects.append(f'<rect x="{c + quiet}" y="{r + quiet}" width="1" height="1"/>')
    body = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'shape-rendering="crispEdges" width="320" height="320">'
        f'<rect width="{total}" height="{total}" fill="#ffffff" rx="1.5"/>'
        f'<g fill="#080c14">{body}</g></svg>'
    )


_qr_upload_queue: "queue.Queue[str]" = queue.Queue()
_qr_jobs_lock = threading.Lock()
_qr_jobs: dict[str, dict] = {}
_qr_job_order: list[str] = []


MAX_QR_HISTORY = 120


def _escape_wifi_qr_field(val: str) -> str:
    out = []
    for ch in str(val):
        if ch in ("\\", ";", ",", '"', ":"):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _prune_qr_history_locked():
    while len(_qr_job_order) > MAX_QR_HISTORY:
        evict_idx = None
        for idx, jid in enumerate(_qr_job_order):
            st = _qr_jobs.get(jid, {}).get("status")
            if st in ("completed", "failed"):
                evict_idx = idx
                break
        if evict_idx is None:
            break
        evict_id = _qr_job_order.pop(evict_idx)
        _qr_jobs.pop(evict_id, None)


def _process_single_queued_job(job_id: str):
    with _qr_jobs_lock:
        job = _qr_jobs.get(job_id)
        if not job:
            return
        job["status"] = "processing"
        job["started_at"] = datetime.now().strftime("%H:%M:%S")
        upload_path = job["saved_upload_path"]
        ext = job["ext"]
        conf_thresh = job["conf_thresh"]
        unique_stem = job["unique_stem"]
        file_size_kb = job["file_size_kb"]

    image_exts = ALLOWED_IMAGE_EXTS
    video_exts = ALLOWED_VIDEO_EXTS

    try:
        with app.app_context():
            if ext in image_exts:
                img_bgr = _decode_image_bgr(upload_path)
                if img_bgr is None:
                    raise RuntimeError(f"Failed to decode uploaded image ({ext}).")
                h_img, w_img = img_bgr.shape[:2]
                resolution = f"{w_img} x {h_img} px"
                detections = run_dual_model_cascade(img_bgr, conf_thresh=conf_thresh)
                annotated_bgr = draw_tactical_boxes(img_bgr, detections)
                plan = evaluate_deterrent_plan(detections)

                result_filename = f"{unique_stem}.jpg"
                result_path = os.path.join(app.config["RESULTS_FOLDER"], result_filename)
                cv2.imwrite(result_path, annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
                thumb_filename = _save_image_thumbnail(annotated_bgr, unique_stem)

                sync_deterrents_with_plan(plan, force_trigger=True)

                ev = DeterrentEvent(
                    filename=result_filename,
                    thumbnail_filename=thumb_filename,
                    media_type="image",
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
                ev_dict = ev.to_dict()

                with _qr_jobs_lock:
                    job["status"] = "completed"
                    job["completed_at"] = datetime.now().strftime("%H:%M:%S")
                    job["event"] = ev_dict
                    job["batch_count"] = 1

            elif ext in video_exts:
                vid_info = process_uploaded_video(upload_path, unique_stem, conf_thresh=conf_thresh)
                plan = vid_info["plan"]
                sync_deterrents_with_plan(plan, force_trigger=True)

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
                ev_dict = ev.to_dict()

                with _qr_jobs_lock:
                    job["status"] = "completed"
                    job["completed_at"] = datetime.now().strftime("%H:%M:%S")
                    job["event"] = ev_dict
                    job["batch_count"] = 1

            elif ext == ".zip":
                created_events = []
                for base_name, raw_bytes, img_bgr in _iter_safe_zip_image_bytes(upload_path):
                    item_stem = f"scan_{uuid.uuid4().hex[:8]}"
                    h_img, w_img = img_bgr.shape[:2]
                    detections = run_dual_model_cascade(img_bgr, conf_thresh=conf_thresh)
                    annotated_bgr = draw_tactical_boxes(img_bgr, detections)
                    plan = evaluate_deterrent_plan(detections)
                    res_fname = f"{item_stem}.jpg"
                    cv2.imwrite(
                        os.path.join(app.config["RESULTS_FOLDER"], res_fname),
                        annotated_bgr,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 93],
                    )
                    thumb_fname = _save_image_thumbnail(annotated_bgr, item_stem)
                    ev = DeterrentEvent(
                        filename=res_fname,
                        thumbnail_filename=thumb_fname,
                        media_type="image",
                        primary_target=plan["primary_target"],
                        action_taken=plan["action_taken"],
                        actuators_json=json.dumps(plan["actuators"]),
                        sound_duration_ms=plan["sound_duration_ms"],
                        confidence=plan["max_confidence"],
                        resolution=f"{w_img} x {h_img} px",
                        file_size_kb=len(raw_bytes) / 1024.0,
                        video_duration_sec=0.0,
                        detections_json=json.dumps(detections),
                        timeline_json="[]",
                    )
                    db.session.add(ev)
                    db.session.flush()
                    ev_dict = ev.to_dict()
                    ev_dict["source_name"] = base_name
                    created_events.append(ev_dict)
                if created_events:
                    db.session.commit()

                if not created_events:
                    raise RuntimeError("No valid images could be decoded from ZIP.")
                with _qr_jobs_lock:
                    job["status"] = "completed"
                    job["completed_at"] = datetime.now().strftime("%H:%M:%S")
                    job["event"] = created_events[-1]
                    job["batch_count"] = len(created_events)
    except Exception as err:
        with _qr_jobs_lock:
            job["status"] = "failed"
            job["completed_at"] = datetime.now().strftime("%H:%M:%S")
            job["error"] = str(err)
    finally:
        _safe_remove_file(upload_path)


def _qr_queue_worker():
    while True:
        job_id = _qr_upload_queue.get()
        try:
            _process_single_queued_job(job_id)
        except Exception as e:
            print(f"[QR-QUEUE] Worker error on {job_id}: {e}")
        finally:
            _qr_upload_queue.task_done()


_qr_worker_thread = threading.Thread(target=_qr_queue_worker, daemon=True)
_qr_worker_thread.start()


ESP32_AP_SSID = os.environ.get("ESP32_AP_SSID", "Wildlife-Deterrent-System-AP")
ESP32_AP_PASS = os.environ.get("ESP32_AP_PASS", "haustein26")


def get_qr_queue_snapshot() -> dict:
    lan_ips = _get_local_ipv4_addresses()
    on_esp32_ap = any(ip.startswith("192.168.4.") for ip in lan_ips)
    if not lan_ips:
        lan_ips = ["192.168.4.2"]
    elif not on_esp32_ap and "192.168.4.2" not in lan_ips:
        lan_ips.append("192.168.4.2")
    urls = [f"http://{ip}:5002/qr-upload" for ip in lan_ips]
    primary_url = urls[0]
    esc_ssid = _escape_wifi_qr_field(ESP32_AP_SSID)
    esc_pass = _escape_wifi_qr_field(ESP32_AP_PASS)
    wifi_qr_payload = f"WIFI:T:WPA;S:{esc_ssid};P:{esc_pass};H:false;;"

    with _qr_jobs_lock:
        queued_ids = [jid for jid in _qr_job_order if _qr_jobs.get(jid, {}).get("status") == "queued"]
        pos_map = {jid: idx + 1 for idx, jid in enumerate(queued_ids)}

        queued_count = len(queued_ids)
        processing_count = sum(1 for jid in _qr_job_order if _qr_jobs.get(jid, {}).get("status") == "processing")
        completed_count = sum(1 for jid in _qr_job_order if _qr_jobs.get(jid, {}).get("status") == "completed")
        failed_count = sum(1 for jid in _qr_job_order if _qr_jobs.get(jid, {}).get("status") == "failed")

        recent_ids = list(reversed(_qr_job_order[-40:]))
        jobs_list = []
        for jid in recent_ids:
            j = _qr_jobs.get(jid)
            if not j:
                continue
            jobs_list.append({
                "job_id": j["job_id"],
                "original_name": j["original_name"],
                "media_type": j["media_type"],
                "file_size_kb": j["file_size_kb"],
                "uploader": j["uploader"],
                "status": j["status"],
                "position": pos_map.get(jid, 0),
                "queued_at": j["queued_at"],
                "started_at": j["started_at"],
                "completed_at": j["completed_at"],
                "event": j["event"],
                "batch_count": j["batch_count"],
                "error": j["error"],
            })

    return {
        "queued_count": queued_count,
        "processing_count": processing_count,
        "active_count": queued_count + processing_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "jobs": jobs_list,
        "network": {
            "ips": lan_ips,
            "on_esp32_ap": on_esp32_ap,
            "port": 5002,
            "primary_url": primary_url,
            "urls": urls,
            "wifi_ssid": ESP32_AP_SSID,
            "wifi_password": ESP32_AP_PASS,
            "wifi_qr_payload": wifi_qr_payload,
        },
    }


@app.route("/api/qr/svg", methods=["GET"])
def api_qr_svg():
    qr_type = request.args.get("type", "").strip().lower()
    if qr_type == "wifi":
        ssid = _escape_wifi_qr_field(request.args.get("ssid", ESP32_AP_SSID).strip() or ESP32_AP_SSID)
        password = _escape_wifi_qr_field(request.args.get("password", ESP32_AP_PASS).strip())
        payload = f"WIFI:T:WPA;S:{ssid};P:{password};H:false;;"
    else:
        payload = request.args.get("url", "").strip()
        if not payload:
            snap = get_qr_queue_snapshot()
            payload = snap["network"]["primary_url"]
    svg_str = generate_qr_svg(payload)
    resp = Response(svg_str, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/qr/queue", methods=["GET"])
def api_qr_queue_status():
    resp = jsonify(get_qr_queue_snapshot())
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/qr/queue/clear", methods=["POST"])
def api_qr_queue_clear():
    with _qr_jobs_lock:
        active_ids = [
            jid for jid in _qr_job_order
            if _qr_jobs.get(jid, {}).get("status") in ("queued", "processing")
        ]
        _qr_job_order[:] = active_ids
        for jid in list(_qr_jobs.keys()):
            if jid not in active_ids:
                _qr_jobs.pop(jid, None)
    return jsonify(get_qr_queue_snapshot())


@app.route("/api/qr/enqueue", methods=["POST"])
def api_qr_enqueue():
    try:
        uploaded_files = request.files.getlist("files")
        if not uploaded_files and "file" in request.files:
            uploaded_files = [request.files["file"]]
    except Exception as exc:
        print(f"[QR-QUEUE] Multipart stream interrupted from {request.remote_addr}: {exc}")
        return jsonify({"error": f"Upload interrupted before completion: {exc}"}), 400

    valid_files = [f for f in uploaded_files if f and (f.filename or getattr(f, "mimetype", ""))]
    if not valid_files:
        return jsonify({"error": "No media files provided."}), 400

    conf_thresh = _safe_float(request.form.get("conf", 0.50), 0.50, min_v=0.50, max_v=0.99)
    uploader = (request.form.get("uploader") or "Mobile QR Upload").strip()[:48]

    image_exts = ALLOWED_IMAGE_EXTS
    video_exts = ALLOWED_VIDEO_EXTS
    allowed_exts = image_exts | video_exts | {".zip"}

    enqueued_jobs = []
    for f in valid_files:
        raw_name = (f.filename or "").strip()
        ext = _resolve_upload_ext(f, allowed_exts)
        if ext not in allowed_exts:
            continue

        display_name = os.path.basename(raw_name) if raw_name else f"mobile_upload{ext}"
        unique_stem = f"scan_{uuid.uuid4().hex[:8]}"
        raw_filename = f"{unique_stem}{ext}"
        upload_path = os.path.join(app.config["UPLOAD_FOLDER"], raw_filename)
        try:
            f.save(upload_path)
            file_size_kb = os.path.getsize(upload_path) / 1024.0
        except Exception as exc:
            print(f"[QR-QUEUE] Save error for '{display_name}' from {request.remote_addr}: {exc}")
            try:
                if os.path.exists(upload_path):
                    os.remove(upload_path)
            except Exception:
                pass
            return jsonify({"error": f"Upload save failed for '{display_name}': {exc}"}), 400

        job_id = f"q_{uuid.uuid4().hex[:8]}"
        media_type = "video" if ext in video_exts else ("zip" if ext == ".zip" else "image")

        job_entry = {
            "job_id": job_id,
            "unique_stem": unique_stem,
            "original_name": display_name,
            "saved_upload_path": upload_path,
            "ext": ext,
            "media_type": media_type,
            "file_size_kb": round(file_size_kb, 1),
            "conf_thresh": conf_thresh,
            "uploader": uploader,
            "status": "queued",
            "queued_at": datetime.now().strftime("%H:%M:%S"),
            "started_at": None,
            "completed_at": None,
            "event": None,
            "batch_count": 0,
            "error": None,
        }
        with _qr_jobs_lock:
            _qr_jobs[job_id] = job_entry
            _qr_job_order.append(job_id)
            _prune_qr_history_locked()
        _qr_upload_queue.put(job_id)
        enqueued_jobs.append({
            "job_id": job_id,
            "original_name": job_entry["original_name"],
            "media_type": media_type,
            "status": "queued",
        })

    if not enqueued_jobs:
        return jsonify({"error": "No supported image, video, or .zip files found in upload."}), 400

    return jsonify({
        "status": "queued",
        "enqueued_count": len(enqueued_jobs),
        "enqueued": enqueued_jobs,
        "queue": get_qr_queue_snapshot(),
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
    auto_save = request.form.get("auto_save", "false").lower() == "true"
    auto_trigger = request.form.get("auto_trigger", "true").lower() == "true"
    conf_thresh = _safe_float(request.form.get("conf", 0.50), 0.50, min_v=0.50, max_v=0.99)
    use_csi = request.form.get("use_csi", "false").lower() == "true"

    if "frame" in request.files:
        file = request.files["frame"]
        file_bytes = np.frombuffer(file.read(), np.uint8)
        img_bgr = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
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
            with _live_temporal_lock:
                _live_temporal_state["prev_detections"] = raw_detections
                _live_temporal_state["prev_time"] = time.time()

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
    should_save_snapshot = save_snapshot and (
        not auto_save or plan["primary_target"] in ("BIRD", "SMALL MAMMAL", "LARGE MAMMAL")
    )
    if should_save_snapshot:
        unique_stem = f"live_{uuid.uuid4().hex[:8]}"
        result_filename = f"{unique_stem}.jpg"
        result_path = os.path.join(app.config["RESULTS_FOLDER"], result_filename)
        annotated_bgr = draw_tactical_boxes(img_bgr, detections)
        cv2.imwrite(result_path, annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
        thumb_filename = _save_image_thumbnail(annotated_bgr, unique_stem)
        file_size_kb = os.path.getsize(result_path) / 1024.0

        # Respect auto_trigger checkbox even during manual snapshots
        if auto_trigger and plan["esp32_token"] and not triggered_now:
            triggered_now = sync_deterrents_with_plan(plan)

        ev = DeterrentEvent(
            filename=result_filename,
            thumbnail_filename=thumb_filename,
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
      - actuator = 'SOUND' (with pattern = 'BIRD' | 'SMALL' | 'LARGE' and randomized or custom duration)
      - actuator = 'WATER' (sends 'WATER_TEST' to ESP32 + updates WATER telemetry only)
      - actuator = 'LIGHT' (sends 'LIGHT_TEST' to ESP32 + updates LIGHT telemetry only)
    """
    data = request.get_json(silent=True) or {}
    actuator = str(data.get("actuator", "SOUND")).upper().strip()
    pattern = str(data.get("pattern", "")).upper().strip()
    raw_dur = data.get("duration_ms")
    parsed_dur = _safe_int(raw_dur, 0) if raw_dur is not None else 0
    custom_dur_ms = max(500, min(30000, parsed_dur)) if parsed_dur > 0 else 0

    if actuator == "SOUND":
        if "BIRD" in pattern:
            token = "BIRD"
            dur_ms = custom_dur_ms if custom_dur_ms > 0 else random.randint(3000, 6000)
        elif "SMALL" in pattern:
            token = "SMALL"
            dur_ms = custom_dur_ms if custom_dur_ms > 0 else random.randint(5000, 9000)
        else:
            token = "LARGE"
            dur_ms = custom_dur_ms if custom_dur_ms > 0 else random.randint(8000, 14000)
        dispatch_esp32_command(f"SOUND_TEST_{token}", duration_ms=dur_ms, actuators=["SOUND"])
        return jsonify({
            "status": "triggered",
            "actuator": "SOUND",
            "pattern": token,
            "duration_ms": dur_ms,
            "telemetry": get_active_deterrent_telemetry(),
        })

    elif actuator == "WATER":
        if custom_dur_ms > 0:
            dur_ms = custom_dur_ms
        elif "LARGE" in pattern:
            dur_ms = random.randint(8000, 14000)
        elif "SMALL" in pattern:
            dur_ms = random.randint(5000, 9000)
        else:
            dur_ms = random.randint(2500, 6000)
        dispatch_esp32_command("WATER_TEST", duration_ms=dur_ms, actuators=["WATER"])
        return jsonify({
            "status": "triggered",
            "actuator": "WATER",
            "pattern": "WATER_TEST",
            "duration_ms": dur_ms,
            "telemetry": get_active_deterrent_telemetry(),
        })

    elif actuator == "LIGHT":
        if custom_dur_ms > 0:
            dur_ms = custom_dur_ms
        elif "BIRD" in pattern:
            dur_ms = random.randint(3000, 6000)
        elif "SMALL" in pattern:
            dur_ms = random.randint(5000, 9000)
        elif "LARGE" in pattern:
            dur_ms = random.randint(8000, 14000)
        else:
            dur_ms = random.randint(3500, 7500)
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


def _probe_esp32_node(timeout_sec: float = 0.5):
    host = os.environ.get("ESP32_HOST", "192.168.4.1")
    try:
        req = urllib.request.Request(
            f"http://{host}/status",
            headers={"Connection": "close"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            now = time.time()
            with _state_lock:
                _deterrent_state["esp32_online"] = True
                _deterrent_state["esp32_ip"] = data.get("ip", host)
                if data.get("firmware"):
                    _deterrent_state["esp32_firmware"] = str(data.get("firmware"))
                # Reconcile live remaining durations when reported by ESP32
                buz_active = bool(data.get("buzzer_active", False))
                pmp_active = bool(data.get("pump_active", False))
                led_active = bool(data.get("led_active", False))
                rem_all = _safe_int(data.get("remaining_ms", 0), 0, min_v=0)
                pmp_rem = _safe_int(data.get("pump_remaining_ms", rem_all), 0, min_v=0)
                led_rem = _safe_int(data.get("led_remaining_ms", rem_all), 0, min_v=0)
                buz_rem = _safe_int(data.get("buzzer_remaining_ms", rem_all), 0, min_v=0)
                if buz_active and buz_rem > 0:
                    _deterrent_state["channel_until"]["SOUND"] = now + (buz_rem / 1000.0)
                elif not buz_active and _deterrent_state["channel_until"]["SOUND"] <= now + 0.5:
                    _deterrent_state["channel_until"]["SOUND"] = 0.0
                if pmp_active and pmp_rem > 0:
                    _deterrent_state["channel_until"]["WATER"] = now + (pmp_rem / 1000.0)
                elif not pmp_active and _deterrent_state["channel_until"]["WATER"] <= now + 0.5:
                    _deterrent_state["channel_until"]["WATER"] = 0.0
                if led_active and led_rem > 0:
                    _deterrent_state["channel_until"]["LIGHT"] = now + (led_rem / 1000.0)
                elif not led_active and _deterrent_state["channel_until"]["LIGHT"] <= now + 0.5:
                    _deterrent_state["channel_until"]["LIGHT"] = 0.0
            return True
    except Exception:
        with _state_lock:
            _deterrent_state["esp32_online"] = False
        return False


def _esp32_heartbeat_worker():
    while True:
        try:
            env_host = os.environ.get("ESP32_HOST", "").strip()
            lan_ips = _get_local_ipv4_addresses()
            on_ap = any(ip.startswith("192.168.4.") for ip in lan_ips)
            if env_host or on_ap:
                _probe_esp32_node(timeout_sec=0.5)
            else:
                with _state_lock:
                    _deterrent_state["esp32_online"] = False
        except Exception:
            pass
        time.sleep(4.0)


_heartbeat_thread = threading.Thread(target=_esp32_heartbeat_worker, daemon=True)
_heartbeat_thread.start()


@app.route("/api/health", methods=["GET"])
def api_health():
    resp = jsonify({"status": "ok"})
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/esp32/status", methods=["GET"])
def api_esp32_status():
    probe = request.args.get("probe", "false").lower() == "true"
    if probe:
        _probe_esp32_node(timeout_sec=0.6)

    return jsonify(get_active_deterrent_telemetry())


# ==============================================================================
# CAMERA HARDWARE & STREAMING ENGINE (SINGLE-THREADED HUB + IMX219 CSI + AWB)
# ==============================================================================

class DashboardGrayWorldAWB:
    """Software Auto White Balance for neutralizing IMX219 color cast."""
    def __init__(self, smoothing: float = 0.85):
        self.smoothing = smoothing
        self.running_gain = None
        self._lock = threading.Lock()

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
        with self._lock:
            if self.running_gain is None:
                self.running_gain = gain
            else:
                self.running_gain = (self.smoothing * self.running_gain) + ((1.0 - self.smoothing) * gain)
            g_snapshot = self.running_gain.copy()
        lut_b = np.clip(np.arange(256) * g_snapshot[0], 0, 255).astype(np.uint8)
        lut_g = np.clip(np.arange(256) * g_snapshot[1], 0, 255).astype(np.uint8)
        lut_r = np.clip(np.arange(256) * g_snapshot[2], 0, 255).astype(np.uint8)
        b, g, r = cv2.split(bgr_frame)
        return cv2.merge([cv2.LUT(b, lut_b), cv2.LUT(g, lut_g), cv2.LUT(r, lut_r)])

_global_awb = DashboardGrayWorldAWB()

_camera_state_lock = threading.Lock()
_camera_state = {
    "mirror_h": True,
    "mirror_v": False,
    "rotation": 180,
    "awb": True,
    "sensor_id": _safe_int(os.environ.get("CSI_SENSOR_ID", "0"), 0, min_v=0, max_v=1),
    "flip_method": _safe_int(os.environ.get("CSI_FLIP_METHOD", "0"), 0, min_v=0, max_v=7),
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
        self.last_open_failed_ts = 0.0

    @classmethod
    def get_instance(cls):
        with cls._hub_lock:
            if cls._instance is None:
                cls._instance = JetsonCameraHub()
            return cls._instance

    def _open_camera(self):
        if os.name == "nt":
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            return cap

        with _camera_state_lock:
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
                return True
            if (time.monotonic() - self.last_open_failed_ts) < 3.0:
                return False
            self.running = True
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
            return True

    def _worker(self):
        print("[CAM-HUB] Starting dedicated single-owner capture thread...")
        try:
            self.cap = self._open_camera()
            if not self.cap or not self.cap.isOpened():
                print("[CAM-HUB] Warning: Unable to open camera pipeline.")
                with self.lock:
                    self.last_open_failed_ts = time.monotonic()
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
                        with self.lock:
                            self.last_open_failed_ts = time.monotonic()
                        break
                    continue

                # Process rotation, mirror, AWB
                with _camera_state_lock:
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
                self.latest_frame = None
                self.latest_jpeg = None
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
        if not self.start_if_needed():
            return None
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
    with _camera_state_lock:
        if request.method == "POST":
            data = request.get_json(silent=True) or request.form.to_dict()
            if "mirror_h" in data:
                _camera_state["mirror_h"] = str(data["mirror_h"]).lower() in ("true", "1")
            if "mirror_v" in data:
                _camera_state["mirror_v"] = str(data["mirror_v"]).lower() in ("true", "1")
            if "toggle_mirror" in data:
                _camera_state["mirror_h"] = not _camera_state["mirror_h"]
            if "rotation" in data:
                _camera_state["rotation"] = (_safe_int(data["rotation"], _camera_state["rotation"]) // 90 * 90) % 360
            if "rotate" in data:
                _camera_state["rotation"] = (_camera_state["rotation"] + 90) % 360
            if "flip" in data:
                _camera_state["rotation"] = (_camera_state["rotation"] + 180) % 360
            if "awb" in data:
                _camera_state["awb"] = str(data["awb"]).lower() in ("true", "1")
            if "toggle_awb" in data:
                _camera_state["awb"] = not _camera_state["awb"]
        snapshot = dict(_camera_state)

    return jsonify({"status": "ok", "settings": snapshot})


@app.route("/api/camera/stream")
def api_camera_stream():
    """MJPEG live camera stream from Jetson IMX219 with AWB, orientation, and mirror."""
    hub = JetsonCameraHub.get_instance()
    started = hub.start_if_needed()
    if not started and hub.latest_jpeg is None:
        return jsonify({"error": "No live camera device available"}), 503

    # Wait briefly for first frame before starting multipart stream so unavailable cameras return clean 503
    wait_deadline = time.monotonic() + 3.0
    first_jpeg = hub.get_jpeg()
    while first_jpeg is None and time.monotonic() < wait_deadline and hub.running:
        time.sleep(0.05)
        first_jpeg = hub.get_jpeg()
    if first_jpeg is None:
        return jsonify({"error": "Camera hardware unavailable or stream failed to initialize"}), 503

    def _stream_gen():
        last_frame_bytes = first_jpeg
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(first_jpeg)).encode() + b"\r\n\r\n"
            + first_jpeg + b"\r\n"
        )
        idle_since = time.monotonic()
        while True:
            jpeg_bytes = hub.get_jpeg()
            if jpeg_bytes is not None and jpeg_bytes != last_frame_bytes:
                last_frame_bytes = jpeg_bytes
                idle_since = time.monotonic()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
                    + jpeg_bytes + b"\r\n"
                )
            elif not hub.running and (time.monotonic() - idle_since) > 6.0:
                break
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


@app.route("/qr-upload")
def serve_qr_upload():
    return serve_spa("")


@app.route("/mobile-upload")
def serve_mobile_upload():
    return serve_spa("")


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


@app.errorhandler(404)
def handle_spa_404(err):
    if request.path.startswith("/api/") or request.path.startswith("/results/") or request.path.startswith("/thumbnails/"):
        return jsonify({"error": "Not found"}), 404
    return serve_spa("")


@app.errorhandler(413)
def handle_entity_too_large(err):
    return jsonify({"error": "Upload exceeds maximum allowed size (1024 MB)."}), 413


@app.errorhandler(500)
def handle_internal_error(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error while processing request."}), 500
    return "Internal server error", 500


_ip_cache_lock = threading.Lock()
_ip_cache_ts = 0.0
_ip_cache_ips: list[str] = []


def _is_virtual_or_ignored_ip(ip: str, strict: bool = False) -> bool:
    if not ip:
        return True
    if ip.startswith(("127.", "192.168.55.", "172.17.", "169.254.", "0.")):
        return True
    if strict:
        # Skip common Windows Hyper-V/WSL/VirtualBox/Hotspot adapters in fallback enumeration
        if ip.startswith(("192.168.56.", "192.168.137.")):
            return True
        if ip.startswith("172."):
            parts = ip.split(".")
            if len(parts) >= 2:
                try:
                    second = int(parts[1])
                    if 16 <= second <= 31:
                        return True
                except Exception:
                    pass
    return False


def _get_local_ipv4_addresses() -> list[str]:
    global _ip_cache_ts, _ip_cache_ips
    now = time.monotonic()
    with _ip_cache_lock:
        if _ip_cache_ips and (now - _ip_cache_ts) < 2.5:
            return list(_ip_cache_ips)

    ips: list[str] = []
    ignore_ifaces = ("lo", "docker", "l4tbr", "br-", "veth", "virbr", "tun", "tap")

    def _add_ip(ip: str, front: bool = False, strict_virtual: bool = False):
        if _is_virtual_or_ignored_ip(ip, strict=strict_virtual):
            return
        if ip in ips:
            if front:
                ips.remove(ip)
                ips.insert(0, ip)
            return
        if front:
            ips.insert(0, ip)
        else:
            ips.append(ip)

    if os.name != "nt":
        try:
            import subprocess
            out = subprocess.check_output(
                ["ip", "-4", "-o", "addr", "show", "up", "scope", "global"],
                text=True,
                timeout=1.0,
            )
            wifi_ips: list[str] = []
            other_ips: list[str] = []
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 4:
                    continue
                iface = parts[1]
                if any(iface.startswith(p) for p in ignore_ifaces):
                    continue
                ip = parts[3].split("/")[0]
                if _is_virtual_or_ignored_ip(ip):
                    continue
                if ip.startswith("192.168.4."):
                    _add_ip(ip, front=True)
                elif iface.startswith(("wl", "wlan", "wifi")):
                    wifi_ips.append(ip)
                else:
                    other_ips.append(ip)
            for ip in wifi_ips + other_ips:
                _add_ip(ip, front=False)
        except Exception:
            pass

    import socket
    for probe_target in (("192.168.4.1", 80), ("8.8.8.8", 80)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(probe_target)
            routed_ip = s.getsockname()[0]
            s.close()
            is_esp_subnet = routed_ip.startswith("192.168.4.")
            _add_ip(routed_ip, front=(is_esp_subnet or len(ips) == 0))
        except Exception:
            pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            _add_ip(addr, front=addr.startswith("192.168.4."), strict_virtual=True)
    except Exception:
        pass

    with _ip_cache_lock:
        _ip_cache_ts = time.monotonic()
        _ip_cache_ips = list(ips)
    return list(ips)


def _esp32_subnet_arp_warmer():
    """
    When connected to the ESP32 SoftAP (192.168.4.0/24), proactively probes
    192.168.4.1..192.168.4.6 every 5.0s so mobile phones connected to the
    ESP32 AP immediately cache the host MAC address without saturating the AP.
    """
    import socket
    while True:
        try:
            lan_ips = _get_local_ipv4_addresses()
            ap_ips = [ip for ip in lan_ips if ip.startswith("192.168.4.")]
            if ap_ips:
                my_ip = ap_ips[0]
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setblocking(False)
                for host_id in range(1, 12):
                    peer_ip = f"192.168.4.{host_id}"
                    if peer_ip == my_ip:
                        continue
                    try:
                        s.sendto(b"", (peer_ip, 5002))
                    except Exception:
                        pass
                s.close()
        except Exception:
            pass
        time.sleep(5.0)


_arp_warmer_thread = threading.Thread(target=_esp32_subnet_arp_warmer, daemon=True)
_arp_warmer_thread.start()


if __name__ == "__main__":
    lan_ips = _get_local_ipv4_addresses()
    print("\n" + "=" * 68)
    print("  SENTINEL WILDLIFE DETERRENT SYSTEM — COMMAND DASHBOARD v2.0")
    print("  Primary Host URL : http://127.0.0.1:5002  (Full HUD + Live Camera)")
    if lan_ips:
        for lip in lan_ips:
            print(f"  External PC URL  : http://{lip}:5002  (Remote Upload Mode)")
    else:
        print("  External PC URL  : http://192.168.4.2:5002  (When linked to ESP32 AP)")
    print("  Offline Mode     : ENABLED (Dual-Model YOLOv11m + COCO Cascade)")
    print("=" * 68 + "\n")
    if os.name != "nt":
        JetsonCameraHub.get_instance().start_if_needed()
    app.run(host="0.0.0.0", port=5002, debug=False, threaded=True)
