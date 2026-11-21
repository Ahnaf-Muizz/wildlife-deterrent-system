import React, { useEffect, useRef, useState } from 'react';
import {
  X,
  ShieldCheck,
  AlertTriangle,
  Volume2,
  Droplets,
  Zap,
  Clock,
  Trash2,
  Film,
  Target,
} from 'lucide-react';
import { DeterrentEventRecord, DeterrentTelemetry, ThreatCategory } from '../types/sentinel';
import { notificationService } from '../services/notificationService';

interface EventDetailModalProps {
  event: DeterrentEventRecord | null;
  autoSyncHardware?: boolean;
  onTelemetryUpdate?: (t: DeterrentTelemetry) => void;
  onClose: () => void;
  onDelete: (id: number) => Promise<void>;
}

export const EventDetailModal: React.FC<EventDetailModalProps> = ({
  event,
  autoSyncHardware = false,
  onTelemetryUpdate,
  onClose,
  onDelete,
}) => {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const videoPlayerRef = useRef<HTMLVideoElement | null>(null);
  const lastSyncRef = useRef<{ target: string; time: number }>({ target: 'NONE', time: 0 });
  const [hardwareSyncEnabled, setHardwareSyncEnabled] = useState<boolean>(autoSyncHardware);

  useEffect(() => {
    setHardwareSyncEnabled(Boolean(autoSyncHardware));
    lastSyncRef.current = { target: 'NONE', time: 0 };
  }, [event?.id, autoSyncHardware]);

  // Open/close native <dialog> via showModal() and register light-dismiss fallback per modern-web-guidance
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (event && !dialog.open) {
      dialog.showModal();
    } else if (!event && dialog.open) {
      dialog.close();
    }

    if (!('closedBy' in HTMLDialogElement.prototype)) {
      const isOutside = (e: PointerEvent) => {
        const rect = dialog.getBoundingClientRect();
        return (
          e.clientX < rect.left ||
          e.clientX > rect.right ||
          e.clientY < rect.top ||
          e.clientY > rect.bottom
        );
      };
      let pressedOutside = false;
      const onPointerDown = (e: PointerEvent) => {
        pressedOutside = isOutside(e);
      };
      const onPointerUp = (e: PointerEvent) => {
        if (pressedOutside && isOutside(e)) {
          dialog.close();
        }
        pressedOutside = false;
      };
      dialog.addEventListener('pointerdown', onPointerDown);
      dialog.addEventListener('pointerup', onPointerUp);
      return () => {
        dialog.removeEventListener('pointerdown', onPointerDown);
        dialog.removeEventListener('pointerup', onPointerUp);
      };
    }
  }, [event]);

  const seekVideoTo = (timeSec: number) => {
    if (videoPlayerRef.current) {
      videoPlayerRef.current.currentTime = timeSec;
      videoPlayerRef.current.play().catch(() => {});
    }
  };

  return (
    <dialog
      ref={dialogRef}
      {...({ closedby: 'any' } as React.DialogHTMLAttributes<HTMLDialogElement>)}
      aria-labelledby="event-detail-title"
      onClose={onClose}
      className="m-auto max-h-[90vh] w-[94vw] max-w-6xl overflow-y-auto rounded-2xl border border-slate-700/90 bg-[#0b101b] p-0 text-slate-100 shadow-2xl open:flex open:flex-col"
    >
      {event && (
        <>
          {/* Modal Top Header */}
          <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
            <div className="flex items-center gap-3">
              <Target className="h-5 w-5 text-sky-400" />
              <div>
                <h2
                  id="event-detail-title"
                  className="font-mono-tabular text-sm font-bold uppercase tracking-wider text-white"
                >
                  THREAT ANALYSIS REPORT // EVENT #{event.id}
                </h2>
                <div className="font-mono-tabular text-xs text-slate-400">
                  Logged {event.timestamp} • Media Type: {event.media_type.toUpperCase()}
                </div>
              </div>
            </div>

            <button
              type="button"
              onClick={onClose}
              autoFocus
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-slate-300 transition hover:border-slate-500 hover:text-white cursor-pointer"
              aria-label="Close inspection dialog"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Modal Body */}
          <div className="grid grid-cols-1 gap-6 p-6 lg:grid-cols-3">
            {/* Left 2 Columns: Annotated Picture or Annotated Video Player + Timeline */}
            <div className="flex flex-col gap-4 lg:col-span-2">
              <div className="flex min-h-[380px] items-center justify-center overflow-hidden rounded-xl border border-slate-800 bg-black p-2">
                {event.media_type === 'video' ? (
                  <video
                    ref={videoPlayerRef}
                    src={event.result_url}
                    controls
                    autoPlay
                    muted
                    playsInline
                    onLoadedData={() => {
                      lastSyncRef.current = { target: 'NONE', time: 0 };
                      videoPlayerRef.current?.play().catch(() => {});
                    }}
                    onTimeUpdate={() => {
                      if (!hardwareSyncEnabled) return;
                      const vid = videoPlayerRef.current;
                      if (!vid || vid.paused || vid.ended) return;
                      const cur = vid.currentTime;
                      let activeTarget: ThreatCategory = 'None';
                      let activeConf = event.confidence || 0.85;
                      if (event.timeline && event.timeline.length > 0) {
                        let bestDelta = Infinity;
                        for (let i = 0; i < event.timeline.length; i++) {
                          const delta = Math.abs(event.timeline[i].time_sec - cur);
                          if (delta <= 0.45 && delta < bestDelta) {
                            bestDelta = delta;
                            activeTarget = event.timeline[i].target;
                            activeConf = event.timeline[i].confidence || activeConf;
                          }
                        }
                      } else if (event.primary_target && event.primary_target !== 'None') {
                        activeTarget = event.primary_target;
                      }
                      const nowMs = Date.now();
                      const isThreatOrSafe =
                        activeTarget === 'SAFE' ||
                        activeTarget === 'LARGE MAMMAL' ||
                        activeTarget === 'SMALL MAMMAL' ||
                        activeTarget === 'BIRD';
                      if (
                        isThreatOrSafe &&
                        (lastSyncRef.current.target !== activeTarget || nowMs - lastSyncRef.current.time > 900)
                      ) {
                        lastSyncRef.current = { target: activeTarget, time: nowMs };
                        fetch('/api/deterrent/video_sync', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ target: activeTarget }),
                        })
                          .then((r) => (r.ok ? r.json() : null))
                          .then((res) => {
                            if (!res) return;
                            if (res.telemetry && onTelemetryUpdate) {
                              onTelemetryUpdate(res.telemetry);
                            }
                            if (res.status === 'triggered' && activeTarget !== 'SAFE') {
                              notificationService.notifyDetection(
                                activeTarget,
                                activeConf,
                                res.telemetry?.active_actuators || event.actuators,
                                res.telemetry?.duration_ms || event.sound_duration_ms || 5000,
                                true
                              );
                            }
                          })
                          .catch(() => {});
                      } else if (!isThreatOrSafe && lastSyncRef.current.target !== 'None') {
                        lastSyncRef.current = { target: 'None', time: nowMs };
                      }
                    }}
                    className="max-h-[62vh] w-full rounded-lg object-contain"
                  />
                ) : (
                  <img
                    src={event.result_url}
                    alt={event.primary_target}
                    className="max-h-[62vh] w-full rounded-lg object-contain"
                  />
                )}
              </div>

              {/* Hardware Sync Control & Interactive Video Threat Timeline Markers */}
              {event.media_type === 'video' && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-[#080c14] px-4 py-2.5">
                  <span className="font-mono-tabular text-[11px] text-slate-400">
                    Replay ESP32 Hardware Sync
                  </span>
                  <button
                    type="button"
                    aria-pressed={hardwareSyncEnabled}
                    onClick={() => setHardwareSyncEnabled((prev) => !prev)}
                    className={`rounded-md border px-3 py-1 font-mono-tabular text-[11px] font-bold transition cursor-pointer ${
                      hardwareSyncEnabled
                        ? 'border-emerald-500/50 bg-emerald-500/20 text-emerald-300'
                        : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    LIVE HARDWARE SYNC: {hardwareSyncEnabled ? 'ON' : 'OFF'}
                  </button>
                </div>
              )}

              {event.media_type === 'video' && event.timeline.length > 0 && (
                <div className="rounded-xl border border-slate-800 bg-[#080c14] p-4">
                  <div className="mb-2.5 flex items-center justify-between">
                    <span className="flex items-center gap-1.5 font-mono-tabular text-xs font-bold uppercase tracking-wider text-slate-300">
                      <Film className="h-3.5 w-3.5 text-amber-400" />
                      Annotated Video Threat Timeline (Click Marker to Seek)
                    </span>
                    <span className="font-mono-tabular text-xs text-slate-400">
                      {event.timeline.length} Detection Frames
                    </span>
                  </div>
                  <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto pr-1">
                    {event.timeline.map((m, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => seekVideoTo(m.time_sec)}
                        className={`rounded border px-2.5 py-1 font-mono-tabular text-[11px] font-semibold transition cursor-pointer ${
                          m.target === 'LARGE MAMMAL'
                            ? 'border-rose-500/40 bg-rose-500/15 text-rose-300 hover:bg-rose-500/30'
                            : m.target === 'SMALL MAMMAL'
                            ? 'border-amber-500/40 bg-amber-500/15 text-amber-300 hover:bg-amber-500/30'
                            : m.target === 'BIRD'
                            ? 'border-sky-500/40 bg-sky-500/15 text-sky-300 hover:bg-sky-500/30'
                            : 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/30'
                        }`}
                      >
                        {m.time_sec.toFixed(1)}s • {m.target} ({Math.round(m.confidence * 100)}%)
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Telemetry Breakdown & Bounding Box List */}
            <div className="flex flex-col justify-between gap-4 rounded-xl border border-slate-800 bg-[#080c14] p-5">
              <div className="space-y-4">
                <div>
                  <div className="font-mono-tabular text-[11px] uppercase tracking-wider text-slate-400">
                    Primary Classification
                  </div>
                  <div className="mt-1.5 flex items-center gap-2">
                    {event.primary_target === 'SAFE' || event.primary_target === 'None' ? (
                      <ShieldCheck className="h-5 w-5 text-emerald-400" />
                    ) : (
                      <AlertTriangle className="h-5 w-5 text-rose-400" />
                    )}
                    <span className="font-mono-tabular text-lg font-bold text-white">
                      {event.primary_target === 'SAFE'
                        ? 'SAFE (HUMAN VERIFIED)'
                        : event.primary_target === 'None'
                        ? 'AREA CLEAR'
                        : event.primary_target}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 border-y border-slate-800 py-3">
                  <div>
                    <div className="font-mono-tabular text-[11px] text-slate-400">
                      PEAK CONFIDENCE
                    </div>
                    <div className="font-mono-tabular text-base font-bold text-sky-400">
                      {(event.confidence * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div className="font-mono-tabular text-[11px] text-slate-400">
                      SOUND DURATION
                    </div>
                    <div className="font-mono-tabular text-base font-bold text-rose-400">
                      {event.sound_duration_ms > 0
                        ? `${(event.sound_duration_ms / 1000).toFixed(2)}s`
                        : '0.0s (Silent)'}
                    </div>
                  </div>
                </div>

                {/* Hardware Actuators Engaged */}
                <div>
                  <div className="mb-2 font-mono-tabular text-[11px] uppercase tracking-wider text-slate-400">
                    Hardware Deterrents Engaged
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-[#0d1320] p-3 font-mono-tabular text-xs font-semibold text-slate-200">
                    {event.action_taken}
                  </div>
                  {event.actuators.length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-2">
                      {event.actuators.includes('SOUND') && (
                        <span className="inline-flex items-center gap-1 rounded border border-rose-500/40 bg-rose-500/15 px-2.5 py-1 font-mono-tabular text-xs font-bold text-rose-300">
                          <Volume2 className="h-3.5 w-3.5" />
                          SOUND BUZZER
                        </span>
                      )}
                      {event.actuators.includes('WATER') && (
                        <span className="inline-flex items-center gap-1 rounded border border-sky-500/40 bg-sky-500/15 px-2.5 py-1 font-mono-tabular text-xs font-bold text-sky-300">
                          <Droplets className="h-3.5 w-3.5" />
                          WATER SPRINKLER
                        </span>
                      )}
                      {event.actuators.includes('LIGHT') && (
                        <span className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/15 px-2.5 py-1 font-mono-tabular text-xs font-bold text-amber-300">
                          <Zap className="h-3.5 w-3.5" />
                          FLASHING LIGHT
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Individual Bounding Boxes List */}
                {event.detections.length > 0 && (
                  <div>
                    <div className="mb-2 font-mono-tabular text-[11px] uppercase tracking-wider text-slate-400">
                      Detected Objects ({event.detections.length})
                    </div>
                    <div className="max-h-40 space-y-1.5 overflow-y-auto rounded-lg border border-slate-800 bg-[#0d1320] p-2.5">
                      {event.detections.map((d, i) => (
                        <div
                          key={i}
                          className="flex items-center justify-between border-b border-slate-800/60 pb-1 last:border-none last:pb-0 font-mono-tabular text-xs"
                        >
                          <span className="font-semibold text-slate-200">{d.display_label}</span>
                          <span className="text-[11px] text-slate-400">
                            [{d.bbox.map((v) => Math.round(v)).join(', ')}]
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Technical File Specs */}
                <div className="space-y-1.5 border-t border-slate-800 pt-3 font-mono-tabular text-xs text-slate-400">
                  <div className="flex justify-between">
                    <span>Resolution:</span>
                    <span className="text-slate-200">{event.resolution}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>File Size:</span>
                    <span className="text-slate-200">{event.file_size_kb} KB</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Timestamp:</span>
                    <span className="flex items-center gap-1 text-slate-200">
                      <Clock className="h-3 w-3" />
                      {event.timestamp}
                    </span>
                  </div>
                </div>
              </div>

              {/* Actions Footer */}
              <div className="flex items-center gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={async () => {
                    await onDelete(event.id);
                    onClose();
                  }}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 font-mono-tabular text-xs font-bold text-rose-400 transition hover:bg-rose-500 hover:text-white cursor-pointer"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  DELETE RECORD
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="flex-1 rounded-lg bg-slate-800 py-2.5 font-mono-tabular text-xs font-bold text-white transition hover:bg-slate-700 cursor-pointer"
                >
                  CLOSE REPORT
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </dialog>
  );
};
