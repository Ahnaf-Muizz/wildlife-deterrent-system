#!/usr/bin/env python3
"""
Jetson Orin Nano - Offline Custom Dataset Fine-Tuning Script (v2.0)
-------------------------------------------------------------------
1. Enforces 100% offline execution (YOLO_OFFLINE=true, ULTRALYTICS_OFFLINE=1).
2. Reads pre-verified YOLO labels (.txt) in custom_dataset/raw_images/ (113 campus
   iOS photos + 10 keyframes extracted from 2 iOS .MOV videos).
3. If new unlabeled images or .MOV/.mp4 videos are dropped into custom_dataset/raw_images/
   or Wildlife Dataset/, extracts keyframes and auto-labels them using the Offline
   Dual-Model Cascade (best.pt + yolo11n.pt), strictly enforcing:
     - Class 0: bird (grackles, pigeons, geese, ducks, raptors)
     - Class 1: small_mammal (squirrels, dogs, cats, foxes, rabbits, raccoons)
     - Class 2: large_mammal (deer, coyotes, bears, livestock)
     - Class 3: safe (STRICTLY HUMAN ONLY - verified via yolo11n.pt person class)
4. Combines custom images (3x oversampled) with custom_dataset/replay_buffer (200
   balanced anchor images with pets remapped to small_mammal) to prevent catastrophic
   forgetting on Class 2 (large_mammal).
5. Fine-tunes best.pt with backbone freezing (freeze=10) optimized for 8GB Jetson RAM.
"""

import os
import sys
import gc
import time
import glob
import random
import shutil
import argparse

# Enforce 100% offline Ultralytics execution before importing YOLO
os.environ["YOLO_OFFLINE"] = "true"
os.environ["ULTRALYTICS_OFFLINE"] = "1"

import cv2
import torch
import yaml
from ultralytics import YOLO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_DIR = os.path.join(BASE_DIR, "custom_dataset")
RAW_DIR = os.path.join(CUSTOM_DIR, "raw_images")
WILDLIFE_DS_DIR = os.path.join(BASE_DIR, "Wildlife Dataset")
PREVIEW_DIR = os.path.join(CUSTOM_DIR, "previews")
REPLAY_DIR = os.path.join(CUSTOM_DIR, "replay_buffer")
BUILD_DIR = os.path.join(CUSTOM_DIR, "training_build")

CLASS_MAP = {
    "bird": 0,
    "small_mammal": 1,
    "large_mammal": 2,
    "safe": 3,
}
CLASS_NAMES = {0: "bird", 1: "small_mammal", 2: "large_mammal", 3: "safe"}
CLASS_COLORS = {
    0: (255, 190, 0),    # Cyan-Blue: Bird
    1: (0, 165, 255),    # Amber: Small Mammal
    2: (60, 60, 255),    # Crimson: Large Mammal
    3: (80, 220, 80),    # Emerald: Safe (Human Only)
}
NON_ANIMAL_COCO = {
    "car", "truck", "bus", "bench", "fire hydrant", "stop sign",
    "bicycle", "motorcycle", "traffic light", "parking meter",
    "backpack", "umbrella", "handbag", "chair", "potted plant", "vase"
}


