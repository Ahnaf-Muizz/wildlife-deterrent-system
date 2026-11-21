import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import {
  Shield,
  Upload,
  Camera,
  Loader2,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ArrowLeft,
  Sparkles,
} from 'lucide-react';
import { QrQueueSnapshot } from '../types/sentinel';

const IMAGE_EXT_RE = /\.(jpe?g|png|webp|bmp|heic|heif|jfif)$/i;

interface EnqueueResponse {
  enqueued_count?: number;
  error?: string;
  queue?: QrQueueSnapshot;
}

function isImageFile(file: File): boolean {
  return file.type.startsWith('image/') || IMAGE_EXT_RE.test(file.name);
}

function prepareFileForUpload(file: File): Promise<File> {
  if (!isImageFile(file)) {
    return Promise.resolve(file);
  }

  return new Promise((resolve) => {
    let settled = false;
    const objectUrl = URL.createObjectURL(file);
    let timerId = 0;

    const finish = (result: File) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timerId);
      URL.revokeObjectURL(objectUrl);
      resolve(result);
    };

    timerId = window.setTimeout(() => finish(file), 2500);
    const img = new Image();

    img.onload = () => {
      try {
        const origW = img.naturalWidth || img.width;
        const origH = img.naturalHeight || img.height;
        if (!origW || !origH) {
          finish(file);
          return;
        }

        const maxDim = 1280;
        const longest = Math.max(origW, origH);
        const scale = longest > maxDim ? maxDim / longest : 1;
        const targetW = Math.max(1, Math.round(origW * scale));
        const targetH = Math.max(1, Math.round(origH * scale));

        if (scale === 1 && file.type === 'image/jpeg' && file.size <= 220 * 1024) {
          finish(file);
          return;
        }

        const canvas = document.createElement('canvas');
        canvas.width = targetW;
        canvas.height = targetH;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          finish(file);
          return;
        }
        ctx.drawImage(img, 0, 0, targetW, targetH);
        canvas.toBlob(
          (blob) => {
            if (!blob) {
              finish(file);
              return;
            }
            if (scale === 1 && blob.size >= file.size && /\.(jpe?g|png|webp)$/i.test(file.name)) {
              finish(file);
              return;
            }
            const baseName = file.name.replace(/\.[^.]+$/, '') || 'capture';
            finish(new File([blob], `${baseName}.jpg`, { type: 'image/jpeg' }));
          },
          'image/jpeg',
          0.82
        );
      } catch {
        finish(file);
      }
    };

    img.onerror = () => finish(file);
    img.src = objectUrl;
  });
}

async function checkServerReachable(): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 1800);
  try {
    const res = await fetch('/api/health', {
      cache: 'no-store',
      signal: controller.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

function uploadSingleFile(
  file: File,
  timeoutMs: number,
  onProgress: (pct: number) => void,
  registerXhr?: (xhr: XMLHttpRequest | null) => void
): Promise<EnqueueResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    registerXhr?.(xhr);
    const formData = new FormData();
    formData.append('files', file, file.name);
    formData.append('conf', '0.50');
    formData.append('uploader', 'Mobile QR Scanner');

    xhr.open('POST', '/api/qr/enqueue', true);
    xhr.timeout = timeoutMs;

    const cleanup = () => {
      registerXhr?.(null);
    };

    xhr.upload.onprogress = (evt) => {
      if (evt.lengthComputable && evt.total > 0) {
        const pct = Math.min(99, Math.round((evt.loaded / evt.total) * 100));
        onProgress(pct);
      }
    };

    xhr.onload = () => {
      cleanup();
      let data: EnqueueResponse = {};
      try {
        data = xhr.responseText ? (JSON.parse(xhr.responseText) as EnqueueResponse) : {};
      } catch {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
        resolve(data);
      } else {
        const err = new Error(data.error || `Upload failed (HTTP ${xhr.status})`) as Error & {
          retryable?: boolean;
        };
        err.retryable = xhr.status >= 500 || xhr.status === 0;
        reject(err);
      }
    };

    xhr.onerror = () => {
      cleanup();
      const err = new Error('Network connection interrupted during upload') as Error & {
        retryable?: boolean;
      };
      err.retryable = true;
      reject(err);
    };

    xhr.ontimeout = () => {
      cleanup();
      const err = new Error('Upload timed out over Wi-Fi') as Error & { retryable?: boolean };
      err.retryable = true;
      reject(err);
    };

    xhr.onabort = () => {
      cleanup();
      reject(new Error('Upload cancelled'));
    };

    xhr.send(formData);
  });
}

