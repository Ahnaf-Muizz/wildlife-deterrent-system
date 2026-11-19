import React, { useEffect, useId, useRef, useState } from 'react';
import {
  QrCode,
  X,
  Copy,
  Check,
  ExternalLink,
  Upload,
  Loader2,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Trash2,
  Smartphone,
  Wifi,
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
  const hostInputId = useId();

  const [selectedIp, setSelectedIp] = useState<string>('');
  const [copied, setCopied] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedIp && queueSnapshot.network.ips.length > 0) {
      setSelectedIp(queueSnapshot.network.ips[0]);
    }
  }, [queueSnapshot.network.ips, selectedIp]);

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
      const handleBackdropClick = (event: MouseEvent) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;
        if (isDialogContent) return;
        dialog.close();
      };
      dialog.addEventListener('click', handleBackdropClick);
      cleanupFallback = () => dialog.removeEventListener('click', handleBackdropClick);
    }

    return () => {
      dialog.removeEventListener('close', handleClose);
      if (cleanupFallback) cleanupFallback();
    };
  }, [onClose]);

  const activeIp = selectedIp || queueSnapshot.network.ips[0] || '192.168.4.2';
  const targetUrl = `http://${activeIp}:${queueSnapshot.network.port || 5002}/qr-upload`;
  const qrSvgUrl = `/api/qr/svg?url=${encodeURIComponent(targetUrl)}`;

  const handleCopyUrl = async () => {
    try {
      await navigator.clipboard.writeText(targetUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

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

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      {...({ closedby: 'any' } as Record<string, string>)}
      className="m-auto w-full max-w-4xl rounded-2xl border border-slate-700/90 bg-[#0b101b] p-0 text-slate-100 shadow-2xl"
    >
      {/* Modal Header */}
      <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-sky-500/40 bg-sky-500/15 text-sky-400">
            <QrCode className="h-5 w-5" />
          </div>
          <div>
            <h2 id={titleId} className="font-mono-tabular text-sm font-bold uppercase tracking-wider text-white">
              QR Mobile Upload & Automatic Scan Queue
            </h2>
            <p className="font-mono-tabular text-[11px] text-slate-400">
              Scan with any phone camera to upload pictures or videos directly into the AI scan queue
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

      {/* Modal Body: Left QR Code Column + Right Live Queue Column */}
      <div className="grid grid-cols-1 gap-6 p-6 md:grid-cols-12">
        {/* Left: Scannable QR Code & Network Link (5 cols) */}
        <div className="flex flex-col items-center justify-between rounded-xl border border-slate-800 bg-[#070a12] p-5 md:col-span-5">
          <div className="flex w-full items-center justify-between">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 font-mono-tabular text-[10px] font-bold text-emerald-300">
              <Smartphone className="h-3 w-3" />
              PHONE CAMERA READY
            </span>
            <span className="font-mono-tabular text-[10px] text-slate-400">
              100% OFFLINE QR
            </span>
          </div>

          {/* Crisp SVG QR Code Frame */}
          <div className="my-4 flex items-center justify-center rounded-xl border-4 border-white bg-white p-2 shadow-[0_0_30px_rgba(56,189,248,0.18)]">
            <img
              src={qrSvgUrl}
              alt={`QR Code for ${targetUrl}`}
              width={230}
              height={230}
              className="h-[230px] w-[230px] select-none"
            />
          </div>

          {/* Network Host Selector */}
          <div className="w-full space-y-2.5">
            {queueSnapshot.network.ips.length > 1 && (
              <div className="flex flex-wrap gap-1.5">
                {queueSnapshot.network.ips.map((ip) => (
                  <button
                    key={ip}
                    type="button"
                    onClick={() => setSelectedIp(ip)}
                    className={`inline-flex items-center gap-1 rounded px-2 py-1 font-mono-tabular text-[10px] font-bold transition cursor-pointer ${
                      activeIp === ip
                        ? 'border border-sky-400 bg-sky-500/20 text-sky-300'
                        : 'border border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Wifi className="h-2.5 w-2.5" />
                    {ip}
                  </button>
                ))}
              </div>
            )}

            <div>
              <label
                htmlFor={hostInputId}
                className="mb-1 block font-mono-tabular text-[10px] font-semibold uppercase tracking-wider text-slate-400"
              >
                Host IP / Mobile Upload URL
              </label>
              <div className="flex items-center gap-1.5">
                <input
                  id={hostInputId}
                  name="host_ip"
                  type="text"
                  value={activeIp}
                  onChange={(e) => setSelectedIp(e.target.value.trim())}
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  className="w-28 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono-tabular text-xs text-sky-300 focus:border-sky-400 focus:outline-none"
                />
                <div className="flex-1 truncate rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 font-mono-tabular text-[11px] text-slate-300">
                  {targetUrl}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-1">
              <button
                type="button"
                onClick={handleCopyUrl}
                className="flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 py-2 font-mono-tabular text-xs font-bold text-slate-200 transition hover:border-sky-400/50 hover:text-sky-300 cursor-pointer"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? 'COPIED' : 'COPY LINK'}
              </button>

              <a
                href="/qr-upload"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/15 py-2 font-mono-tabular text-xs font-bold text-sky-300 transition hover:bg-sky-500/25"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                OPEN UPLOADER
              </a>
            </div>
          </div>
        </div>

        {/* Right: Multi-File Queue Uploader & Live Queue Monitor (7 cols) */}
        <div className="flex flex-col justify-between rounded-xl border border-slate-800 bg-[#070a12] p-5 md:col-span-7">
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
                accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska,application/zip,.jpg,.jpeg,.png,.webp,.mp4,.mov,.avi,.webm,.mkv,.zip"
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
            <div
              role="status"
              aria-live="polite"
              className="max-h-[270px] space-y-2 overflow-y-auto pr-1"
            >
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
                  return (
                    <div
                      key={job.job_id}
                      onClick={() => {
                        if (ev) {
                          onSelectEvent(ev);
                          onClose();
                        }
                      }}
                      className={`flex items-center justify-between gap-3 rounded-lg border p-2.5 transition ${
                        job.status === 'processing'
                          ? 'border-sky-500/50 bg-sky-500/10'
                          : job.status === 'queued'
                          ? 'border-amber-500/40 bg-amber-500/5'
                          : job.status === 'completed'
                          ? 'border-slate-800 bg-[#0b101b] hover:border-sky-500/40 cursor-pointer'
                          : 'border-rose-500/40 bg-rose-500/10'
                      }`}
                    >
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

                        <div className="min-w-0">
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