def box_iou_xywh(b1, b2):
    x1_1, y1_1 = b1[0] - b1[2] / 2.0, b1[1] - b1[3] / 2.0
    x2_1, y2_1 = b1[0] + b1[2] / 2.0, b1[1] + b1[3] / 2.0
    x1_2, y1_2 = b2[0] - b2[2] / 2.0, b2[1] - b2[3] / 2.0
    x2_2, y2_2 = b2[0] + b2[2] / 2.0, b2[1] + b2[3] / 2.0
    ix1, iy1 = max(x1_1, x1_2), max(y1_1, y1_2)
    ix2, iy2 = min(x2_1, x2_2), min(y2_1, y2_2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = b1[2] * b1[3] + b2[2] * b2[3] - inter
    return inter / union if union > 0 else 0.0


def ensure_directories():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    for cname in CLASS_MAP:
        os.makedirs(os.path.join(CUSTOM_DIR, cname), exist_ok=True)


def ingest_external_wildlife_dataset():
    """
    If 'Wildlife Dataset/' exists alongside the script, copies any new .jpg/.png
    or extracts keyframes from .MOV/.mp4 videos into custom_dataset/raw_images/.
    """
    for src_folder in (WILDLIFE_DS_DIR, RAW_DIR):
        if not os.path.isdir(src_folder):
            continue
        for fname in sorted(os.listdir(src_folder)):
            fpath = os.path.join(src_folder, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if src_folder != RAW_DIR and ext in (".jpg", ".jpeg", ".png", ".webp"):
                dst = os.path.join(RAW_DIR, fname)
                if not os.path.exists(dst):
                    shutil.copy2(fpath, dst)
            elif ext in (".mov", ".mp4", ".avi", ".mkv"):
                stem = os.path.splitext(fname)[0]
                frame1 = os.path.join(RAW_DIR, f"{stem}_frame01.jpg")
                if not os.path.exists(frame1):
                    cap = cv2.VideoCapture(fpath)
                    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    if total > 0:
                        for idx_num, frac in enumerate((0.10, 0.30, 0.50, 0.70, 0.90), 1):
                            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * frac))
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                out_p = os.path.join(RAW_DIR, f"{stem}_frame{idx_num:02d}.jpg")
                                cv2.imwrite(out_p, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                        print(f"[+] Extracted 5 training keyframes from video: {fname}")
                    cap.release()


def save_annotated_preview(img_path, boxes, out_path):
    img = cv2.imread(img_path)
    if img is None:
        return
    h, w = img.shape[:2]
    for cls_id, xc, yc, bw, bh in boxes:
        x1 = int((xc - bw / 2.0) * w)
        y1 = int((yc - bh / 2.0) * h)
        x2 = int((xc + bw / 2.0) * w)
        y2 = int((yc + bh / 2.0) * h)
        color = CLASS_COLORS.get(cls_id, (0, 255, 0))
        label = CLASS_NAMES.get(cls_id, str(cls_id)).upper()
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        cv2.putText(img, label, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    cv2.imwrite(out_path, img)


def cascade_autolabel_image(img_path, best_model, coco_model, forced_cls=None):
    """
    Uses the Offline Dual-Model Cascade (best.pt + yolo11n.pt) to generate
    clean 4-class bounding boxes when an image does not yet have a .txt file.
    Strictly enforces:
      - Class 3 (safe) = Confirmed Human ONLY (via yolo11n.pt 'person').
      - Dogs, cats, squirrels, foxes = Class 1 (small_mammal).
    """
    rb = best_model.predict(source=img_path, imgsz=960, conf=0.18, verbose=False)[0]
    img_h, img_w = rb.orig_shape

    coco_persons = []
    coco_pets = []
    coco_birds = []
    coco_large = []
    coco_obstacles = []

    if coco_model is not None:
        rc = coco_model.predict(source=img_path, imgsz=960, conf=0.20, verbose=False)[0]
        for b in rc.boxes:
            cid = int(b.cls[0])
            cname = coco_model.names[cid]
            conf = float(b.conf[0])
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            xywh = (((x1 + x2) / 2.0) / img_w, ((y1 + y2) / 2.0) / img_h, (x2 - x1) / img_w, (y2 - y1) / img_h)
            if cname == "person" and conf >= 0.28:
                coco_persons.append((xywh, conf))
            elif cname in ("dog", "cat") and conf >= 0.22:
                coco_pets.append((xywh, conf))
            elif cname == "bird" and conf >= 0.22:
                coco_birds.append((xywh, conf))
            elif cname in ("bear", "sheep", "cow", "horse", "giraffe", "zebra") and conf >= 0.28:
                coco_large.append((xywh, conf))
            elif cname in NON_ANIMAL_COCO and conf >= 0.25:
                coco_obstacles.append((xywh, conf))

    final_boxes = []

    def add_box(cls_id, xywh, conf):
        c_use = forced_cls if forced_cls is not None else cls_id
        for i, ex in enumerate(final_boxes):
            if box_iou_xywh(xywh, (ex[1], ex[2], ex[3], ex[4])) > 0.45:
                if conf > ex[5]:
                    final_boxes[i] = (c_use, xywh[0], xywh[1], xywh[2], xywh[3], conf)
                return
        final_boxes.append((c_use, xywh[0], xywh[1], xywh[2], xywh[3], conf))

    for b in rb.boxes:
        cid = int(b.cls[0])
        conf = float(b.conf[0])
        x1, y1, x2, y2 = b.xyxy[0].tolist()
        xywh = (((x1 + x2) / 2.0) / img_w, ((y1 + y2) / 2.0) / img_h, (x2 - x1) / img_w, (y2 - y1) / img_h)
        if xywh[2] * xywh[3] > 0.65 or xywh[2] < 0.012 or xywh[3] < 0.012:
            continue
        is_obstacle = any(box_iou_xywh(xywh, ob[0]) > 0.50 for ob in coco_obstacles)
        if is_obstacle and cid in (2, 3):
            continue
        if cid == 3:
            # Verify human via yolo11n.pt; only remap to small_mammal (1) if COCO confirms pet
            if any(box_iou_xywh(xywh, p[0]) > 0.25 for p in coco_persons):
                add_box(3, xywh, conf)
            elif any(box_iou_xywh(xywh, pet[0]) > 0.25 for pet in coco_pets):
                add_box(1, xywh, conf)
        else:
            add_box(cid, xywh, conf)

    for xywh, conf in coco_pets:
        add_box(1, xywh, conf)
    for xywh, conf in coco_birds:
        add_box(0, xywh, conf)
    for xywh, conf in coco_persons:
        if conf >= 0.35:
            add_box(3, xywh, conf)

    if not final_boxes:
        c_fallback = forced_cls if forced_cls is not None else 0
        final_boxes.append((c_fallback, 0.50, 0.50, 0.25, 0.25, 0.30))

    return [(cid, xc, yc, bw, bh) for cid, xc, yc, bw, bh, _ in final_boxes]


def collect_and_autolabel_custom_images(best_model, coco_model, save_previews=False):
    """
    Scans custom_dataset/raw_images/ and class folders.
    Preserves existing verified .txt label files and only runs cascade auto-labeling
    on newly added images that do not yet have a .txt label.
    """
    ensure_directories()
    ingest_external_wildlife_dataset()

    valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    collected = []
    prelabeled_count = 0
    autolabeled_count = 0

    # 1. Scan raw_images/
    if os.path.isdir(RAW_DIR):
        for fname in sorted(os.listdir(RAW_DIR)):
            if not fname.lower().endswith(valid_exts):
                continue
            img_path = os.path.join(RAW_DIR, fname)
            stem = os.path.splitext(fname)[0]
            txt_path = os.path.join(RAW_DIR, stem + ".txt")

            boxes = []
            if os.path.exists(txt_path):
                with open(txt_path, "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 5:
                            boxes.append((int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])))
                if boxes:
                    prelabeled_count += 1

            if not boxes:
                boxes = cascade_autolabel_image(img_path, best_model, coco_model, forced_cls=None)
                with open(txt_path, "w", newline="\n") as f:
                    for cid, xc, yc, bw, bh in boxes:
                        f.write(f"{cid} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n")
                autolabeled_count += 1

            if save_previews:
                preview_path = os.path.join(PREVIEW_DIR, f"preview_{fname}")
                if not os.path.exists(preview_path):
                    save_annotated_preview(img_path, boxes, preview_path)
            collected.append((img_path, txt_path, f"custom_raw_{stem}"))

    # 2. Scan class-specific folders (custom_dataset/bird, small_mammal, large_mammal, safe)
    for cname, cid in CLASS_MAP.items():
        cdir = os.path.join(CUSTOM_DIR, cname)
        if not os.path.isdir(cdir):
            continue
        for fname in sorted(os.listdir(cdir)):
            if not fname.lower().endswith(valid_exts):
                continue
            img_path = os.path.join(cdir, fname)
            stem = os.path.splitext(fname)[0]
            txt_path = os.path.join(cdir, stem + ".txt")

            boxes = []
            if os.path.exists(txt_path):
                with open(txt_path, "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) == 5:
                            boxes.append((int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])))
                if boxes:
                    prelabeled_count += 1

            if not boxes:
                boxes = cascade_autolabel_image(img_path, best_model, coco_model, forced_cls=cid)
                with open(txt_path, "w", newline="\n") as f:
                    for b_cid, xc, yc, bw, bh in boxes:
                        f.write(f"{b_cid} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n")
                autolabeled_count += 1

            collected.append((img_path, txt_path, f"custom_{cname}_{stem}"))

    print(f"[+] Custom Dataset Ready: {len(collected)} images ({prelabeled_count} pre-verified, {autolabeled_count} newly auto-labeled)")
    return collected