async function uploadSingleFileWithRetry(
  file: File,
  onProgress: (pct: number) => void,
  registerXhr: (xhr: XMLHttpRequest | null) => void,
  isCancelled: () => boolean
): Promise<EnqueueResponse> {
  const timeoutMs = isImageFile(file) ? 12000 : 90000;
  try {
    return await uploadSingleFile(file, timeoutMs, onProgress, registerXhr);
  } catch (firstErr: unknown) {
    if (isCancelled()) {
      throw firstErr;
    }
    const retryable =
      typeof firstErr === 'object' &&
      firstErr !== null &&
      'retryable' in firstErr &&
      Boolean((firstErr as { retryable?: boolean }).retryable);
    if (!retryable) {
      throw firstErr;
    }
    const reachable = await checkServerReachable();
    if (!reachable || isCancelled()) {
      throw new Error(
        'Cannot reach Dashboard PC over Wi-Fi. Verify your phone is connected to Wildlife-Deterrent-System-AP and tap Upload again.'
      );
    }
    await new Promise((r) => window.setTimeout(r, 400));
    return await uploadSingleFile(file, timeoutMs, onProgress, registerXhr);
  }
}

const EMPTY_SNAPSHOT: QrQueueSnapshot = {
  queued_count: 0,
  processing_count: 0,
  active_count: 0,
  completed_count: 0,
  failed_count: 0,
  jobs: [],
  network: {
    ips: ['192.168.4.2'],
    port: 5002,
    primary_url: 'http://192.168.4.2:5002/mobile-upload',
    urls: ['http://192.168.4.2:5002/mobile-upload'],
  },
};

