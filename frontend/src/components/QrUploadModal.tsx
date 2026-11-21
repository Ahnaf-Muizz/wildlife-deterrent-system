import React, { useEffect, useId, useRef, useState } from 'react';
import {
  QrCode,
  X,
  Upload,
  Loader2,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Trash2,
  Smartphone,
  Wifi,
  ArrowRight,
  Lock,
} from 'lucide-react';
import { DeterrentEventRecord, QrQueueSnapshot } from '../types/sentinel';

interface QrUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  queueSnapshot: QrQueueSnapshot;
  onEnqueueFiles: (files: FileList | File[], uploader?: string) => Promise<void>;
  onClearCompleted: () => Promise<void>;
  onSelectEvent: (ev: DeterrentEventRecord) => void;
}

type QrStepMode = 'both' | 'step1' | 'step2';

export const QrUploadModal: React.FC<QrUploadModalProps> = ({
  isOpen,
  onClose,
  queueSnapshot,
  onEnqueueFiles,
  onClearCompleted,
  onSelectEvent,
}) => {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const titleId = useId();
  const multiInputId = useId();

  const [qrStepMode, setQrStepMode] = useState<QrStepMode>('both');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Open/close native <dialog> via showModal() / close() per modern-web-guidance
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [isOpen]);

  // Mandatory fallback for browsers without native dialog closedby="any" support
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const handleClose = () => {
      onClose();
    };
    dialog.addEventListener('close', handleClose);

    let cleanupFallback: (() => void) | undefined;
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
      const handlePointerDown = (event: PointerEvent) => {
        pressedOutside = isOutside(event);
      };
      const handlePointerUp = (event: PointerEvent) => {
        if (pressedOutside && isOutside(event)) {
          dialog.close();
        }
        pressedOutside = false;
      };
      dialog.addEventListener('pointerdown', handlePointerDown);
      dialog.addEventListener('pointerup', handlePointerUp);
      cleanupFallback = () => {
        dialog.removeEventListener('pointerdown', handlePointerDown);
        dialog.removeEventListener('pointerup', handlePointerUp);
      };
    }

    return () => {
      dialog.removeEventListener('close', handleClose);
      if (cleanupFallback) cleanupFallback();
    };
  }, [onClose]);

  const activeIp = queueSnapshot.network.ips[0] || '192.168.4.2';
  const targetUrl = `http://${activeIp}:${queueSnapshot.network.port || 5002}/qr-upload`;
  const wifiSsid = queueSnapshot.network.wifi_ssid || 'Wildlife-Deterrent-System-AP';
  const wifiPassword = queueSnapshot.network.wifi_password || 'haustein26';

  const wifiQrSvgUrl = `/api/qr/svg?type=wifi&ssid=${encodeURIComponent(
    wifiSsid
  )}&password=${encodeURIComponent(wifiPassword)}`;
  const portalQrSvgUrl = `/api/qr/svg?url=${encodeURIComponent(targetUrl)}`;

  const handleFilesSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      await onEnqueueFiles(files, 'Dashboard Queue');
      e.target.value = '';
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : 'Failed to enqueue files');
    } finally {
      setIsUploading(false);
    }
  };

  const singleSizePx = 320;
  const bothSizePx = 232;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      {...({ closedby: 'any' } as Record<string, string>)}
      className="m-auto w-[96vw] max-w-6xl rounded-2xl border border-slate-700/90 bg-[#0b101b] p-0 text-slate-100 shadow-2xl"
    >
      {/* Modal Header */}
      <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-sky-500/40 bg-sky-500/15 text-sky-400">
            <QrCode className="h-5 w-5" />
          </div>
          <div>
            <h2
              id={titleId}
              className="font-mono-tabular text-sm font-bold uppercase tracking-wider text-white"
            >
              2-Step QR Onboarding: Join ESP32 Wi-Fi &rarr; Open Upload Portal
            </h2>
            <p className="font-mono-tabular text-[11px] text-slate-400">
              First scan joins the ESP32 local Wi-Fi network, second scan opens the automatic AI upload portal
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onClose}
          autoFocus
          aria-label="Close QR upload modal"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-slate-300 transition hover:border-slate-500 hover:text-white cursor-pointer"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Modal Body: Left 2-Step QR Onboarding (7 cols) + Right Live Queue Column (5 cols) */}
      <div className="grid grid-cols-1 gap-5 p-6 md:grid-cols-12">
        {/* Left: Guided 2-Step QR Codes (7 cols) */}
        <div className="flex flex-col rounded-xl border border-slate-800 bg-[#070a12] p-4 md:col-span-7">
          <div className="flex h-full flex-col">
            {/* Top Step View Tabs */}
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="grid w-full grid-cols-3 gap-1 rounded-lg border border-slate-800 bg-[#0b101b] p-1">
                <button
                  type="button"
                  onClick={() => setQrStepMode('both')}
                  className={`rounded-md px-2 py-1 font-mono-tabular text-[10px] font-bold transition cursor-pointer ${
                    qrStepMode === 'both'
                      ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  BOTH STEPS
                </button>
                <button
                  type="button"
                  onClick={() => setQrStepMode('step1')}
                  className={`rounded-md px-2 py-1 font-mono-tabular text-[10px] font-bold transition cursor-pointer ${
                    qrStepMode === 'step1'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  STEP 1: JOIN WI-FI
                </button>
                <button
                  type="button"
                  onClick={() => setQrStepMode('step2')}
                  className={`rounded-md px-2 py-1 font-mono-tabular text-[10px] font-bold transition cursor-pointer ${
                    qrStepMode === 'step2'
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  STEP 2: OPEN PORTAL
                </button>
              </div>
            </div>

            {/* Warn operator if host PC is not connected to the ESP32 AP (without exposing IP or credentials) */}
            {queueSnapshot.network.on_esp32_ap === false && (
              <div
                role="status"
                className="mb-3 flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 font-mono-tabular text-[11px] text-amber-200"
              >
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                <span>
                  Host PC is not on the ESP32 Wi-Fi network — connect this host to ESP32 Wi-Fi before scanning Step 2 on a phone.
                </span>
              </div>
            )}

            {/* Dual / Focused QR Cards */}
            <div
              className={`my-auto grid w-full gap-3 ${
                qrStepMode === 'both' ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1'
              }`}
            >
              {/* STEP 1 QR: Join ESP32 SoftAP Wi-Fi */}
              {(qrStepMode === 'both' || qrStepMode === 'step1') && (
                <div className="flex flex-col items-center rounded-xl border border-emerald-500/35 bg-[#0b1220] p-3 text-center">
                  <div className="mb-1.5 flex w-full items-center justify-between">
                    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-emerald-300">
                      <Wifi className="h-3 w-3" />
                      STEP 1 • JOIN WI-FI
                    </span>
                    <Lock className="h-3 w-3 text-emerald-400" />
                  </div>

                  <p className="mb-2 font-mono-tabular text-[10px] text-slate-300">
                    1. Scan with phone camera to join the ESP32 Wi-Fi network
                  </p>

                  <div className="flex items-center justify-center rounded-xl border-4 border-white bg-white p-2.5 shadow-[0_0_24px_rgba(16,185,129,0.2)]">
                    <img
                      src={wifiQrSvgUrl}
                      alt={`Step 1 Wi-Fi QR for ${wifiSsid}`}
                      width={qrStepMode === 'step1' ? singleSizePx : bothSizePx}
                      height={qrStepMode === 'step1' ? singleSizePx : bothSizePx}
                      className="block h-auto max-w-full select-none"
                    />
                  </div>
                </div>
              )}

              {/* STEP 2 QR: Open Upload Portal */}
              {(qrStepMode === 'both' || qrStepMode === 'step2') && (
                <div className="flex flex-col items-center rounded-xl border border-sky-500/35 bg-[#0b1220] p-3 text-center">
                  <div className="mb-1.5 flex w-full items-center justify-between">
                    <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
                      <Smartphone className="h-3 w-3" />
                      STEP 2 • UPLOAD PORTAL
                    </span>
                    <ArrowRight className="h-3 w-3 text-sky-400" />
                  </div>

                  <p className="mb-2 font-mono-tabular text-[10px] text-slate-300">
                    2. Once connected to Wi-Fi, scan to open the upload portal
                  </p>

                  <div className="flex items-center justify-center rounded-xl border-4 border-white bg-white p-2.5 shadow-[0_0_24px_rgba(56,189,248,0.2)]">
                    <img
                      src={portalQrSvgUrl}
                      alt={`Step 2 Upload Portal QR for ${targetUrl}`}
                      width={qrStepMode === 'step2' ? singleSizePx : bothSizePx}
                      height={qrStepMode === 'step2' ? singleSizePx : bothSizePx}
                      className="block h-auto max-w-full select-none"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Multi-File Queue Uploader & Live Queue Monitor (5 cols) */}
        <div className="flex flex-col justify-between rounded-xl border border-slate-800 bg-[#070a12] p-5 md:col-span-5">
          <div>
            {/* Queue Summary Counters */}
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <span className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-white">
                  LIVE FIFO SCAN QUEUE
                </span>
                {queueSnapshot.active_count > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {queueSnapshot.active_count} ACTIVE
                  </span>
                )}
              </div>

              <div className="flex items-center gap-3 font-mono-tabular text-[11px]">
                <span className="text-amber-300">
                  QUEUED: <strong>{queueSnapshot.queued_count}</strong>
                </span>
                <span className="text-sky-300">
                  SCANNING: <strong>{queueSnapshot.processing_count}</strong>
                </span>
                <span className="text-emerald-300">
                  DONE: <strong>{queueSnapshot.completed_count}</strong>
                </span>
                {queueSnapshot.completed_count + queueSnapshot.failed_count > 0 && (
                  <button
                    type="button"
                    onClick={onClearCompleted}
                    className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-300 transition hover:border-rose-500/50 hover:text-rose-300 cursor-pointer"
                  >
                    <Trash2 className="h-3 w-3" />
                    CLEAR DONE
                  </button>
                )}
              </div>
            </div>

            {/* Direct Multi-File Enqueue Form */}
            <form
              action="/api/qr/enqueue"
              method="POST"
              encType="multipart/form-data"
              onSubmit={(e) => e.preventDefault()}
              className="mb-4"
            >
              <input
                id={multiInputId}
                name="files"
                type="file"
                multiple
                accept="image/jpeg,image/png,image/webp,image/bmp,image/gif,video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska,video/x-m4v,video/3gpp,application/zip,.jpg,.jpeg,.png,.webp,.bmp,.jfif,.mp4,.mov,.avi,.webm,.mkv,.m4v,.3gp,.zip"
                onChange={handleFilesSelected}
                className="visually-hidden"
              />
              <label
                htmlFor={multiInputId}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-sky-500/40 bg-sky-500/10 px-4 py-3 font-mono-tabular text-xs font-bold text-sky-300 transition hover:border-sky-400 hover:bg-sky-500/20 cursor-pointer"
              >
                {isUploading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>ENQUEUING MEDIA FILES...</span>
                  </>
                ) : (
                  <>
                    <Upload className="h-4 w-4" />
                    <span>ADD MULTIPLE PICTURES / VIDEOS TO AUTO-SCAN QUEUE</span>
                  </>
                )}
              </label>
            </form>

            {uploadError && (
              <div
                role="alert"
                className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 font-mono-tabular text-xs text-rose-300"
              >
                {uploadError}
              </div>
            )}

            {/* Queue Items List */}
            <div className="max-h-[290px] space-y-2 overflow-y-auto pr-1">
              {queueSnapshot.jobs.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-xl border border-slate-800/80 bg-[#0b101b] py-10 text-center">
                  <QrCode className="mb-2 h-7 w-7 text-slate-500" />
                  <p className="font-mono-tabular text-xs font-semibold text-slate-300">
                    Queue Idle — Waiting for Mobile QR or Batch Uploads
                  </p>
                  <p className="mt-1 max-w-xs font-mono-tabular text-[11px] text-slate-400">
                    Multiple users can upload photos or videos simultaneously. Every file is queued and automatically scanned in order.
                  </p>
                </div>
              ) : (
                queueSnapshot.jobs.map((job) => {
                  const ev = job.event;
                  const rowContent = (
                    <>
                      <div className="flex min-w-0 items-center gap-3">
                        {ev ? (
                          <img
                            src={ev.thumbnail_url}
                            alt={job.original_name}
                            className="h-11 w-14 shrink-0 rounded border border-slate-700 object-cover"
                          />
                        ) : (
                          <div className="flex h-11 w-14 shrink-0 items-center justify-center rounded border border-slate-800 bg-slate-900">
                            {job.status === 'processing' ? (
                              <Loader2 className="h-4 w-4 animate-spin text-sky-400" />
                            ) : job.status === 'queued' ? (
                              <Clock className="h-4 w-4 text-amber-400" />
                            ) : (
                              <AlertTriangle className="h-4 w-4 text-rose-400" />
                            )}
                          </div>
                        )}

                        <div className="min-w-0 text-left">
                          <div className="truncate font-mono-tabular text-xs font-bold text-white">
                            {job.original_name}
                          </div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-2 font-mono-tabular text-[10px] text-slate-400">
                            <span>{job.uploader}</span>
                            <span>•</span>
                            <span>{job.file_size_kb.toFixed(1)} KB</span>
                            {ev && (
                              <>
                                <span>•</span>
                                <span className="font-bold text-sky-300">
                                  #{ev.id} ({Math.round(ev.confidence * 100)}%)
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="shrink-0 text-right">
                        {job.status === 'queued' && (
                          <span className="inline-flex items-center gap-1 rounded bg-amber-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-amber-300">
                            <Clock className="h-3 w-3" />
                            QUEUED #{job.position}
                          </span>
                        )}
                        {job.status === 'processing' && (
                          <span className="inline-flex items-center gap-1 rounded bg-sky-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            SCANNING...
                          </span>
                        )}
                        {job.status === 'completed' && ev && (
                          <span
                            className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono-tabular text-[10px] font-bold ${
                              ev.primary_target === 'LARGE MAMMAL'
                                ? 'bg-rose-500/20 text-rose-300'
                                : ev.primary_target === 'SMALL MAMMAL'
                                ? 'bg-amber-500/20 text-amber-300'
                                : ev.primary_target === 'BIRD'
                                ? 'bg-sky-500/20 text-sky-300'
                                : 'bg-emerald-500/20 text-emerald-300'
                            }`}
                          >
                            <CheckCircle2 className="h-3 w-3" />
                            {ev.primary_target === 'None' ? 'CLEAR' : ev.primary_target}
                          </span>
                        )}
                        {job.status === 'failed' && (
                          <span className="inline-flex items-center gap-1 rounded bg-rose-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-rose-300">
                            FAILED
                          </span>
                        )}
                      </div>
                    </>
                  );

                  if (ev) {
                    return (
                      <button
                        key={job.job_id}
                        type="button"
                        onClick={() => {
                          onSelectEvent(ev);
                          onClose();
                        }}
                        className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-800 bg-[#0b101b] p-2.5 text-left transition hover:border-sky-500/40 cursor-pointer"
                      >
                        {rowContent}
                      </button>
                    );
                  }

                  return (
                    <div
                      key={job.job_id}
                      className={`flex items-center justify-between gap-3 rounded-lg border p-2.5 transition ${
                        job.status === 'processing'
                          ? 'border-sky-500/50 bg-sky-500/10'
                          : job.status === 'queued'
                          ? 'border-amber-500/40 bg-amber-500/5'
                          : 'border-rose-500/40 bg-rose-500/10'
                      }`}
                    >
                      {rowContent}
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between border-t border-slate-800/80 pt-3 font-mono-tabular text-[11px] text-slate-400">
            <span>Completed scans automatically save to Dashboard History</span>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-bold text-slate-200 transition hover:bg-slate-800 cursor-pointer"
            >
              DONE
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
};
