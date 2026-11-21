import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  Camera,
  X,
  Aperture,
  ShieldCheck,
  AlertOctagon,
  Volume2,
  Droplets,
  Zap,
  Square,
  RefreshCw,
  CheckCircle2,
  Activity,
} from 'lucide-react';
import {
  DetectionBox,
  DeterrentEventRecord,
  DeterrentTelemetry,
  LiveDetectResponse,
  ThreatCategory,
} from '../types/sentinel';
import { notificationService } from '../services/notificationService';

interface FullPageLiveCameraProps {
  isOpen: boolean;
  onClose: () => void;
  telemetry: DeterrentTelemetry;
  onTelemetryUpdate: (t: DeterrentTelemetry) => void;
  onSnapshotSaved: (ev: DeterrentEventRecord) => void;
  onStopAll: () => Promise<void>;
}

export const FullPageLiveCamera: React.FC<FullPageLiveCameraProps> = ({
  isOpen,
  onClose,
  telemetry,
  onTelemetryUpdate,
  onSnapshotSaved,
  onStopAll,
}) => {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const videoRef = useRef<HTMLImageElement | null>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const inFlightRef = useRef<boolean>(false);
  const snapshotInFlightRef = useRef<boolean>(false);
  const lastAutoSaveEpochRef = useRef<number>(0);
  const isOpenRef = useRef<boolean>(isOpen);
  const toastTimerRef = useRef<number | null>(null);
  const retryTimerRef = useRef<number | null>(null);

  const [confThreshold, setConfThreshold] = useState<number>(0.5);
  const [autoSaveOnThreat, setAutoSaveOnThreat] = useState<boolean>(true);
  const [autoTriggerEsp32, setAutoTriggerEsp32] = useState<boolean>(true);
  const [detections, setDetections] = useState<DetectionBox[]>([]);
  const [primaryTarget, setPrimaryTarget] = useState<ThreatCategory>('None');
  const [actionTaken, setActionTaken] = useState<string>('Area Clear — No Deterrents');
  const [inferenceMs, setInferenceMs] = useState<number>(0);
  const [isCapturingSnapshot, setIsCapturingSnapshot] = useState<boolean>(false);
  const [snapshotToast, setSnapshotToast] = useState<string | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const [mirrorH, setMirrorH] = useState<boolean>(true);
  const [mirrorV, setMirrorV] = useState<boolean>(false);
  const [rotation, setRotation] = useState<number>(180);
  const [showHudOverlay, setShowHudOverlay] = useState<boolean>(true);
  const [hudNotice, setHudNotice] = useState<string | null>(null);
  const hudNoticeTimerRef = useRef<number | null>(null);

  isOpenRef.current = isOpen;

  const showHudNotice = useCallback((msg: string) => {
    setHudNotice(msg);
    if (hudNoticeTimerRef.current !== null) {
      window.clearTimeout(hudNoticeTimerRef.current);
    }
    hudNoticeTimerRef.current = window.setTimeout(() => {
      setHudNotice(null);
      hudNoticeTimerRef.current = null;
    }, 2200);
  }, []);

  // Sync native <dialog> modal state
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isOpen && !dialog.open) {
      dialog.showModal();
    } else if (!isOpen && dialog.open) {
      dialog.close();
    }
  }, [isOpen]);

  const stopCameraStream = useCallback(() => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
      toastTimerRef.current = null;
    }
    if (hudNoticeTimerRef.current !== null) {
      window.clearTimeout(hudNoticeTimerRef.current);
      hudNoticeTimerRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.removeAttribute('src');
      videoRef.current.src = '';
    }
  }, []);

  const startCameraStream = useCallback(async () => {
    setCameraError(null);
    try {
      const res = await fetch('/api/camera/control');
      if (res.ok) {
        const data = await res.json();
        if (data?.settings) {
          setMirrorH(Boolean(data.settings.mirror_h));
          setMirrorV(Boolean(data.settings.mirror_v));
          setRotation(Number(data.settings.rotation ?? 180));
        }
      }
    } catch {
      // Ignore control sync error and continue starting stream
    }
    if (isOpenRef.current && videoRef.current) {
      videoRef.current.src = `/api/camera/stream?t=${Date.now()}`;
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      void startCameraStream();
    } else {
      stopCameraStream();
      setDetections([]);
      setPrimaryTarget('None');
      setHudNotice(null);
      setSnapshotToast(null);
    }
    return () => {
      stopCameraStream();
    };
  }, [isOpen, startCameraStream, stopCameraStream]);

  useEffect(() => {
    if (!snapshotToast) return;
    const t = window.setTimeout(() => {
      setSnapshotToast(null);
    }, 3500);
    return () => window.clearTimeout(t);
  }, [snapshotToast]);

  // Draw tactical bounding boxes & non-overlapping telemetry labels onto the live full-screen <canvas>
  const drawOverlay = useCallback(
    (boxes: DetectionBox[]) => {
      const canvas = overlayCanvasRef.current;
      const video = videoRef.current;
      if (!canvas || !video) return;

      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;

      const cw = Math.round(rect.width);
      const ch = Math.round(rect.height);
      if (canvas.width !== cw || canvas.height !== ch) {
        canvas.width = cw;
        canvas.height = ch;
      }

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (!showHudOverlay || boxes.length === 0) return;

      const vw = video.naturalWidth || 1280;
      const vh = video.naturalHeight || 720;
      const scale = Math.min(canvas.width / vw, canvas.height / vh);
      const drawnW = vw * scale;
      const drawnH = vh * scale;
      const offsetX = (canvas.width - drawnW) / 2;
      const offsetY = (canvas.height - drawnH) / 2;

      const colorMap: Record<number, { stroke: string; fill: string; text: string }> = {
        2: { stroke: '#f43f5e', fill: 'rgba(244, 63, 94, 0.92)', text: '#ffffff' }, // LARGE MAMMAL
        1: { stroke: '#f59e0b', fill: 'rgba(245, 158, 11, 0.92)', text: '#090d14' }, // SMALL MAMMAL
        0: { stroke: '#38bdf8', fill: 'rgba(56, 189, 248, 0.92)', text: '#090d14' }, // BIRD
        3: { stroke: '#10b981', fill: 'rgba(16, 185, 129, 0.92)', text: '#090d14' }, // HUMAN / SAFE
      };

      const boxDrawItems: Array<{
        det: DetectionBox;
        x1: number;
        y1: number;
        x2: number;
        y2: number;
        palette: { stroke: string; fill: string; text: string };
      }> = [];

      // Pass 1: boxes and corner brackets
      for (const det of boxes) {
        const [nx1, ny1, nx2, ny2] = det.bbox_norm;
        const x1 = offsetX + nx1 * drawnW;
        const y1 = offsetY + ny1 * drawnH;
        const x2 = offsetX + nx2 * drawnW;
        const y2 = offsetY + ny2 * drawnH;
        const bw = x2 - x1;
        const bh = y2 - y1;
        const palette = colorMap[det.class_id] || colorMap[0];

        ctx.fillStyle = `${palette.stroke}18`;
        ctx.fillRect(x1, y1, bw, bh);

        ctx.strokeStyle = palette.stroke;
        ctx.lineWidth = 2;
        ctx.strokeRect(x1, y1, bw, bh);

        const cLen = Math.max(12, Math.min(28, Math.min(bw, bh) * 0.22));
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.moveTo(x1, y1 + cLen);
        ctx.lineTo(x1, y1);
        ctx.lineTo(x1 + cLen, y1);
        ctx.moveTo(x2 - cLen, y1);
        ctx.lineTo(x2, y1);
        ctx.lineTo(x2, y1 + cLen);
        ctx.moveTo(x1, y2 - cLen);
        ctx.lineTo(x1, y2);
        ctx.lineTo(x1 + cLen, y2);
        ctx.moveTo(x2 - cLen, y2);
        ctx.lineTo(x2, y2);
        ctx.lineTo(x2, y2 - cLen);
        ctx.stroke();

        boxDrawItems.push({ det, x1, y1, x2, y2, palette });
      }

      // Pass 2: non-overlapping clamped label pills
      const placedPills: Array<[number, number, number, number]> = [];
      const overlaps = (a: [number, number, number, number], b: [number, number, number, number]) =>
        !(a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1]);

      ctx.font = 'bold 13px "JetBrains Mono", Consolas, monospace';
      for (const item of boxDrawItems) {
        const label = item.det.display_label;
        const padX = 10;
        const badgeH = 26;
        const badgeW = Math.min(canvas.width - 8, ctx.measureText(label).width + padX * 2);

        const clampRect = (rx: number, ry: number): [number, number, number, number] => {
          const cx1 = Math.max(4, Math.min(canvas.width - 4 - badgeW, rx));
          const cy1 = Math.max(4, Math.min(canvas.height - 4 - badgeH, ry));
          return [cx1, cy1, cx1 + badgeW, cy1 + badgeH];
        };

        const candidates: Array<[number, number, number, number]> = [
          clampRect(item.x1, item.y1 - badgeH),
          clampRect(item.x1 + 2, item.y1 + 2),
          clampRect(item.x2 - badgeW, item.y1 - badgeH),
          clampRect(item.x1, item.y2 + 2),
        ];

        let chosen = candidates.find((c) => !placedPills.some((p) => overlaps(c, p))) || candidates[0];
        for (let step = 0; step < 3; step++) {
          const hit = placedPills.find((p) => overlaps(chosen, p));
          if (!hit) break;
          chosen = clampRect(chosen[0], hit[3] + 2);
        }
        placedPills.push(chosen);

        ctx.fillStyle = item.palette.fill;
        ctx.fillRect(chosen[0], chosen[1], badgeW, badgeH);
        ctx.fillStyle = item.palette.text;
        ctx.fillText(label, chosen[0] + padX, chosen[1] + 17);
      }
    },
    [showHudOverlay]
  );

  // Send frame to backend /api/live/detect
  const sendFrameForDetection = useCallback(
    async (saveSnapshot = false, isAutoSave = false) => {
      if (!isOpenRef.current) return;
      const video = videoRef.current;
      if (!video) return;
      if (saveSnapshot) {
        if (snapshotInFlightRef.current) return;
        snapshotInFlightRef.current = true;
        setIsCapturingSnapshot(true);
      } else {
        if (inFlightRef.current || snapshotInFlightRef.current) return;
        inFlightRef.current = true;
      }

      try {
        const formData = new FormData();
        formData.append('use_csi', 'true');
        formData.append('conf', String(confThreshold));
        formData.append('auto_trigger', String(autoTriggerEsp32));
        formData.append('save_snapshot', String(saveSnapshot));
        formData.append('auto_save', String(isAutoSave));

        const res = await fetch('/api/live/detect', {
          method: 'POST',
          body: formData,
        });
        if (!res.ok) return;

        const data: LiveDetectResponse = await res.json();
        if (!isOpenRef.current) return;

        setDetections(data.detections);
        setPrimaryTarget(data.primary_target);
        setActionTaken(data.action_taken);
        setInferenceMs(data.inference_ms);
        onTelemetryUpdate(data.telemetry);
        drawOverlay(data.detections);

        if (data.primary_target !== 'None') {
          notificationService.notifyDetection(
            data.primary_target,
            data.max_confidence,
            data.actuators,
            data.sound_duration_ms,
            saveSnapshot
          );
        }

        if (data.saved_event) {
          onSnapshotSaved(data.saved_event);
          setSnapshotToast(
            `Snapshot Saved: ${data.saved_event.primary_target} (${Math.round(
              data.saved_event.confidence * 100
            )}%)`
          );
          if (toastTimerRef.current !== null) {
            window.clearTimeout(toastTimerRef.current);
          }
          toastTimerRef.current = window.setTimeout(() => {
            setSnapshotToast(null);
            toastTimerRef.current = null;
          }, 3500);
        } else if (
          !saveSnapshot &&
          autoSaveOnThreat &&
          (data.primary_target === 'BIRD' ||
            data.primary_target === 'SMALL MAMMAL' ||
            data.primary_target === 'LARGE MAMMAL') &&
          Date.now() - lastAutoSaveEpochRef.current > 6500
        ) {
          lastAutoSaveEpochRef.current = Date.now();
          inFlightRef.current = false;
          await sendFrameForDetection(true, true);
        }
      } catch {
        // Ignore transient frame errors
      } finally {
        if (saveSnapshot) {
          snapshotInFlightRef.current = false;
          setIsCapturingSnapshot(false);
        } else {
          inFlightRef.current = false;
        }
      }
    },
    [
      confThreshold,
      autoTriggerEsp32,
      autoSaveOnThreat,
      drawOverlay,
      onTelemetryUpdate,
      onSnapshotSaved,
    ]
  );

  // Scoped keyboard shortcuts inside Full-Screen Live HUD (top-layer safe)
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (!isOpenRef.current) return;
      const targetTag = (e.target as HTMLElement | null)?.tagName;
      if (targetTag && ['INPUT', 'SELECT', 'TEXTAREA'].includes(targetTag)) return;

      const key = e.key.toLowerCase();
      if (key === 'm') {
        e.preventDefault();
        setMirrorH((prev) => {
          const next = !prev;
          showHudNotice(`HORIZONTAL MIRROR: ${next ? 'ON' : 'OFF'}`);
          fetch('/api/camera/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mirror_h: next }),
          }).catch(() => {});
          return next;
        });
      } else if (key === 'v') {
        e.preventDefault();
        setMirrorV((prev) => {
          const next = !prev;
          showHudNotice(`VERTICAL MIRROR: ${next ? 'ON' : 'OFF'}`);
          fetch('/api/camera/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mirror_v: next }),
          }).catch(() => {});
          return next;
        });
      } else if (key === 'r') {
        e.preventDefault();
        setRotation((prev) => {
          const next = (prev + 90) % 360;
          showHudNotice(`ROTATION: ${next}°`);
          fetch('/api/camera/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rotation: next }),
          }).catch(() => {});
          return next;
        });
      } else if (key === 'f') {
        e.preventDefault();
        setRotation((prev) => {
          const next = (prev + 180) % 360;
          showHudNotice(`FLIP 180: ${next}°`);
          fetch('/api/camera/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rotation: next }),
          }).catch(() => {});
          return next;
        });
      } else if (key === 's') {
        e.preventDefault();
        showHudNotice('CAPTURING SNAPSHOT & RUNNING AI...');
        void sendFrameForDetection(true);
      } else if (key === 'h') {
        e.preventDefault();
        setShowHudOverlay((prev) => {
          const next = !prev;
          showHudNotice(`TACTICAL HUD: ${next ? 'ON' : 'OFF'}`);
          return next;
        });
      } else if (key === 'q') {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose, sendFrameForDetection, showHudNotice]);

  // Continuous live detection loop while HUD is open
  useEffect(() => {
    if (!isOpen) return;
    const interval = window.setInterval(() => {
      void sendFrameForDetection(false);
    }, 320);
    return () => clearInterval(interval);
  }, [isOpen, sendFrameForDetection]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="live-hud-title"
      onClose={onClose}
      className="m-0 h-screen max-h-screen w-screen max-w-none border-none bg-[#05080f] p-0 text-slate-100 open:flex open:flex-col"
    >
      {/* Top Full-Screen Tactical HUD Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 bg-[#090e1a]/95 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-sky-500/40 bg-sky-500/15 text-sky-400">
            <Camera className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2
                id="live-hud-title"
                className="font-mono-tabular text-sm font-bold tracking-wider text-white"
              >
                SENTINEL // FULL-PAGE LIVE AI OPTICAL HUD
              </h2>
              <span className="flex items-center gap-1 rounded border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 font-mono-tabular text-[11px] font-bold text-rose-400">
                <span className="h-2 w-2 animate-ping rounded-full bg-rose-500" />
                LIVE INFERENCE ({inferenceMs} ms)
              </span>
            </div>
            <div className="font-mono-tabular text-xs text-slate-400">
              Dual-Model Offline Cascade (YOLOv11m + COCO Person/Pet Verifier)
            </div>
          </div>
        </div>

        {/* Center Threat Status Banner */}
        <div className="flex items-center gap-3">
          {primaryTarget === 'None' ? (
            <div className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/90 px-4 py-2 font-mono-tabular text-xs font-bold text-slate-300">
              <Activity className="h-4 w-4 text-slate-400" />
              SECTOR CLEAR — SCANNING FIELD OF VIEW
            </div>
          ) : primaryTarget === 'SAFE' ? (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/60 bg-emerald-500/20 px-4 py-2 font-mono-tabular text-xs font-bold text-emerald-300 shadow-[0_0_20px_rgba(16,185,129,0.3)]">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              SAFE ALERT // HUMAN CONFIRMED — 0 DETERRENTS ENGAGED
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-lg border border-rose-500 bg-rose-500/25 px-4 py-2 font-mono-tabular text-xs font-bold text-white shadow-[0_0_25px_rgba(244,63,94,0.45)]">
              <AlertOctagon className="h-4 w-4 text-rose-400 animate-bounce" />
              THREAT LOCK: {primaryTarget} — DEPLOYED: {actionTaken}
            </div>
          )}
        </div>

        {/* Close Full-Screen Button */}
        <button
          type="button"
          onClick={onClose}
          autoFocus
          className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2 font-mono-tabular text-xs font-bold text-slate-200 transition hover:border-rose-500/50 hover:bg-rose-500/20 hover:text-white cursor-pointer"
        >
          <X className="h-4 w-4" />
          EXIT FULLSCREEN (ESC)
        </button>
      </div>

      {/* Main Optical Viewport */}
      <div className="relative flex flex-1 items-center justify-center overflow-hidden bg-black">
        <img
          ref={videoRef}
          alt="Jetson CSI Live Stream"
          onError={() => {
            if (!isOpenRef.current) return;
            if (retryTimerRef.current !== null) {
              window.clearTimeout(retryTimerRef.current);
            }
            retryTimerRef.current = window.setTimeout(() => {
              retryTimerRef.current = null;
              if (isOpenRef.current && videoRef.current) {
                videoRef.current.src = `/api/camera/stream?t=${Date.now()}`;
              }
            }, 800);
          }}
          className="h-full w-full object-contain"
        />
        <canvas
          ref={overlayCanvasRef}
          style={{ display: showHudOverlay ? 'block' : 'none' }}
          className="pointer-events-none absolute inset-0 h-full w-full"
        />

        {/* In-Dialog HUD Keyboard Notice & Legend (Top-Layer Safe) */}
        {hudNotice && (
          <div
            role="status"
            aria-live="polite"
            className="pointer-events-none absolute bottom-16 left-1/2 -translate-x-1/2 rounded-lg border border-sky-400/60 bg-[#090e1a]/95 px-4 py-2 font-mono-tabular text-xs font-bold text-sky-300 shadow-[0_0_20px_rgba(56,189,248,0.3)]"
          >
            {hudNotice}
          </div>
        )}
        <div className="pointer-events-none absolute bottom-3 left-1/2 flex -translate-x-1/2 flex-wrap items-center gap-3 rounded-full border border-sky-400/30 bg-[#090e1a]/90 px-4 py-1.5 font-mono-tabular text-[11px] font-bold text-slate-300 backdrop-blur-md">
          <span>
            <b className="text-sky-400">[M]</b> Mirror:{' '}
            <span className={mirrorH ? 'text-emerald-400' : 'text-slate-400'}>
              {mirrorH ? 'ON' : 'OFF'}
            </span>
          </span>
          <span>
            <b className="text-sky-400">[V]</b> Flip-V:{' '}
            <span className={mirrorV ? 'text-emerald-400' : 'text-slate-400'}>
              {mirrorV ? 'ON' : 'OFF'}
            </span>
          </span>
          <span>
            <b className="text-sky-400">[R]</b> Rot: {rotation}°
          </span>
          <span>
            <b className="text-sky-400">[F]</b> Flip 180
          </span>
          <span>
            <b className="text-sky-400">[S]</b> Snap
          </span>
          <span>
            <b className="text-sky-400">[H]</b> HUD:{' '}
            <span className={showHudOverlay ? 'text-emerald-400' : 'text-slate-400'}>
              {showHudOverlay ? 'ON' : 'OFF'}
            </span>
          </span>
          <span>
            <b className="text-rose-400">[Esc/Q]</b> Close
          </span>
        </div>

        {cameraError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950/90 p-6 text-center">
            <AlertOctagon className="mb-3 h-10 w-10 text-rose-400" />
            <div className="font-mono-tabular text-sm font-bold text-white">{cameraError}</div>
            <button
              type="button"
              onClick={() => void startCameraStream()}
              className="mt-4 flex items-center gap-2 rounded-lg bg-sky-500 px-4 py-2 font-mono-tabular text-xs font-bold text-slate-950 cursor-pointer"
            >
              <RefreshCw className="h-4 w-4" />
              RETRY CAMERA INITIALIZATION
            </button>
          </div>
        )}

        {/* Snapshot Confirmation Toast */}
        {snapshotToast && (
          <div className="absolute top-5 right-6 flex items-center gap-2 rounded-lg border border-emerald-500/60 bg-slate-950/95 px-4 py-2.5 font-mono-tabular text-xs font-bold text-emerald-300 shadow-2xl">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            {snapshotToast}
          </div>
        )}

        {/* Live Bounding Box Counter Overlay (Top Left) */}
        <div className="absolute top-4 left-6 flex flex-col gap-1.5 rounded-lg border border-slate-800/90 bg-slate-950/85 p-3 backdrop-blur-md">
          <div className="font-mono-tabular text-[11px] font-bold uppercase tracking-wider text-slate-400">
            ACTIVE OPTICAL TARGETS ({detections.length})
          </div>
          {detections.length === 0 ? (
            <div className="font-mono-tabular text-xs text-slate-500">No targets in frame</div>
          ) : (
            <div className="space-y-1">
              {detections.map((d, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between gap-4 font-mono-tabular text-xs"
                >
                  <span
                    className={
                      d.class_id === 2
                        ? 'font-bold text-rose-400'
                        : d.class_id === 1
                        ? 'font-bold text-amber-400'
                        : d.class_id === 0
                        ? 'font-bold text-sky-400'
                        : 'font-bold text-emerald-400'
                    }
                  >
                    {d.display_label}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Bottom Tactical Control Deck */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-800 bg-[#090e1a] px-6 py-3.5">
        {/* Left: Sensitivity & Automation Toggles */}
        <div className="flex flex-wrap items-center gap-4">

          <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/90 px-3 py-1.5">
            <span className="font-mono-tabular text-xs text-slate-400">CONFIDENCE:</span>
            <input
              type="range"
              min="0.50"
              max="0.90"
              step="0.05"
              value={confThreshold}
              onChange={(e) => setConfThreshold(parseFloat(e.target.value))}
              className="h-1.5 w-24 accent-sky-400 cursor-pointer"
            />
            <span className="font-mono-tabular text-xs font-bold text-sky-400">
              {Math.round(confThreshold * 100)}%
            </span>
          </div>

          <label className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/90 px-3 py-1.5 font-mono-tabular text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={autoSaveOnThreat}
              onChange={(e) => setAutoSaveOnThreat(e.target.checked)}
              className="accent-sky-400"
            />
            AUTO-SAVE SNAPSHOT ON THREAT
          </label>

          <label className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/90 px-3 py-1.5 font-mono-tabular text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={autoTriggerEsp32}
              onChange={(e) => setAutoTriggerEsp32(e.target.checked)}
              className="accent-sky-400"
            />
            AUTO-ENGAGE ESP32 DETERRENTS
          </label>
        </div>

        {/* Center: Save Picture & Run AI Detection Button (Requirement #1) */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => sendFrameForDetection(true)}
            disabled={isCapturingSnapshot}
            className="flex items-center gap-2.5 rounded-lg border border-emerald-400/50 bg-emerald-500 px-6 py-2.5 font-mono-tabular text-xs font-bold uppercase tracking-wider text-slate-950 shadow-[0_0_25px_rgba(16,185,129,0.35)] transition hover:bg-emerald-400 disabled:opacity-50 cursor-pointer"
          >
            <Aperture className="h-4 w-4" />
            <span>
              {isCapturingSnapshot
                ? 'SAVING & ANALYZING...'
                : 'SAVE PICTURE & RUN AI DETECTION'}
            </span>
          </button>
        </div>

        {/* Right: Active Hardware Deterrent Indicators + Stop */}
        <div className="flex items-center gap-2.5">
          <span
            className={`inline-flex items-center gap-1 rounded px-2.5 py-1 font-mono-tabular text-xs font-bold ${
              telemetry.active_actuators.includes('SOUND')
                ? 'bg-rose-500/25 text-rose-300 border border-rose-500/50'
                : 'bg-slate-900 text-slate-500 border border-slate-800'
            }`}
          >
            <Volume2 className="h-3.5 w-3.5" />
            SOUND
          </span>
          <span
            className={`inline-flex items-center gap-1 rounded px-2.5 py-1 font-mono-tabular text-xs font-bold ${
              telemetry.active_actuators.includes('WATER')
                ? 'bg-sky-500/25 text-sky-300 border border-sky-500/50'
                : 'bg-slate-900 text-slate-500 border border-slate-800'
            }`}
          >
            <Droplets className="h-3.5 w-3.5" />
            WATER
          </span>
          <span
            className={`inline-flex items-center gap-1 rounded px-2.5 py-1 font-mono-tabular text-xs font-bold ${
              telemetry.active_actuators.includes('LIGHT')
                ? 'bg-amber-500/25 text-amber-300 border border-amber-500/50'
                : 'bg-slate-900 text-slate-500 border border-slate-800'
            }`}
          >
            <Zap className="h-3.5 w-3.5" />
            LIGHT
          </span>

          <button
            type="button"
            onClick={onStopAll}
            className="flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-1.5 font-mono-tabular text-xs font-bold text-rose-300 transition hover:bg-rose-500 hover:text-white cursor-pointer"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
            SILENCE
          </button>
        </div>
      </div>
    </dialog>
  );
};