export const MobileQrUploadPage: React.FC = () => {
  const galleryInputId = useId();
  const cameraInputId = useId();
  const formHeadingId = useId();

  const isMountedRef = useRef(true);
  const isUploadingRef = useRef(false);
  const isPollingRef = useRef(false);
  const cancelledRef = useRef(false);
  const activeXhrRef = useRef<XMLHttpRequest | null>(null);

  const [queueSnapshot, setQueueSnapshot] = useState<QrQueueSnapshot>(EMPTY_SNAPSHOT);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      activeXhrRef.current?.abort();
    };
  }, []);

  const fetchQueue = useCallback(async () => {
    if (isUploadingRef.current || isPollingRef.current) return;
    isPollingRef.current = true;
    const controller = new AbortController();
    const abortTimer = window.setTimeout(() => controller.abort(), 3500);
    try {
      const res = await fetch('/api/qr/queue', {
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!res.ok) return;
      const data: QrQueueSnapshot = await res.json();
      if (isMountedRef.current) {
        setQueueSnapshot(data);
      }
    } catch {
      // Ignore transient mobile polling errors / timeouts
    } finally {
      window.clearTimeout(abortTimer);
      isPollingRef.current = false;
    }
  }, []);

  useEffect(() => {
    void fetchQueue();
    const timer = window.setInterval(() => {
      void fetchQueue();
    }, 1500);
    const handleResume = () => {
      if (document.visibilityState !== 'hidden') {
        void fetchQueue();
      }
    };
    document.addEventListener('visibilitychange', handleResume);
    window.addEventListener('pageshow', handleResume);
    window.addEventListener('focus', handleResume);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', handleResume);
      window.removeEventListener('pageshow', handleResume);
      window.removeEventListener('focus', handleResume);
    };
  }, [fetchQueue]);

  const cancelActiveUpload = () => {
    cancelledRef.current = true;
    activeXhrRef.current?.abort();
  };

  const enqueueFiles = async (files: File[]) => {
    if (files.length === 0 || isUploadingRef.current) return;
    cancelledRef.current = false;
    isUploadingRef.current = true;
    setIsUploading(true);
    setErrorMsg(null);
    setUploadProgress(`PREPARING 1/${files.length}...`);
    setStatusMessage(`Preparing ${files.length} file${files.length > 1 ? 's' : ''} for scan queue...`);

    let totalQueued = 0;
    let latestQueue: QrQueueSnapshot | undefined;

    try {
      for (let i = 0; i < files.length; i += 1) {
        if (!isMountedRef.current || cancelledRef.current) break;
        const idxLabel = `${i + 1}/${files.length}`;
        setUploadProgress(`OPTIMIZING ${idxLabel}...`);
        const prepared = await prepareFileForUpload(files[i]);
        if (!isMountedRef.current || cancelledRef.current) break;
        setUploadProgress(`UPLOADING ${idxLabel} (0%)...`);
        setStatusMessage(
          `Uploading ${idxLabel} (${Math.max(1, Math.round(prepared.size / 1024))} KB)...`
        );

        const data = await uploadSingleFileWithRetry(
          prepared,
          (pct) => {
            if (isMountedRef.current) {
              setUploadProgress(`UPLOADING ${idxLabel} (${pct}%)...`);
            }
          },
          (xhr) => {
            activeXhrRef.current = xhr;
          },
          () => cancelledRef.current
        );
        totalQueued += data.enqueued_count ?? 1;
        if (data.queue && isMountedRef.current) {
          latestQueue = data.queue;
          setQueueSnapshot(data.queue);
        }
      }

      if (isMountedRef.current && !cancelledRef.current) {
        if (latestQueue) {
          setQueueSnapshot(latestQueue);
        }
        setStatusMessage(
          `Queued ${totalQueued} file${totalQueued > 1 ? 's' : ''} for automatic AI scanning!`
        );
      }
    } catch (err: unknown) {
      if (isMountedRef.current) {
        const reason = err instanceof Error ? err.message : 'Could not upload media';
        setErrorMsg(
          totalQueued > 0
            ? `Queued ${totalQueued}/${files.length} file${totalQueued > 1 ? 's' : ''}, then failed: ${reason}`
            : reason
        );
        setStatusMessage(null);
      }
    } finally {
      activeXhrRef.current = null;
      isUploadingRef.current = false;
      if (isMountedRef.current) {
        setIsUploading(false);
        setUploadProgress(null);
      }
      void fetchQueue();
    }
  };

  return (
    <div className="min-h-screen bg-[#090d14] text-slate-100">
      {/* Top Mobile Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-[#0b101b]/95 px-4 py-3.5 backdrop-blur-md">
        <div className="mx-auto flex max-w-lg items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-sky-500/30 bg-sky-500/10 text-sky-400">
              <Shield className="h-5 w-5" />
            </div>
            <div>
              <h1 className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-white">
                Sentinel Mobile Uploader
              </h1>
              <p className="font-mono-tabular text-[10px] text-slate-400">
                Automatic Dual-Model YOLO Queue
              </p>
            </div>
          </div>

          <a
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono-tabular text-[11px] font-bold text-slate-200 transition hover:border-sky-400/50 hover:text-sky-300"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            DASHBOARD
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-lg space-y-5 px-4 py-5">
        {/* Upload Action Card */}
        <section className="rounded-2xl border border-slate-800 bg-[#0d1320] p-5 shadow-xl">
          <div className="mb-3 flex items-center justify-between">
            <h2
              id={formHeadingId}
              className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-sky-300"
            >
              Instant Media Upload & Auto-Scan
            </h2>
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 font-mono-tabular text-[10px] font-bold text-emerald-300">
              <Sparkles className="h-3 w-3" />
              AUTO-QUEUE ON
            </span>
          </div>

          <p className="mb-4 font-mono-tabular text-xs text-slate-300">
            Select one or multiple photos/videos below. Each upload is automatically queued, scanned by the AI model, and added to the main dashboard history.
          </p>

          <form
            aria-labelledby={formHeadingId}
            action="/api/qr/enqueue"
            method="POST"
            encType="multipart/form-data"
            onSubmit={(e) => e.preventDefault()}
            className="space-y-3"
          >
            {/* Multi-File Gallery Input (Accessible visually-hidden) */}
            <input
              id={galleryInputId}
              name="files"
              type="file"
              multiple
              disabled={isUploading}
              accept="image/*,video/*,application/zip,.jpg,.jpeg,.png,.webp,.bmp,.heic,.heif,.jfif,.mp4,.mov,.avi,.webm,.mkv,.m4v,.zip"
              onChange={(e) => {
                const picked = e.target.files ? Array.from(e.target.files) : [];
                e.target.value = '';
                if (picked.length > 0) {
                  void enqueueFiles(picked);
                }
              }}
              className="visually-hidden"
            />
            <label
              htmlFor={galleryInputId}
              style={{ minHeight: '54px', fontSize: 'max(1rem, 1em)' }}
              className={`flex w-full items-center justify-center gap-2.5 rounded-xl px-4 py-3.5 font-mono-tabular font-bold text-slate-950 shadow-[0_0_24px_rgba(56,189,248,0.25)] transition ${
                isUploading
                  ? 'bg-sky-500/80 cursor-wait'
                  : 'bg-sky-500 hover:bg-sky-400 cursor-pointer'
              }`}
            >
              {isUploading ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin" />
                  <span>{uploadProgress || 'UPLOADING TO QUEUE...'}</span>
                </>
              ) : (
                <>
                  <Upload className="h-5 w-5" />
                  <span>UPLOAD PHOTOS / VIDEOS</span>
                </>
              )}
            </label>

            {/* Direct Mobile Camera Capture Input */}
            <input
              id={cameraInputId}
              name="camera_file"
              type="file"
              disabled={isUploading}
              capture="environment"
              accept="image/*,video/*"
              onChange={(e) => {
                const picked = e.target.files ? Array.from(e.target.files) : [];
                e.target.value = '';
                if (picked.length > 0) {
                  void enqueueFiles(picked);
                }
              }}
              className="visually-hidden"
            />
            <label
              htmlFor={cameraInputId}
              style={{ minHeight: '52px', fontSize: 'max(1rem, 1em)' }}
              className={`flex w-full items-center justify-center gap-2.5 rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 font-mono-tabular font-bold text-slate-100 transition ${
                isUploading
                  ? 'opacity-60 cursor-wait'
                  : 'hover:border-sky-400/50 hover:text-sky-300 cursor-pointer'
              }`}
            >
              <Camera className="h-5 w-5 text-sky-400" />
              <span>TAKE CAMERA PHOTO / VIDEO</span>
            </label>

            {isUploading && (
              <button
                type="button"
                onClick={cancelActiveUpload}
                className="flex w-full items-center justify-center rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 font-mono-tabular text-xs font-bold text-rose-300 transition hover:bg-rose-500/20 cursor-pointer"
              >
                CANCEL CURRENT UPLOAD
              </button>
            )}
          </form>

          {/* Accessible Live Feedback Banner */}
          <div role="status" aria-live="polite" className="mt-3">
            {statusMessage && (
              <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-3 font-mono-tabular text-xs font-semibold text-emerald-300">
                {statusMessage}
              </div>
            )}
            {errorMsg && (
              <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 font-mono-tabular text-xs font-semibold text-rose-300">
                {errorMsg}
              </div>
            )}
          </div>
        </section>

        {/* Live Queue Status & Results Card */}
        <section className="rounded-2xl border border-slate-800 bg-[#0d1320] p-5 shadow-xl">
          <div className="mb-3 flex items-center justify-between border-b border-slate-800 pb-3">
            <span className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-white">
              Live Scan Queue ({queueSnapshot.jobs.length})
            </span>
            <div className="flex items-center gap-3 font-mono-tabular text-[11px]">
              <span className="text-amber-300">
                Queued: <strong>{queueSnapshot.queued_count}</strong>
              </span>
              <span className="text-sky-300">
                Scanning: <strong>{queueSnapshot.processing_count}</strong>
              </span>
              <span className="text-emerald-300">
                Done: <strong>{queueSnapshot.completed_count}</strong>
              </span>
            </div>
          </div>

          <div className="space-y-3">
            {queueSnapshot.jobs.length === 0 ? (
              <div className="rounded-xl border border-slate-800/80 bg-[#080c14] py-8 text-center font-mono-tabular text-xs text-slate-400">
                No uploads in queue yet. Tap above to upload photos or videos!
              </div>
            ) : (
              queueSnapshot.jobs.map((job) => {
                const ev = job.event;
                return (
                  <div
                    key={job.job_id}
                    className={`rounded-xl border p-3 ${
                      job.status === 'processing'
                        ? 'border-sky-500/50 bg-sky-500/10'
                        : job.status === 'queued'
                        ? 'border-amber-500/40 bg-amber-500/5'
                        : job.status === 'completed'
                        ? 'border-slate-800 bg-[#080c14]'
                        : 'border-rose-500/40 bg-rose-500/10'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate font-mono-tabular text-xs font-bold text-white">
                        {job.original_name}
                      </div>
                      {job.status === 'queued' && (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded bg-amber-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-amber-300">
                          <Clock className="h-3 w-3" />
                          QUEUED #{job.position}
                        </span>
                      )}
                      {job.status === 'processing' && (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded bg-sky-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          SCANNING...
                        </span>
                      )}
                      {job.status === 'completed' && ev && (
                        <span
                          className={`inline-flex shrink-0 items-center gap-1 rounded px-2 py-0.5 font-mono-tabular text-[10px] font-bold ${
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
                          {ev.primary_target === 'None'
                            ? 'CLEAR'
                            : `${ev.primary_target} (${Math.round(ev.confidence * 100)}%)`}
                        </span>
                      )}
                      {job.status === 'failed' && (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded bg-rose-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-rose-300">
                          <AlertTriangle className="h-3 w-3" />
                          FAILED
                        </span>
                      )}
                    </div>

                    {ev && (
                      <div className="mt-2.5 flex items-center gap-3 border-t border-slate-800/80 pt-2.5">
                        <img
                          src={ev.thumbnail_url}
                          alt={ev.primary_target}
                          className="h-16 w-24 shrink-0 rounded-lg border border-slate-700 object-cover"
                        />
                        <div className="min-w-0 font-mono-tabular text-[11px]">
                          <div className="font-bold text-slate-200">
                            Event #{ev.id} • {ev.action_taken}
                          </div>
                          <div className="mt-0.5 text-slate-400">
                            {ev.resolution} • Saved to Dashboard History
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </section>
      </main>
    </div>
  );
};