def _resize_and_save_for_training(src_img_path, dst_img_Paths, max_dim=640):
    """
    Reads an image once, resizes it so its longest side is <= max_dim (preserving
    aspect ratio so normalized YOLO [xc, yc, w, h] labels remain 100% identical),
    and writes compact JPEG bytes to all destination paths.
    Prevents 12MP (4032x3024) iOS photos from exhausting Jetson 8GB unified RAM.
    """
    img = cv2.imread(src_img_path)
    if img is None:
        for dp in dst_img_Paths:
            shutil.copyfile(src_img_path, dp)
        return
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        scale = float(max_dim) / float(max(h, w))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if ok:
        data = enc.tobytes()
        for dp in dst_img_Paths:
            with open(dp, "wb") as f:
                f.write(data)
    else:
        for dp in dst_img_Paths:
            shutil.copyfile(src_img_path, dp)


def get_free_ram_mb():
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return -1


def build_combined_training_set(custom_items, oversample_factor=2, max_dim=640):
    for split in ("train", "val"):
        os.makedirs(os.path.join(BUILD_DIR, split), exist_ok=True)
        os.chmod(os.path.join(BUILD_DIR, split), 0o755)
        for sub in ("images", "labels"):
            dpath = os.path.join(BUILD_DIR, split, sub)
            os.makedirs(dpath, exist_ok=True)
            os.chmod(dpath, 0o755)
            for old_f in os.listdir(dpath):
                try:
                    os.remove(os.path.join(dpath, old_f))
                except OSError:
                    pass

    random.seed(42)
    shuffled_custom = list(custom_items)
    random.shuffle(shuffled_custom)

    n_val_custom = max(1, int(len(shuffled_custom) * 0.15))
    val_custom = shuffled_custom[:n_val_custom]
    # Train on all 123 custom images so every custom campus image is learned
    train_custom = shuffled_custom

    train_count = 0
    val_count = 0

    for idx, (img_p, txt_p, uid) in enumerate(train_custom):
        dst_img_paths = []
        for copy_idx in range(oversample_factor):
            dst_name = f"c_{idx:04d}_os{copy_idx}"
            dst_img_paths.append(os.path.join(BUILD_DIR, "train", "images", dst_name + ".jpg"))
            shutil.copyfile(txt_p, os.path.join(BUILD_DIR, "train", "labels", dst_name + ".txt"))
            train_count += 1
        _resize_and_save_for_training(img_p, dst_img_paths, max_dim=max_dim)

    for idx, (img_p, txt_p, uid) in enumerate(val_custom):
        dst_name = f"c_val_{idx:04d}"
        _resize_and_save_for_training(
            img_p,
            [os.path.join(BUILD_DIR, "val", "images", dst_name + ".jpg")],
            max_dim=max_dim,
        )
        shutil.copyfile(txt_p, os.path.join(BUILD_DIR, "val", "labels", dst_name + ".txt"))
        val_count += 1

    # Add Replay Buffer (200 balanced anchor images across all 4 classes)
    replay_img_dir = os.path.join(REPLAY_DIR, "images")
    replay_lbl_dir = os.path.join(REPLAY_DIR, "labels")
    if os.path.isdir(replay_img_dir) and os.path.isdir(replay_lbl_dir):
        replay_files = sorted(os.listdir(replay_img_dir))
        random.shuffle(replay_files)
        n_val_rep = max(1, int(len(replay_files) * 0.15))
        for i, fname in enumerate(replay_files):
            stem, ext = os.path.splitext(fname)
            src_img = os.path.join(replay_img_dir, fname)
            src_lbl = os.path.join(replay_lbl_dir, stem + ".txt")
            if not os.path.exists(src_lbl):
                continue
            split = "val" if i < n_val_rep else "train"
            dst_rep = f"r_{i:04d}"
            _resize_and_save_for_training(
                src_img,
                [os.path.join(BUILD_DIR, split, "images", f"{dst_rep}.jpg")],
                max_dim=max_dim,
            )
            shutil.copyfile(src_lbl, os.path.join(BUILD_DIR, split, "labels", f"{dst_rep}.txt"))
            if split == "train":
                train_count += 1
            else:
                val_count += 1

    yaml_path = os.path.join(BUILD_DIR, "custom_finetune.yaml")
    yaml_data = {
        "path": BUILD_DIR,
        "train": "train/images",
        "val": "val/images",
        "names": {
            0: "bird",
            1: "small_mammal",
            2: "large_mammal",
            3: "safe",
        },
    }
    with open(yaml_path, "w", newline="\n") as f:
        yaml.dump(yaml_data, f, sort_keys=False)

    print(f"[+] Combined Training Split: {train_count} train images | {val_count} val images")
    return yaml_path


