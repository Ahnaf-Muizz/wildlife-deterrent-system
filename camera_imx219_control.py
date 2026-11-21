#!/usr/bin/env python3
"""
Sony IMX219 Camera Control with OpenCV on NVIDIA Jetson Orin / Xavier / Nano.

Features:
1. GStreamer Hardware Pipeline (nvarguscamerasrc + nvvidconv)
2. Hardware & Software Automatic White Balance (AWB)
3. Hardware & Software Orientation Handling (flip-method + auto-detection)
4. Focus Analysis (Laplacian sharpness metric) & Motorized Autofocus (Arducam I2C VCM)
"""

import os
import sys
import time
import argparse
import numpy as np

# Ensure Jetson system OpenCV with GStreamer support is loaded (avoid pip wheel shadowing)
def _ensure_gstreamer_cv2():
    try:
        import cv2
        if "GStreamer:                   YES" in cv2.getBuildInformation():
            return cv2
    except Exception:
        pass
    sys.modules.pop("cv2", None)
    sys.path = [p for p in sys.path if ".local" not in p] + ["/usr/lib/python3/dist-packages", "/usr/lib/python3.12/dist-packages"]
    import cv2
    return cv2

cv2 = _ensure_gstreamer_cv2()

# ==============================================================================
# 1. GStreamer Pipeline Builder
# ==============================================================================
def build_nvargus_pipeline(
    sensor_id: int = 0,
    capture_width: int = 1920,
    capture_height: int = 1080,
    framerate: int = 30,
    flip_method: int = 2,
    display_width: int = 1280,
    display_height: int = 720,
    wbmode: int = 1,
) -> str:
    """
    Builds the GStreamer pipeline string for nvarguscamerasrc.
    - sensor-id: CSI port (0 = CAM0 / J1, 1 = CAM1 / J2)
    - flip-method: nvvidconv hardware rotation
        0 = none, 1 = CCW 90, 2 = 180 deg (standard for Jetson inverted mount), 3 = CW 90
    - wbmode: Hardware ISP White Balance
        0 = off, 1 = auto (default), 2 = incandescent, 3 = fluorescent,
        4 = warm-fluorescent, 5 = daylight, 6 = cloudy-daylight
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


# ==============================================================================
# 2. Software Auto White Balance (Gray World Algorithm with Temporal Smoothing)
# ==============================================================================
class GrayWorldAWB:
    """
    Software Auto White Balance based on the Gray-World assumption:
    The average reflected color in a natural scene is achromatic (neutral gray).
    Includes temporal smoothing to avoid sudden color shifts.
    """
    def __init__(self, smoothing: float = 0.85):
        self.smoothing = smoothing
        self.running_gain = None  # [gain_b, gain_g, gain_r]

    def balance(self, bgr_frame: np.ndarray) -> np.ndarray:
        # Fast downscaled sample for computing channel means
        small = cv2.resize(bgr_frame, (160, 90), interpolation=cv2.INTER_NEAREST)
        mean_b = float(np.mean(small[:, :, 0]))
        mean_g = float(np.mean(small[:, :, 1]))
        mean_r = float(np.mean(small[:, :, 2]))

        if mean_b < 1e-3 or mean_g < 1e-3 or mean_r < 1e-3:
            return bgr_frame

        gray_target = (mean_b + mean_g + mean_r) / 3.0
        instant_gain = np.array([
            gray_target / mean_b,
            gray_target / mean_g,
            gray_target / mean_r,
        ], dtype=np.float32)

        # Apply exponential moving average to prevent flickering
        if self.running_gain is None:
            self.running_gain = instant_gain
        else:
            self.running_gain = (self.smoothing * self.running_gain) + ((1.0 - self.smoothing) * instant_gain)

        # Scale channels using look-up tables (LUTs) for maximum speed
        lut_b = np.clip(np.arange(256) * self.running_gain[0], 0, 255).astype(np.uint8)
        lut_g = np.clip(np.arange(256) * self.running_gain[1], 0, 255).astype(np.uint8)
        lut_r = np.clip(np.arange(256) * self.running_gain[2], 0, 255).astype(np.uint8)

        b, g, r = cv2.split(bgr_frame)
        b = cv2.LUT(b, lut_b)
        g = cv2.LUT(g, lut_g)
        r = cv2.LUT(r, lut_r)
        return cv2.merge([b, g, r])


# ==============================================================================
# 3. Focus Metric & Motorized Auto Focus Controller
# ==============================================================================
def compute_focus_score(frame: np.ndarray) -> float:
    """
    Computes image sharpness / focus measure using the variance of the Laplacian.
    Higher score = Sharper image / Better focus.
    """
    # Downscale central region to speed up evaluation
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    rw, rh = int(w * 0.4), int(h * 0.4)
    roi = frame[cy - rh // 2 : cy + rh // 2, cx - rw // 2 : cx + rw // 2]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    return float(laplacian.var())


class MotorizedFocusController:
    """
    Controls Arducam IMX219 Motorized Focus via I2C (DW9714 VCM driver).
    Default I2C bus on Jetson Orin CAM0 is typically /dev/i2c-7 or /dev/i2c-8.
    Default I2C address is 0x0c.
    """
    def __init__(self, i2c_bus: int = 7, i2c_addr: int = 0x0C):
        self.i2c_bus = i2c_bus
        self.i2c_addr = i2c_addr
        self.is_available = False
        self._check_availability()

    def _check_availability(self):
        try:
            import smbus2
            self.bus = smbus2.SMBus(self.i2c_bus)
            # Must actively communicate with the I2C chip address to confirm physical motor
            self.bus.read_byte(self.i2c_addr)
            self.is_available = True
        except Exception:
            self.is_available = False

    def set_focus(self, val: int):
        """Sets focus step (0 to 1023) for DW9714 VCM."""
        if not self.is_available:
            return
        val = max(0, min(1023, int(val)))
        # DW9714 format: 10-bit DAC value
        d1 = (val >> 4) & 0x3F
        d2 = (val & 0x0F) << 4
        try:
            self.bus.write_i2c_block_data(self.i2c_addr, d1, [d2])
        except Exception:
            pass

    def run_autofocus(self, cap: cv2.VideoCapture) -> int:
        """
        Runs an auto-focus sweep to find the step that maximizes Laplacian variance.
        """
        if not self.is_available:
            print("[AF] Motorized I2C controller not available. Lens is fixed-focus.")
            return -1

        print("[AF] Starting Auto-Focus sweep (0-1000)...")
        best_step = 0
        max_score = -1.0

        # Coarse sweep
        for step in range(0, 1020, 60):
            self.set_focus(step)
            time.sleep(0.04)  # Allow VCM voice-coil settle time
            # Discard stale buffer
            cap.grab()
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            score = compute_focus_score(frame)
            if score > max_score:
                max_score = score
                best_step = step

        # Fine sweep around best coarse step
        start = max(0, best_step - 50)
        end = min(1023, best_step + 50)
        for step in range(start, end, 10):
            self.set_focus(step)
            time.sleep(0.04)
            cap.grab()
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            score = compute_focus_score(frame)
            if score > max_score:
                max_score = score
                best_step = step

        self.set_focus(best_step)
        print(f"[AF] Auto-Focus locked at step {best_step} (Sharpness: {max_score:.1f})")
        return best_step


# ==============================================================================
# 4. Software Auto-Orientation
# ==============================================================================
def detect_upside_down_heuristic(frame: np.ndarray) -> bool:
    """
    Heuristic to detect inverted orientation based on sky/ground brightness.
    In outdoor/ambient settings, the top half is typically brighter than the bottom half.
    Returns True if frame is likely upside-down.
    """
    h = frame.shape[0]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    top_half = gray[0 : h // 3, :]
    bottom_half = gray[2 * h // 3 :, :]
    top_mean = float(np.mean(top_half))
    bottom_mean = float(np.mean(bottom_half))

    # If the bottom is significantly brighter than the top (by > 25 intensity levels),
    # the camera is likely upside-down.
    return (bottom_mean - top_mean) > 25.0


# ==============================================================================
# 5. Main Application Loop
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="IMX219 OpenCV Controller on Jetson")
    parser.add_argument("--sensor-id", type=int, default=0, help="CSI sensor ID (0 or 1)")
    parser.add_argument("--flip", type=int, default=2, help="Hardware flip-method: 0=none, 2=rotate-180")
    parser.add_argument("--width", type=int, default=1280, help="Display width")
    parser.add_argument("--height", type=int, default=720, help="Display height")
    parser.add_argument("--fps", type=int, default=30, help="Frame rate")
    parser.add_argument("--no-software-awb", action="store_true", help="Disable software Gray-World AWB")
    parser.add_argument("--no-hud", action="store_true", help="Hide the HUD info overlay by default")
    parser.add_argument("--mirror", action="store_true", help="Mirror (flip horizontally) by default")
    parser.add_argument("--i2c-bus", type=int, default=7, help="I2C bus for motorized focus (e.g. 7 or 8)")
    parser.add_argument("--headless", action="store_true", help="Run without X11 GUI window (saves live_preview.jpg)")
    args = parser.parse_args()

    # Attempt opening the primary pipeline
    pipeline = build_nvargus_pipeline(
        sensor_id=args.sensor_id,
        capture_width=1920,
        capture_height=1080,
        framerate=args.fps,
        flip_method=args.flip,
        display_width=args.width,
        display_height=args.height,
        wbmode=1,
    )

    print("=" * 65)
    print(" Jetson IMX219 Camera Controller")
    print("=" * 65)
    print(f" Sensor ID:      {args.sensor_id}")
    print(f" Hardware Flip:  {args.flip} (nvvidconv flip-method={args.flip})")
    print(f" Hardware AWB:   ENABLED (Argus ISP wbmode=1)")
    print(f" Pipeline:       {pipeline}\n")

    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    # Fallback 1: Try without wbmode flag (standard bare nvarguscamerasrc)
    if not cap.isOpened():
        print("[WARN] Pipeline with wbmode=1 failed. Retrying bare hardware pipeline...")
        alt_pipe = build_nvargus_pipeline(
            sensor_id=args.sensor_id,
            capture_width=1920,
            capture_height=1080,
            framerate=args.fps,
            flip_method=args.flip,
            display_width=args.width,
            display_height=args.height,
            wbmode=None,
        )
        cap = cv2.VideoCapture(alt_pipe, cv2.CAP_GSTREAMER)

    # Fallback 2: Try alternate sensor-id (1 vs 0)
    if not cap.isOpened():
        alt_sid = 1 if args.sensor_id == 0 else 0
        print(f"[WARN] Sensor {args.sensor_id} failed. Trying alternate sensor-id={alt_sid}...")
        alt_pipe2 = build_nvargus_pipeline(
            sensor_id=alt_sid,
            capture_width=1920,
            capture_height=1080,
            framerate=args.fps,
            flip_method=args.flip,
            display_width=args.width,
            display_height=args.height,
            wbmode=None,
        )
        cap = cv2.VideoCapture(alt_pipe2, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        print("\n[ERROR] Failed to open GStreamer pipeline.")
        print("Jetson Troubleshooting Steps:")
        print("  1. Restart nvargus daemon (Argus may be locked by previous process):")
        print("     sudo systemctl restart nvargus-daemon")
        print("  2. Verify camera ribbon cable connection and run:")
        print("     ls -l /dev/video*")
        print("  3. Verify sensor-id (CAM0/J1 = 0, CAM1/J2 = 1):")
        print("     python3 camera_imx219_control.py --sensor-id 0 --flip 2")
        sys.exit(1)

    print("[SUCCESS] Camera stream active!")
    print("\nInteractive Controls (Press keys in the preview window):")
    print("  [m] - Toggle Horizontal Mirror (Left <-> Right)")
    print("  [v] - Toggle Vertical Mirror (Up <-> Down)")
    print("  [r] - Rotate 90 degrees clockwise")
    print("  [f] - Flip 180 degrees")
    print("  [w] - Toggle Software Auto White Balance")
    print("  [h] - Toggle HUD overlay on/off")
    print("  [s] - Save snapshot (snapshot.jpg)")
    print("  [q] - Quit\n")

    awb_processor = GrayWorldAWB()
    use_software_awb = not args.no_software_awb
    show_hud = not args.no_hud
    manual_rotation = 0  # 0, 90, 180, 270
    mirror_horizontal = args.mirror
    mirror_vertical = False

    fps_count = 0
    fps_time = time.time()
    current_fps = 0.0
    has_display = bool(os.environ.get("DISPLAY")) and not args.headless

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        fps_count += 1
        if time.time() - fps_time >= 1.0:
            current_fps = fps_count / (time.time() - fps_time)
            fps_count = 0
            fps_time = time.time()

        # 1. Orientation & Mirror handling
        if manual_rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif manual_rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif manual_rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if mirror_horizontal:
            frame = cv2.flip(frame, 1)

        if mirror_vertical:
            frame = cv2.flip(frame, 0)

        # 2. White Balance
        if use_software_awb:
            display_frame = awb_processor.balance(frame)
        else:
            display_frame = frame.copy()

        # 3. Clean HUD Overlay (Toggle with 'h')
        if show_hud:
            h, w = display_frame.shape[:2]
            awb_status = "Software Gray-World" if use_software_awb else "Argus ISP Only"
            mirror_str = []
            if mirror_horizontal:
                mirror_str.append("H-Mirror")
            if mirror_vertical:
                mirror_str.append("V-Mirror")
            mirror_desc = ", ".join(mirror_str) if mirror_str else "Normal (Unmirrored)"

            info_lines = [
                f"FPS: {current_fps:.1f} | Res: {w}x{h}",
                f"Orientation: Rot={manual_rotation} deg | {mirror_desc}",
                f"White Balance: {awb_status}",
            ]

            overlay = display_frame.copy()
            cv2.rectangle(overlay, (10, 10), (460, 95), (20, 20, 20), -1)
            cv2.addWeighted(overlay, 0.6, display_frame, 0.4, 0, display_frame)

            for idx, line in enumerate(info_lines):
                cv2.putText(
                    display_frame,
                    line,
                    (20, 32 + (idx * 22)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

        if has_display:
            cv2.imshow("Jetson IMX219 Control - OpenCV", display_frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            elif key == ord("m"):
                mirror_horizontal = not mirror_horizontal
                print(f"[MIRROR] Horizontal mirror (Left-Right): {'ON' if mirror_horizontal else 'OFF'}")
            elif key == ord("v"):
                mirror_vertical = not mirror_vertical
                print(f"[MIRROR] Vertical mirror (Up-Down): {'ON' if mirror_vertical else 'OFF'}")
            elif key == ord("w"):
                use_software_awb = not use_software_awb
                print(f"[TOGGLE] Software AWB: {'ON' if use_software_awb else 'OFF'}")
            elif key == ord("h"):
                show_hud = not show_hud
                print(f"[TOGGLE] HUD Overlay: {'ON' if show_hud else 'OFF'}")
            elif key == ord("r"):
                manual_rotation = (manual_rotation + 90) % 360
                print(f"[ROTATE] Current software rotation: {manual_rotation} degrees")
            elif key == ord("f"):
                manual_rotation = (manual_rotation + 180) % 360
                print(f"[FLIP] Current software rotation: {manual_rotation} degrees")
            elif key == ord("s"):
                fname = f"imx219_snap_{int(time.time())}.jpg"
                cv2.imwrite(fname, display_frame)
                print(f"[SNAPSHOT] Saved to {fname}")
        else:
            # Headless / SSH mode: periodically write frame snapshot
            if fps_count % 30 == 0:
                cv2.imwrite("live_preview.jpg", display_frame)
                sys.stdout.write(f"\r[HEADLESS] FPS: {current_fps:.1f} | Saved: live_preview.jpg   ")
                sys.stdout.flush()

    cap.release()
    if has_display:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
