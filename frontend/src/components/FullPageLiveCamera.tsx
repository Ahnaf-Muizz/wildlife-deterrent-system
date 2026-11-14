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
  const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const inFlightRef = useRef<boolean>(false);
  const lastAutoSaveEpochRef = useRef<number>(0);

  const [devices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('');
  const [confThreshold, setConfThreshold] = useState<number>(0.5);
  const [autoSaveOnThreat, setAutoSaveOnThreat] = useState<boolean>(false);
  const [autoTriggerEsp32, setAutoTriggerEsp32] = useState<boolean>(true);
  const [detections, setDetections] = useState<DetectionBox[]>([]);
  const [primaryTarget, setPrimaryTarget] = useState<ThreatCategory>('None');
  const [actionTaken, setActionTaken] = useState<string>('Area Clear — No Deterrents');
  const [inferenceMs, setInferenceMs] = useState<number>(0);
  const [isCapturingSnapshot, setIsCapturingSnapshot] = useState<boolean>(false);
  const [snapshotToast, setSnapshotToast] = useState<string | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);

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
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.removeAttribute('src');
      videoRef.current.src = '';
    }
  }, []);

  const startCameraStream = useCallback(
    async (_deviceId?: string) => {
      setCameraError(null);
      if (videoRef.current) {
        videoRef.current.src = `/api/camera/stream?t=${Date.now()}`;
      }
    },
    []
  );

  useEffect(() => {
    if (isOpen) {
      startCameraStream(selectedDeviceId || undefined);
    } else {
      stopCameraStream();
      setDetections([]);
      setPrimaryTarget('None');
    }
    return () => {
      stopCameraStream();
    };
  }, [isOpen, selectedDeviceId, startCameraStream, stopCameraStream]);

  // Draw tactical bounding boxes & telemetry labels onto the live full-screen <canvas>
  const drawOverlay = useCallback((boxes: DetectionBox[]) => {
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

    for (const det of boxes) {
      const [nx1, ny1, nx2, ny2] = det.bbox_norm;
      const x1 = offsetX + nx1 * drawnW;
      const y1 = offsetY + ny1 * drawnH;
      const x2 = offsetX + nx2 * drawnW;
      const y2 = offsetY + ny2 * drawnH;
      const bw = x2 - x1;
      const bh = y2 - y1;

      const palette = colorMap[det.class_id] || colorMap[0];

      // Subtle translucent box tint
      ctx.fillStyle = `${palette.stroke}18`;
      ctx.fillRect(x1, y1, bw, bh);

      // Main hairline box
      ctx.strokeStyle = palette.stroke;
      ctx.lineWidth = 2;
      ctx.strokeRect(x1, y1, bw, bh);

      // Corner tactical brackets
      const cLen = Math.max(12, Math.min(28, Math.min(bw, bh) * 0.22));
      ctx.lineWidth = 4;
      ctx.beginPath();
      // Top-left
      ctx.moveTo(x1, y1 + cLen);
      ctx.lineTo(x1, y1);
      ctx.lineTo(x1 + cLen, y1);
      // Top-right
      ctx.moveTo(x2 - cLen, y1);
      ctx.lineTo(x2, y1);
      ctx.lineTo(x2, y1 + cLen);
      // Bottom-left
      ctx.moveTo(x1, y2 - cLen);
      ctx.lineTo(x1, y2);
      ctx.lineTo(x1 + cLen, y2);
      // Bottom-right
      ctx.moveTo(x2 - cLen, y2);
      ctx.lineTo(x2, y2);
      ctx.lineTo(x2, y2 - cLen);
      ctx.stroke();

      // Label badge
      const label = det.display_label;
      ctx.font = 'bold 13px "JetBrains Mono", Consolas, monospace';
      const textWidth = ctx.measureText(label).width;
      const padX = 10;
      const badgeH = 26;
      const badgeY = Math.max(4, y1 - badgeH);

      ctx.fillStyle = palette.fill;
      ctx.fillRect(x1, badgeY, textWidth + padX * 2, badgeH);

      ctx.fillStyle = palette.text;
      ctx.fillText(label, x1 + padX, badgeY + 17);
    }
  }, []);

  // Send frame to backend /api/live/detect
  const sendFrameForDetection = useCallback(
    async (saveSnapshot = false) => {
      const video = videoRef.current;
      if (!video) return;
      if (!saveSnapshot && inFlightRef.current) return;

      inFlightRef.current = true;
      if (saveSnapshot) {
        setIsCapturingSnapshot(true);
      }

      try {
        const formData = new FormData();
        formData.append('use_csi', 'true');
        formData.append('conf', String(confThreshold));
        formData.append('auto_trigger', String(autoTriggerEsp32));

        // Check if auto-save on threat should fire (with 6s cooldown)
        const shouldSave = saveSnapshot;
        formData.append('save_snapshot', String(shouldSave));

        const res = await fetch('/api/live/detect', {
          method: 'POST',
          body: formData,
        });
        if (!res.ok) return;

        const data: LiveDetectResponse = await res.json();
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
          setTimeout(() => setSnapshotToast(null), 3500);
        } else if (
          autoSaveOnThreat &&
          data.primary_target !== 'None' &&
          data.primary_target !== 'SAFE' &&
          Date.now() - lastAutoSaveEpochRef.current > 6500
        ) {
          lastAutoSaveEpochRef.current = Date.now();
          // Trigger an immediate snapshot save for this threat
          sendFrameForDetection(true);
        }
      } catch {
        // Ignore transient frame errors
      } finally {
        inFlightRef.current = false;
        if (saveSnapshot) {
          setIsCapturingSnapshot(false);
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

  // Continuous live detection loop while HUD is open
  useEffect(() => {
    if (!isOpen) return;
    const interval = window.setInterval(() => {
      sendFrameForDetection(false);
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
            setTimeout(() => {
              if (isOpen && videoRef.current) {
                videoRef.current.src = `/api/camera/stream?t=${Date.now()}`;
              }
            }, 800);
          }}
          className="h-full w-full object-contain"
        />
        <canvas
          ref={overlayCanvasRef}
          className="pointer-events-none absolute inset-0 h-full w-full"
        />
        <canvas ref={captureCanvasRef} className="hidden" />

        {cameraError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950/90 p-6 text-center">
            <AlertOctagon className="mb-3 h-10 w-10 text-rose-400" />
            <div className="font-mono-tabular text-sm font-bold text-white">{cameraError}</div>
            <button
              type="button"
              onClick={() => startCameraStream(selectedDeviceId || undefined)}
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
        {/* Left: Camera Selector & Sensitivity */}
        <div className="flex flex-wrap items-center gap-4">
          {devices.length > 1 && (
            <div className="flex items-center gap-2">
              <span className="font-mono-tabular text-xs text-slate-400">CAMERA:</span>
              <select
                value={selectedDeviceId}
                onChange={(e) => setSelectedDeviceId(e.target.value)}
                className="rounded border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono-tabular text-xs text-white"
              >
                {devices.map((dev, i) => (
                  <option key={dev.deviceId || i} value={dev.deviceId}>
                    {dev.label || `Camera ${i + 1}`}
                  </option>
                ))}
              </select>
            </div>
          )}

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