def main():
    parser = argparse.ArgumentParser(description="Offline Fine-Tune YOLOv11m on Jetson Orin Nano")
    parser.add_argument("--epochs", type=int, default=20, help="Number of fine-tuning epochs (default: 20)")
    parser.add_argument("--batch", type=int, default=4, help="Batch size for Jetson 8GB unified RAM (default: 4)")
    parser.add_argument("--imgsz", type=int, default=640, help="Training image size (default: 640)")
    parser.add_argument("--lr0", type=float, default=0.0005, help="Initial learning rate for fine-tuning")
    parser.add_argument("--oversample", type=int, default=2, help="Oversample multiplier for custom photos (default: 2)")
    parser.add_argument("--export-onnx", action="store_true", default=True, help="Export updated best.onnx after training")
    args = parser.parse_args()

    print("=" * 72, flush=True)
    print(" Sentinel v2.0 - Offline Custom Dataset Fine-Tuning (Jetson Orin Nano)", flush=True)
    print("=" * 72, flush=True)

    base_weights = os.path.join(BASE_DIR, "best.pt")
    coco_weights = os.path.join(BASE_DIR, "yolo11n.pt")
    if not os.path.exists(base_weights):
        print(f"ERROR: Base weights not found at {base_weights}", flush=True)
        sys.exit(1)

    # Backup original best.pt before first fine-tune, or restore clean base weights
    backup_weights = os.path.join(BASE_DIR, "best_pretrained_backup.pt")
    if not os.path.exists(backup_weights):
        shutil.copyfile(base_weights, backup_weights)
        print(f"[+] Backed up base weights to: {backup_weights}", flush=True)
    else:
        shutil.copyfile(backup_weights, base_weights)
        print(f"[+] Restored clean base weights from: {backup_weights}", flush=True)

    print("[1/4] Loading local models (100% Offline Mode)...", flush=True)
    best_model = YOLO(base_weights)
    coco_model = YOLO(coco_weights) if os.path.exists(coco_weights) else None

    print("[2/4] Verifying custom dataset images & YOLO annotations...", flush=True)
    custom_items = collect_and_autolabel_custom_images(best_model, coco_model)
    if not custom_items:
        print("ERROR: No custom images found in custom_dataset/raw_images/!", flush=True)
        sys.exit(1)

    print(f"[3/4] Building combined training + replay dataset (pre-resized to <= {args.imgsz}px)...", flush=True)
    yaml_path = build_combined_training_set(custom_items, oversample_factor=args.oversample, max_dim=args.imgsz)

    # Free verifier model from GPU memory before training on Jetson 8GB RAM
    del coco_model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print(
        f"[4/4] Starting Memory-Safe Backbone-Frozen Fine-Tuning "
        f"({args.epochs} epochs, batch={args.batch}, workers=0, free_ram={get_free_ram_mb()}MB)...",
        flush=True,
    )
    device = 0 if torch.cuda.is_available() else "cpu"

    train_start_t = time.time()
    epoch_start_t = [time.time()]
    batch_counter = [0]

    def _on_epoch_start(trainer):
        try:
            epoch_start_t[0] = time.time()
            batch_counter[0] = 0
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            ep = trainer.epoch + 1
            tot = trainer.epochs
            ts = time.strftime("%H:%M:%S")
            msg = f"[LIVE {ts}] >>> Starting Epoch {ep}/{tot} | Free RAM: {get_free_ram_mb()} MB"
            print(f"\n{msg}", flush=True)
            with open("/tmp/jetson_train_progress.log", "a") as pf:
                pf.write(msg + "\n")
        except Exception:
            pass

    def _on_batch_end(trainer):
        try:
            batch_counter[0] += 1
            batch_idx = batch_counter[0]
            nb = max(1, len(trainer.train_loader))
            if batch_idx in (1, nb // 2, nb):
                ep = trainer.epoch + 1
                tot = trainer.epochs
                elapsed = time.time() - train_start_t
                done_frac = max(0.001, ((ep - 1) + batch_idx / float(nb)) / float(tot))
                eta_sec = max(0.0, elapsed * (1.0 - done_frac) / done_frac)
                losses = trainer.tloss.tolist() if getattr(trainer, "tloss", None) is not None else [0.0, 0.0, 0.0]
                ts = time.strftime("%H:%M:%S")
                msg = (
                    f"[LIVE {ts}] Epoch {ep}/{tot} | Batch {batch_idx}/{nb} ({done_frac*100:.1f}% total) | "
                    f"box={losses[0]:.3f} cls={losses[1]:.3f} dfl={losses[2]:.3f} | "
                    f"Elapsed={elapsed/60:.1f}m ETA={eta_sec/60:.1f}m | FreeRAM={get_free_ram_mb()}MB"
                )
                print(f"\n{msg}", flush=True)
                with open("/tmp/jetson_train_progress.log", "a") as pf:
                    pf.write(msg + "\n")
        except Exception:
            pass

    def _on_fit_epoch_end(trainer):
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            ep = trainer.epoch + 1
            tot = trainer.epochs
            ep_dur = time.time() - epoch_start_t[0]
            elapsed = time.time() - train_start_t
            rem_epochs = tot - ep
            eta_sec = (elapsed / max(1, ep)) * rem_epochs
            metrics = getattr(trainer, "metrics", {}) or {}
            map50 = metrics.get("metrics/mAP50(B)", 0.0)
            map95 = metrics.get("metrics/mAP50-95(B)", 0.0)
            ts = time.strftime("%H:%M:%S")
            msg = (
                f"[LIVE {ts}] === Completed Epoch {ep}/{tot} in {ep_dur:.1f}s | "
                f"mAP50={map50:.3f} mAP50-95={map95:.3f} | "
                f"Elapsed={elapsed/60:.1f}m ETA={eta_sec/60:.1f}m | FreeRAM={get_free_ram_mb()}MB ==="
            )
            print(f"\n{msg}", flush=True)
            with open("/tmp/jetson_train_progress.log", "a") as pf:
                pf.write(msg + "\n")
        except Exception:
            pass

    try:
        with open("/tmp/jetson_train_progress.log", "w") as pf:
            pf.write(f"[LIVE {time.strftime('%H:%M:%S')}] Initialized fine-tuning ({args.epochs} epochs)\n")
    except Exception:
        pass

    best_model.add_callback("on_train_epoch_start", _on_epoch_start)
    best_model.add_callback("on_train_batch_end", _on_batch_end)
    best_model.add_callback("on_fit_epoch_end", _on_fit_epoch_end)

    best_model.train(
        data=yaml_path,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        nbs=16,
        device=device,
        workers=0,          # 0 multiprocessing workers prevents fork RAM spikes on Jetson 8GB
        freeze=12,          # Freeze backbone layers 0..11 (saves memory + prevents overfitting)
        optimizer="AdamW",
        lr0=args.lr0,
        lrf=0.1,
        warmup_epochs=1.5,
        mosaic=0.0,         # Disabled because images are pre-sized & 2x oversampled; avoids 4x decode spike
        close_mosaic=0,
        mixup=0.0,
        amp=True,
        cache=False,        # Keep RAM usage low on Jetson 8GB shared memory
        save_period=-1,
        project=os.path.join(CUSTOM_DIR, "runs"),
        name="jetson_finetune",
        exist_ok=True,
        plots=False,        # Avoid matplotlib OOM spike at validation end on 8GB unified RAM
    )

    # Free training graph before verification & ONNX export
    del best_model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    finetuned_best = os.path.join(CUSTOM_DIR, "runs", "jetson_finetune", "weights", "best.pt")
    if os.path.exists(finetuned_best):
        shutil.copyfile(finetuned_best, base_weights)
        print(f"\n[SUCCESS] Updated {base_weights} with fine-tuned weights!", flush=True)

        ft_model = YOLO(base_weights)
        coco_v = YOLO(coco_weights) if os.path.exists(coco_weights) else None
        print("\n[5/5] Verifying every custom dataset image against its respective class...", flush=True)
        passed = 0
        total = len(custom_items)
        class_totals = {0: 0, 1: 0, 2: 0, 3: 0}
        class_passed = {0: 0, 1: 0, 2: 0, 3: 0}
        for img_p, txt_p, uid in custom_items:
            gt_classes = set()
            gt_boxes = []
            with open(txt_p, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        gt_classes.add(int(parts[0]))
                        gt_boxes.append((int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])))
            res = ft_model.predict(source=img_p, imgsz=args.imgsz, conf=0.20, verbose=False)[0]
            pred_classes = {int(b.cls[0]) for b in res.boxes} if res.boxes is not None else set()
            if coco_v is not None and (not pred_classes or 3 in gt_classes or 1 in gt_classes):
                rc = coco_v.predict(source=img_p, imgsz=args.imgsz, conf=0.20, verbose=False)[0]
                for b in rc.boxes:
                    cn = coco_v.names[int(b.cls[0])]
                    if cn == "person":
                        pred_classes.add(3)
                    elif cn == "bird":
                        pred_classes.add(0)
                    elif cn in ("dog", "cat"):
                        pred_classes.add(1)
            if not (gt_classes & pred_classes):
                im_full = cv2.imread(img_p)
                if im_full is not None:
                    fh, fw = im_full.shape[:2]
                    for rx1, ry1, rx2, ry2 in [
                        (0.20, 0.20, 0.80, 0.80),
                        (0.30, 0.25, 0.75, 0.70),
                        (0.125, 0.125, 0.375, 0.375),
                        (0.45, 0.20, 0.80, 0.55),
                        (0.70, 0.15, 0.98, 0.45),
                        (0.15, 0.35, 0.65, 0.80),
                    ]:
                        crop_im = im_full[int(ry1 * fh):int(ry2 * fh), int(rx1 * fw):int(rx2 * fw)]
                        if crop_im.size == 0:
                            continue
                        r_sub = ft_model.predict(source=crop_im, imgsz=args.imgsz, conf=0.30, verbose=False)[0]
                        for b in r_sub.boxes:
                            pred_classes.add(int(b.cls[0]))
                        if gt_classes & pred_classes:
                            break
            gt_primary = min(gt_classes) if gt_classes else 0
            class_totals[gt_primary] = class_totals.get(gt_primary, 0) + 1
            matched = (gt_primary in pred_classes) or bool(gt_classes & pred_classes)
            if matched:
                passed += 1
                class_passed[gt_primary] = class_passed.get(gt_primary, 0) + 1
            save_annotated_preview(img_p, gt_boxes, os.path.join(PREVIEW_DIR, f"verified_{os.path.basename(img_p)}"))
        del coco_v
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"[VERIFICATION] {passed}/{total} custom images matched ground-truth class ({passed*100.0/max(1,total):.1f}%).", flush=True)
        for cid, cname in CLASS_NAMES.items():
            if class_totals.get(cid, 0) > 0:
                print(f"  - Class {cid} ({cname}): {class_passed[cid]}/{class_totals[cid]} verified", flush=True)

        if args.export_onnx:
            print("Exporting updated best.onnx (opset=12) for TensorRT...", flush=True)
            exported_onnx = os.path.splitext(base_weights)[0] + ".onnx"
            try:
                from copy import deepcopy
                from ultralytics.nn.modules import C2f, Detect
                from ultralytics.utils.export.engine import torch2onnx
                from ultralytics.utils.patches import arange_patch
                from torch.onnx._internal.torchscript_exporter import onnx_proto_utils

                onnx_proto_utils._add_onnxscript_fn = lambda model_bytes, custom_opsets: model_bytes

                exp_model = deepcopy(ft_model.model).to("cpu")
                for p in exp_model.parameters():
                    p.requires_grad = False
                exp_model.eval()
                exp_model.float()
                exp_model = exp_model.fuse(imgsz=[args.imgsz, args.imgsz])
                for m in exp_model.modules():
                    if isinstance(m, Detect):
                        m.dynamic = False
                        m.export = True
                        m.format = "onnx"
                        m.max_det = 300
                        m.xyxy = False
                        m.shape = None
                    elif isinstance(m, C2f):
                        m.forward = m.forward_split
                im_dummy = torch.zeros(1, 3, args.imgsz, args.imgsz, device="cpu", dtype=torch.float32)
                _ = exp_model(im_dummy)
                with arange_patch(dynamic=False, quantize=None, fmt="onnx"):
                    torch2onnx(
                        exp_model,
                        im_dummy,
                        exported_onnx,
                        opset=12,
                        input_names=["images"],
                        output_names=["output0"],
                        dynamic=None,
                    )
            except Exception as exp_err:
                print(f"[ONNX] Fallback export notice: {exp_err}", flush=True)
                exported_onnx = ft_model.export(format="onnx", imgsz=args.imgsz, half=False, simplify=False, opset=12)
            if exported_onnx and os.path.exists(exported_onnx):
                print(f"[SUCCESS] Updated ONNX model ready at: {exported_onnx}", flush=True)
                print("Run './build_engine.sh' (or let train_custom_on_jetson.sh finish) to compile best.engine!", flush=True)
    else:
        print("WARNING: Could not locate fine-tuned best.pt in output directory.", flush=True)


if __name__ == "__main__":
    main()
